#!/usr/bin/env python3
"""Phase 1 — transform raw Quran + Bukhari dumps into KB-ready corpus files.

Reads the raw sources downloaded by ``download_data.sh`` and writes one file
per verse / per hadith, each paired with a ``.metadata.json`` sidecar that
Bedrock Knowledge Base uses for citations and metadata filtering.

Design: chunking strategy is NONE (one file == one chunk), so retrieval units
are always whole verses / whole hadith — never truncated or merged. The
``citation`` field is precomputed here so the LLM cites verbatim from metadata
and cannot fabricate references.

Pure stdlib, no AWS calls, no embedding. Offline, free, idempotent.

Layout (relative to repo root):
    ingest/data/raw/quran/quran_en.json
    ingest/data/raw/hadith/{eng,ara}-bukhari.json      -> input
    ingest/data/corpus/quran/<surah>_<ayah>.json(+.metadata.json)
    ingest/data/corpus/hadith/bukhari/<n>.json(+.metadata.json)  -> output
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

# repo root is three levels up from backend/src/scripts
REPO_ROOT = Path(__file__).resolve().parents[3]
RAW = REPO_ROOT / "ingest" / "data" / "raw"
CORPUS = REPO_ROOT / "ingest" / "data" / "corpus"


def _meta_str(value: str, embed: bool) -> dict:
    return {
        "value": {"type": "STRING", "stringValue": value},
        "includeForEmbedding": embed,
    }


def _meta_num(value: int, embed: bool) -> dict:
    return {
        "value": {"type": "NUMBER", "numberValue": value},
        "includeForEmbedding": embed,
    }


def _write_pair(out_dir: Path, stem: str, content: dict, metadata: dict) -> None:
    """Write <stem>.json and <stem>.json.metadata.json into out_dir."""
    doc = out_dir / f"{stem}.json"
    doc.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    sidecar = out_dir / f"{stem}.json.metadata.json"
    sidecar.write_text(
        json.dumps({"metadataAttributes": metadata}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_quran() -> int:
    """One file per verse. Embeds surah name + English + Arabic."""
    surahs = json.loads((RAW / "quran" / "quran_en.json").read_text(encoding="utf-8"))
    out_dir = CORPUS / "quran"
    out_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for surah in surahs:
        s_num = surah["id"]
        s_name = surah["transliteration"]  # e.g. "Al-Baqarah"
        for verse in surah["verses"]:
            a_num = verse["id"]
            arabic = verse["text"]
            english = verse["translation"]
            citation = f"Quran {s_num}:{a_num}"

            # Embeddable text: name gives topical signal, English carries meaning,
            # Arabic lets multilingual queries match the original.
            text = f"Surah {s_name} ({s_num}:{a_num})\n{english}\n{arabic}"

            content = {
                "text": text,
                "arabic": arabic,
                "translation": english,
                "surah_name": s_name,
                "surah_number": s_num,
                "ayah_number": a_num,
                "citation": citation,
            }
            metadata = {
                "source_type": _meta_str("quran", embed=False),
                "surah_number": _meta_num(s_num, embed=False),
                "ayah_number": _meta_num(a_num, embed=False),
                "surah_name": _meta_str(s_name, embed=True),
                "citation": _meta_str(citation, embed=False),
            }
            _write_pair(out_dir, f"{s_num}_{a_num}", content, metadata)
            count += 1
    return count


def build_bukhari() -> int:
    """One file per hadith, merging English + Arabic on hadithnumber."""
    eng = json.loads((RAW / "hadith" / "eng-bukhari.json").read_text(encoding="utf-8"))
    ara = json.loads((RAW / "hadith" / "ara-bukhari.json").read_text(encoding="utf-8"))

    collection = "Sahih al-Bukhari"
    sections: dict[str, str] = eng["metadata"]["sections"]  # {"1": "Revelation", ...}
    ara_by_num = {h["hadithnumber"]: h for h in ara["hadiths"]}

    out_dir = CORPUS / "hadith" / "bukhari"
    out_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for h in eng["hadiths"]:
        num = h["hadithnumber"]
        english = h["text"]
        arabic = ara_by_num.get(num, {}).get("text", "")
        book_num = h.get("reference", {}).get("book")
        book_name = sections.get(str(book_num), "") if book_num is not None else ""
        citation = f"{collection} {num}"

        text_parts = [f"{collection} {num}"]
        if book_name:
            text_parts.append(f"Book: {book_name}")
        text_parts.append(english)
        if arabic:
            text_parts.append(arabic)
        text = "\n".join(text_parts)

        content = {
            "text": text,
            "english": english,
            "arabic": arabic,
            "collection": collection,
            "book_name": book_name,
            "hadith_number": num,
            "grade": "Sahih",  # Bukhari is Sahih by definition; source grades[] is empty
            "citation": citation,
        }
        metadata = {
            "source_type": _meta_str("hadith", embed=False),
            "collection": _meta_str(collection, embed=True),
            "hadith_number": _meta_num(num, embed=False),
            "book_name": _meta_str(book_name, embed=True) if book_name else _meta_str("Uncategorized", embed=False),
            "grade": _meta_str("Sahih", embed=False),
            "citation": _meta_str(citation, embed=False),
        }
        _write_pair(out_dir, str(num), content, metadata)
        count += 1
    return count


def main() -> None:
    if not RAW.exists():
        raise SystemExit(f"Raw data not found at {RAW}. Run download_data.sh first.")

    # Clean rebuild so stale files never linger.
    if CORPUS.exists():
        shutil.rmtree(CORPUS)

    print("Building Quran corpus...")
    n_quran = build_quran()
    print(f"  ✓ {n_quran} verses -> {CORPUS / 'quran'}")

    print("Building Bukhari corpus...")
    n_hadith = build_bukhari()
    print(f"  ✓ {n_hadith} hadith -> {CORPUS / 'hadith' / 'bukhari'}")

    # Sanity check: expected counts.
    assert n_quran == 6236, f"expected 6236 verses, got {n_quran}"
    assert n_hadith == 7589, f"expected 7589 hadith, got {n_hadith}"

    total_files = (n_quran + n_hadith) * 2  # doc + sidecar each
    print(f"\n✓ Corpus ready: {n_quran + n_hadith} items ({total_files} files).")


if __name__ == "__main__":
    main()