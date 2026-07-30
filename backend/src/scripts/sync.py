#!/usr/bin/env python3
"""Phase 2 — upload the built corpus to S3 and trigger KB ingestion.

Pipeline position:
    download_data.sh -> build_corpus.py -> [sync.py] -> Bedrock KB embeds & indexes

Two steps:
  1. Bulk-upload ingest/data/corpus/ to the KB's S3 data-source bucket
     (uses `aws s3 sync` — far faster than boto3 put_object for ~43k files).
  2. Start a Bedrock KB ingestion job (StartIngestionJob) and poll to
     completion. The KB chunks (NONE = one file per chunk), embeds each with
     Cohere Multilingual v3, and writes vectors to the S3 Vectors index.

Ingestion is incremental: re-running only processes new/changed/deleted files.

Config comes from CloudFormation stack outputs (KB id, data source id, bucket)
so you don't hand-copy IDs. Override via env vars or --flags if you prefer.

Usage:
    python3 backend/src/scripts/sync.py                 # auto-resolve from CFN
    python3 backend/src/scripts/sync.py --no-wait       # start job, don't poll
    KB_ID=... DS_ID=... CORPUS_BUCKET=... python3 ... --skip-upload
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import boto3

REPO_ROOT = Path(__file__).resolve().parents[3]
CORPUS_DIR = REPO_ROOT / "ingest" / "data" / "corpus"

KB_STACK_NAME = "NoorAi-KnowledgeBase"
REGION = "us-east-1"

# Output keys as defined in knowledge-base-stack.ts (CfnOutput logical IDs).
OUT_KB_ID = "KnowledgeBaseId"
OUT_DS_ID = "DataSourceId"
OUT_BUCKET = "CorpusBucketName"


def resolve_from_cfn(region: str) -> dict[str, str]:
    """Read KB id, data source id, and bucket name from the CFN stack outputs."""
    cfn = boto3.client("cloudformation", region_name=region)
    try:
        stacks = cfn.describe_stacks(StackName=KB_STACK_NAME)["Stacks"]
    except Exception as e:
        raise SystemExit(
            f"Could not read stack '{KB_STACK_NAME}' in {region}: {e}\n"
            "Pass --kb-id/--ds-id/--bucket or set KB_ID/DS_ID/CORPUS_BUCKET."
        )
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stacks[0].get("Outputs", [])}
    missing = [k for k in (OUT_KB_ID, OUT_DS_ID, OUT_BUCKET) if k not in outputs]
    if missing:
        raise SystemExit(f"Stack outputs missing: {missing}. Found: {list(outputs)}")
    return {
        "kb_id": outputs[OUT_KB_ID],
        "ds_id": outputs[OUT_DS_ID],
        "bucket": outputs[OUT_BUCKET],
    }


def upload_corpus(bucket: str, region: str) -> None:
    """Bulk-sync the corpus dir to s3://<bucket>/ via the AWS CLI."""
    if not CORPUS_DIR.exists():
        raise SystemExit(f"Corpus not found at {CORPUS_DIR}. Run build_corpus.py first.")

    n = sum(1 for _ in CORPUS_DIR.rglob("*.json"))
    print(f"→ Uploading {n} files from {CORPUS_DIR} to s3://{bucket}/ ...")
    # --delete keeps S3 == local, so removed corpus files are pruned and the
    # next ingestion job deletes their vectors too.
    result = subprocess.run(
        [
            "aws", "s3", "sync", str(CORPUS_DIR), f"s3://{bucket}/",
            "--region", region, "--delete", "--only-show-errors",
        ],
    )
    if result.returncode != 0:
        raise SystemExit("aws s3 sync failed.")
    print("  ✓ upload complete")


def start_ingestion(kb_id: str, ds_id: str, region: str, wait: bool) -> None:
    """Trigger a KB ingestion job and (optionally) poll to completion."""
    agent = boto3.client("bedrock-agent", region_name=region)
    print(f"→ Starting ingestion job (KB={kb_id}, DS={ds_id}) ...")
    job = agent.start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id)
    job_id = job["ingestionJob"]["ingestionJobId"]
    print(f"  ingestionJobId = {job_id}")

    if not wait:
        print("  (--no-wait) not polling; check status in the Bedrock console.")
        return

    terminal = {"COMPLETE", "FAILED"}
    while True:
        time.sleep(15)
        j = agent.get_ingestion_job(
            knowledgeBaseId=kb_id, dataSourceId=ds_id, ingestionJobId=job_id
        )["ingestionJob"]
        status = j["status"]
        stats = j.get("statistics", {})
        print(
            f"  status={status} "
            f"scanned={stats.get('numberOfDocumentsScanned', '?')} "
            f"indexed={stats.get('numberOfNewDocumentsIndexed', '?')} "
            f"failed={stats.get('numberOfDocumentsFailed', '?')}"
        )
        if status in terminal:
            if status == "FAILED":
                reasons = j.get("failureReasons", [])
                raise SystemExit(f"Ingestion FAILED: {reasons}")
            print("  ✓ ingestion COMPLETE")
            return


def main() -> None:
    p = argparse.ArgumentParser(description="Upload corpus + trigger KB ingestion.")
    p.add_argument("--region", default=REGION)
    p.add_argument("--kb-id", help="override Knowledge Base id")
    p.add_argument("--ds-id", help="override Data Source id")
    p.add_argument("--bucket", help="override corpus bucket name")
    p.add_argument("--skip-upload", action="store_true", help="only trigger ingestion")
    p.add_argument("--no-wait", action="store_true", help="don't poll the job")
    args = p.parse_args()

    import os

    kb_id = args.kb_id or os.environ.get("KB_ID")
    ds_id = args.ds_id or os.environ.get("DS_ID")
    bucket = args.bucket or os.environ.get("CORPUS_BUCKET")

    if not (kb_id and ds_id and bucket):
        resolved = resolve_from_cfn(args.region)
        kb_id = kb_id or resolved["kb_id"]
        ds_id = ds_id or resolved["ds_id"]
        bucket = bucket or resolved["bucket"]

    print(f"KB={kb_id}  DS={ds_id}  bucket={bucket}  region={args.region}\n")

    if not args.skip_upload:
        upload_corpus(bucket, args.region)

    start_ingestion(kb_id, ds_id, args.region, wait=not args.no_wait)


if __name__ == "__main__":
    main()