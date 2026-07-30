# 🌙 Noor AI

**Your light to Islamic knowledge.**

A conversational Islamic Q&A system with Retrieval-Augmented Generation (RAG) over the Quran, Sahih al-Bukhari, and Sahih Muslim. Powered by AWS Bedrock (Claude Haiku 4.5 + Cohere embeddings), with streaming responses, conversation memory, verbatim citations, and school-of-thought filtering.

Live at **[noorai.elprince.net](https://noorai.elprince.net)**.

## Architecture

![Noor AI — AWS architecture](docs/architecture.svg)

> Diagram source lives in [`docs/diagram/`](docs/diagram/) (Graphviz + official AWS icons).
> Regenerate with `cd docs/diagram && npm install && node render.mjs`.

📖 Want the internals? Read the **[Technical Deep Dive](docs/DEEP_DIVE.md)** — components, request flow, and the logic of every major service with code.
🎬 Presenting it? [`docs/presentation/`](docs/presentation/) has two Marp decks — `slides.md` (portfolio video walkthrough) and `deep-dive.md` (full technical deck). Build with `cd docs/presentation && npm install && npm run html`.

**Request flow:** CloudFront serves the static Next.js app from S3 and proxies `/api/*` to a streaming Lambda Function URL — one domain, no CORS. The Lambda runs FastAPI through the [Lambda Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter) (no Docker, no API Gateway). A LangChain agent retrieves relevant verses/hadith from the Bedrock Knowledge Base, loads conversation history from DynamoDB, and streams Claude's answer back as NDJSON events.

**RAG design:** the corpus is pre-split into one file per verse/hadith with precomputed citation metadata, so retrieval units are always complete and the LLM cites verbatim from metadata — it cannot fabricate references. Vectors live in S3 Vectors (low-cost, serverless) indexed with Cohere Embed Multilingual v3 (Arabic + English).

### CloudFormation Stacks

| Stack | Purpose |
|-------|---------|
| `NoorAi-Dns` | Route 53 hosted zone (delegated subdomain) + ACM certificate |
| `NoorAi-Data` | DynamoDB chat history table (pay-per-request, TTL) |
| `NoorAi-KnowledgeBase` | Corpus S3 bucket, S3 Vectors index, Bedrock Knowledge Base + data source |
| `NoorAi-Api` | FastAPI Lambda (Web Adapter, streaming Function URL) + IAM |
| `NoorAi-Web` | Frontend S3 bucket, CloudFront distribution, Route 53 alias record |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Infrastructure | AWS CDK (TypeScript), 5 stacks |
| Backend | Python 3.12, FastAPI, LangChain, uv |
| Frontend | Next.js (static export), TypeScript, Tailwind CSS |
| LLM | AWS Bedrock — Claude Haiku 4.5 (cross-region inference profile) |
| RAG | Bedrock Knowledge Base + S3 Vectors + Cohere Embed Multilingual v3 |
| Database | DynamoDB (chat sessions, TTL) |
| Hosting | Lambda Function URL (streaming) + CloudFront + S3 |
| DNS / TLS | Route 53 + ACM |

## Project Structure

```
noor-ai/
├── infra/       → CDK stacks (TypeScript) — DNS, data, KB, API, web
├── backend/     → FastAPI + LangChain agent (Python, OOP) — managed with uv
│   └── src/scripts/  → corpus pipeline: download → build → sync
├── frontend/    → Next.js chat UI (TypeScript, Tailwind)
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
| POST | `/api/ask` | Ask a question — **streams NDJSON agent events** (retrieval, tokens, citations) |
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
uv run pytest                          # Run tests
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

~$2–12/month at low traffic. Everything is serverless/pay-per-use: Lambda, DynamoDB on-demand, S3 Vectors (a fraction of OpenSearch Serverless cost), CloudFront, and Bedrock tokens (the main variable). Route 53 hosted zone adds $0.50/month.

## License

MIT
