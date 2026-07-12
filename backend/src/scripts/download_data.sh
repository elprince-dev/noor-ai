#!/usr/bin/env bash
# Phase 0 — download raw Quran + Sahih al-Bukhari source data.
#
# Sources (open-licensed, verse/hadith-numbered):
#   Quran  : risan/quran-json       (Arabic + English translation)
#   Hadith : fawazahmed0/hadith-api (eng + ara editions of Bukhari)
#
# Idempotent: safe to re-run. Resolves the repo root from this script's
# location (backend/src/scripts) so data always lands in ingest/data/raw/.
set -euo pipefail

# backend/src/scripts -> repo root is three levels up.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
RAW_DIR="$REPO_ROOT/ingest/data/raw"

mkdir -p "$RAW_DIR/quran" "$RAW_DIR/hadith"

echo "→ Quran (Arabic + English)..."
curl -fsSL -o "$RAW_DIR/quran/quran_en.json" \
  "https://raw.githubusercontent.com/risan/quran-json/main/dist/quran_en.json"

echo "→ Sahih al-Bukhari (English)..."
curl -fsSL -o "$RAW_DIR/hadith/eng-bukhari.json" \
  "https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/eng-bukhari.min.json"

echo "→ Sahih al-Bukhari (Arabic)..."
curl -fsSL -o "$RAW_DIR/hadith/ara-bukhari.json" \
  "https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/ara-bukhari.min.json"

echo ""
echo "✓ Done. Downloaded into $RAW_DIR :"
du -h "$RAW_DIR"/quran/*.json "$RAW_DIR"/hadith/*.json