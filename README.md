# 🌙 Noor AI

**Your light to Islamic knowledge.**

A conversational Islamic Q&A system with Retrieval-Augmented Generation (RAG) over the Quran, Sahih al-Bukhari, and Sahih Muslim. Powered by AWS Bedrock (Claude Haiku 4.5 + Cohere embeddings), with streaming responses, conversation memory, verbatim citations, and school-of-thought filtering — plus full **evaluation and observability**: per-request structured traces, a CloudWatch ops dashboard and alarm, an offline eval harness with a versioned golden dataset, LLM-as-judge scoring, and a user feedback loop that feeds bad production queries back into the eval dataset.

Live at **[noorai.elprince.net](https://noorai.elprince.net)**.

## Architecture

![Noor AI — AWS architecture](docs/architecture.svg)

> Diagram source lives in [`docs/diagram/`](docs/diagram/) (Graphviz + official AWS icons).
> Regenerate with `cd docs/diagram && npm install && node render.mjs`.

📖 Want the internals? Read the **[Technical Deep Dive](docs/DEEP_DIVE.md)** — components, request flow, and the logic of every major service with code.
🎬 Presenting it? [`docs/presentation/`](docs/presentation/) has two Marp decks — `slides.md` (portfolio video walkthrough) and `deep-dive.md` (full technical deck). Build with `cd docs/presentation && npm install && npm run html`.

**Request flow:** CloudFront serves the static Next.js app from S3 and proxies `/api/*` to a streaming Lambda Function URL — one domain, no CORS. The Lambda runs FastAPI through the [Lambda Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter) (no Docker, no API Gateway). A LangChain agent retrieves relevant verses/hadith from the Bedrock Knowledge Base, loads conversation history from DynamoDB, and streams Claude's answer back as NDJSON events. Every request is assigned a **Request ID** (delivered to the client in the stream) and produces a **structured trace** — query, retrieved chunks with scores, final prompt, response, TTFT, latency, token counts, and estimated cost — emitted to CloudWatch Logs and persisted to DynamoDB for 90 days.

**RAG design:** the corpus is pre-split into one file per verse/hadith with precomputed citation metadata, so retrieval units are always complete and the LLM cites verbatim from metadata — it cannot fabricate references. Vectors live in S3 Vectors (low-cost, serverless) indexed with Cohere Embed Multilingual v3 (Arabic + English).

### CloudFormation Stacks

| Stack | Purpose |
|-------|---------|
| `NoorAi-Dns` | Route 53 hosted zone (delegated subdomain) + ACM certificate |
| `NoorAi-Data` | DynamoDB tables (pay-per-request): chat history (TTL), request traces (TTL 90 days), user feedback (GSI on rating) |
| `NoorAi-KnowledgeBase` | Corpus S3 bucket, S3 Vectors index, Bedrock Knowledge Base + data source |
| `NoorAi-Api` | FastAPI Lambda (Web Adapter, streaming Function URL) + IAM |
| `NoorAi-Web` | Frontend S3 bucket, CloudFront distribution, Route 53 alias record |
| `NoorAi-Observability` | Metric filters over trace logs, CloudWatch dashboard (`NoorAi-Traces`), error-rate alarm, optional SNS email |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Infrastructure | AWS CDK (TypeScript), 6 stacks |
| Backend | Python 3.12, FastAPI, LangChain, uv |
| Frontend | Next.js (static export), TypeScript, Tailwind CSS |
| LLM | AWS Bedrock — Claude Haiku 4.5 (cross-region inference profile) |
| RAG | Bedrock Knowledge Base + S3 Vectors + Cohere Embed Multilingual v3 |
| Database | DynamoDB (chat sessions, traces, feedback — all TTL/pay-per-request) |
| Observability | Structured JSON traces → CloudWatch Logs, metric filters, dashboard, alarm |
| Evaluation | Offline eval harness (`backend/evals/`), golden dataset, Amazon Nova Pro judge |
| Hosting | Lambda Function URL (streaming) + CloudFront + S3 |
| DNS / TLS | Route 53 + ACM |

## Project Structure

```
noor-ai/
├── infra/       → CDK stacks (TypeScript) — DNS, data, KB, API, web, observability
├── backend/     → FastAPI + LangChain agent (Python, OOP) — managed with uv
│   ├── src/observability/  → per-request trace capture, cost estimation, emission, persistence
│   ├── src/feedback/       → thumbs up/down feedback API (POST /api/feedback)
│   ├── src/scripts/        → corpus pipeline: download → build → sync
│   └── evals/              → offline eval harness: golden dataset, runner, metrics, judge, triage CLI
├── frontend/    → Next.js chat UI (TypeScript, Tailwind) + feedback controls
└── ingest/      → corpus data (raw dumps + built KB-ready files, gitignored)
```

## Prerequisites

- AWS Account with Bedrock model access enabled (Claude Haiku 4.5, Cohere Embed Multilingual v3)
- AWS CLI configured (`aws configure`)
- Node.js 18+
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- A domain (optional) — the stack hosts `noorai.<your-domain>` via a delegated Route 53 subdomain

> **No Docker required.** The Lambda is bundled on the host with `uv` during
> `cdk synth`/`deploy`, targeting the Lambda runtime (linux/x86_64, py3.12).

## Getting Started

### 1. Clone & Setup

```bash
git clone <your-repo>
cd noor-ai
```

### 2. Build the Frontend (CDK deploys it)

```bash
cd frontend
npm install
npm run build     # Static export to /out — CDK reads from here
```

### 3. Deploy Infrastructure

```bash
cd infra
npm install

# Bootstrap CDK (first time only)
npx cdk bootstrap

# Deploy everything — Python deps are bundled automatically with uv
npx cdk deploy --all
```

Notes:
- The `NoorAi-Dns` stack outputs 4 nameservers. Add them as an **NS record** for the `noorai` subdomain at your registrar (one-time). The ACM cert then validates automatically.
- The `NoorAi-Web` stack outputs the **CloudFront URL**; once DNS delegation is live, the custom domain works too.

### 4. Build & Ingest the Corpus (RAG)

```bash
# 1. Download raw Quran + Bukhari + Muslim dumps
bash backend/src/scripts/download_data.sh

# 2. Transform into KB-ready files (one verse/hadith per file + citation metadata)
python3 backend/src/scripts/build_corpus.py

# 3. Upload to S3 and trigger the Bedrock KB ingestion job
#    (resolves KB id / bucket from CloudFormation outputs automatically)
python3 backend/src/scripts/sync.py
```

Ingestion is incremental — re-running `sync.py` only processes new/changed/deleted files.

### 5. Run Backend Locally (Optional)

```bash
cd backend

uv sync --extra dev
cp .env.example .env    # defaults work once CDK is deployed

uv run uvicorn src.app:app --reload --port 8000
```

### Local Frontend Development

The dev API URL lives in `frontend/.env.development` (already committed), which
Next.js loads only for `next dev` — so production builds are unaffected:

```bash
cd frontend
npm install
npm run dev   # uses NEXT_PUBLIC_API_URL from .env.development
```

## API Endpoints

All routes are namespaced under `/api` (identical in local dev, the Lambda
Function URL, and CloudFront — no path rewriting anywhere).

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/ask` | Ask a question — **streams NDJSON agent events** (`meta` with request ID, retrieval, tokens, citations, `done`) |
| POST | `/api/feedback` | Rate a response — `{"request_id": "...", "rating": "up"\|"down", "comment?": "..."}` → 204 |
| POST | `/api/sessions` | Create a new conversation session |
| GET | `/api/health` | Health check |

### Example

```bash
BASE=https://noorai.elprince.net

# Create a session
SESSION_ID=$(curl -s -X POST $BASE/api/sessions | jq -r '.session_id')

# Ask a question (response streams as NDJSON events)
curl -N -X POST $BASE/api/ask \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"What are the pillars of Islam?\", \"session_id\": \"$SESSION_ID\", \"school\": \"general\"}"

# Follow-up (same session — remembers context)
curl -N -X POST $BASE/api/ask \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"Tell me more about the third one\", \"session_id\": \"$SESSION_ID\", \"school\": \"general\"}"
```

`school` accepts `hanafi`, `maliki`, `shafii`, `hanbali`, or `general`.

## Evaluation & Observability

Quality changes are measurable and production health is visible. Four layers, each built on the previous:

### 1. Structured Trace Logging

Every `/api/ask` request gets a unique **Request ID** (uuid4), generated before any pipeline step and delivered to the client as the first stream event (`meta`), repeated in `done`, and included in error responses. The `backend/src/observability/` package assembles one JSON trace per request:

- Query, session ID, receipt timestamp (UTC)
- Retrieved chunk Source IDs with relevance scores + retrieval latency
- Final prompt, complete response, input/output token counts
- TTFT (time to first token), total latency, estimated cost in USD

Traces are emitted to CloudWatch Logs as single JSON lines (`log_type: "trace"`) and — for successful requests — persisted to the `noor-ai-traces` DynamoDB table keyed by Request ID (90-day TTL). Failed requests emit a partial trace (with the failing step and error) but are never persisted. Trace persistence failures never disturb the user's response. Set `TRACE_ENABLED=false` to turn tracing off entirely.

### 2. Ops Dashboard & Alarm

The `NoorAi-Observability` stack derives everything from the trace log lines — no extra instrumentation:

- **Dashboard `NoorAi-Traces`**: latency percentiles (p50/p90/p99), TTFT percentiles, error rate %, Bedrock throttling count, and estimated cost per UTC day
- **Alarm**: error rate > 5% over 5 minutes (zero traffic never alarms). Set `ALARM_EMAIL` in `infra/.env` before deploying to get email notifications.

### 3. Offline Eval Harness

A config-driven eval harness lives in `backend/evals/` and runs from a developer machine against the deployed Knowledge Base and Bedrock (AWS credentials required).

**Golden dataset** (`backend/evals/data/golden_dataset.jsonl`): 50+ human-annotated bilingual questions (≥20 Arabic, ≥20 English) across four categories — `direct_lookup`, `paraphrase`, `cross_lingual` (paired items sharing expected sources), and `out_of_corpus` (correct behavior = abstaining). Each item is labeled with expected Source IDs in the corpus citation grammar (`Quran 2:255`, `Sahih al-Bukhari 1`, `Sahih Muslim 534`). The dataset is fully validated on every load and versioned as `{manifest version}+{content hash}` — any content change produces a new version, so reports are always attributable to an exact dataset state.

**Run an eval:**

```bash
cd backend
uv run python -m evals run --config evals/config.yaml
```

The config controls the generation model, retrieval top-k, prompt version, and judge model:

```yaml
# backend/evals/config.yaml
model_id: us.anthropic.claude-haiku-4-5-20251001-v1:0
retrieval_top_k: 5
prompt_version: v1                        # key into PROMPT_VERSIONS registry
judge_model_id: us.amazon.nova-pro-v1:0   # must be a different model family
dataset_path: data/golden_dataset.jsonl
results_dir: results
```

Each golden item runs independently (no conversation memory) through the same retrieval and prompt code paths as production. Two metric families are computed:

- **Retrieval metrics** (deterministic, code-based): recall@k, precision@k, MRR — exact Source ID matching against the labels
- **Generation metrics** (LLM-as-judge, pass/fail rubrics): faithfulness, citation accuracy, and answer relevancy — or a single abstention rubric for out-of-corpus items. The judge is Amazon Nova Pro, deliberately a different model family than Claude to avoid self-preference bias (the harness refuses same-family configs). Failed judge calls retry once, then count as errors excluded from pass rates.

Reports are immutable JSON artifacts under `backend/evals/results/{run_id}/report.json` with aggregates broken down overall, by category, and by language, plus per-item verdicts with judge rationales.

**Compare two runs** (e.g. before/after a prompt change):

```bash
uv run python -m evals compare <run_id_a> <run_id_b>
# prints per-metric diffs and every item whose verdict flipped
```

> **Bedrock access note:** eval runs invoke Claude Haiku 4.5 (generation) and Nova Pro (judge) — enable both in your Bedrock model access settings.

### 4. Feedback Loop & Triage

Thumbs up/down controls appear under each completed assistant response (only when a Request ID was received). Ratings post to `/api/feedback` and are stored keyed by Request ID — re-rating overwrites. The triage CLI turns bad production answers into new eval cases:

```bash
cd backend

# List down-rated responses (newest first) with the query/response from each trace
uv run python -m evals triage list

# Draft a golden dataset row from a down-rated request (schema-conformant JSONL,
# question + language pre-filled from the trace; category, expected Source IDs,
# and reference answer left for human annotation)
uv run python -m evals triage draft <request_id>
```

Append the annotated draft to `golden_dataset.jsonl` and the dataset version changes automatically — closing the loop from production failure to regression test.

## Environment Variables

### Backend (`.env` for local, set by CDK on Lambda)

| Variable | Default | Description |
|----------|---------|-------------|
| `BEDROCK_MODEL_ID` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Bedrock model (cross-region inference profile) |
| `BEDROCK_REGION` | `us-east-1` | AWS region for Bedrock |
| `CHAT_TABLE` | `noor-ai-chat-history` | DynamoDB table name |
| `KNOWLEDGE_BASE_ID` | *(from CDK)* | Bedrock Knowledge Base ID for retrieval |
| `RETRIEVAL_TOP_K` | `5` | Number of passages retrieved per question |
| `SESSION_TTL_HOURS` | `72` | Session expiry (hours) |
| `MAX_HISTORY_MESSAGES` | `20` | Max messages in context |
| `TRACE_TABLE` | `noor-ai-traces` | DynamoDB table for persisted request traces |
| `FEEDBACK_TABLE` | `noor-ai-feedback` | DynamoDB table for user feedback records |
| `TRACE_ENABLED` | `true` | Set `false` to disable trace emission/persistence (request IDs still flow) |
| `TRACE_RETENTION_DAYS` | `90` | Trace TTL — expired traces vanish from the store |

### Infra (`infra/.env` — optional)

| Variable | Description |
|----------|-------------|
| `ALARM_EMAIL` | If set at deploy time, creates an SNS topic + email subscription for the error-rate alarm |

### Frontend (`.env.development` — local dev only)

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_API_URL` | Backend host for local dev (`http://localhost:8000`). Loaded only by `next dev`; production builds use same-origin `/api`, which CloudFront routes to the Lambda Function URL — no env var needed in prod. |

## Development

### Backend Commands

```bash
cd backend
uv sync --extra dev                    # Install all deps
uv run uvicorn src.app:app --reload    # Run server
uv run pytest                          # Run tests (incl. 31 Hypothesis property tests)
uv run python -m evals run --config evals/config.yaml   # Offline eval run
uv run python -m evals compare <run_a> <run_b>          # Diff two eval reports
uv run python -m evals triage list                      # Review down-rated feedback
uv add <package>                       # Add dependency
```

> Lambda dependencies are resolved and bundled automatically from
> `pyproject.toml` at deploy time — no `requirements.txt` step needed.

### Infrastructure Commands

```bash
cd infra
npx cdk synth        # Generate CloudFormation (dry run)
npx cdk deploy --all # Deploy to AWS
npx cdk diff         # Show pending changes
npm test             # CDK assertion tests (tables, dashboard, alarm)
npx cdk destroy      # Tear down (careful!)
```

### Frontend Commands

```bash
cd frontend
npm run dev        # Local dev server (port 3000)
npm run build      # Static export to /out (for S3 deployment)
npm run lint       # Lint check
```

## Cost

~$2–12/month at low traffic. Everything is serverless/pay-per-use: Lambda, DynamoDB on-demand, S3 Vectors (a fraction of OpenSearch Serverless cost), CloudFront, and Bedrock tokens (the main variable). Route 53 hosted zone adds $0.50/month. The observability layer adds near zero: metric filters are free, the alarm fits the free tier, the dashboard is ~$3/month past the free tier's three, and the trace/feedback tables are pay-per-request with TTL cleanup. Eval runs cost a few cents each (one generation + a few judge calls per golden item).

## License

MIT
