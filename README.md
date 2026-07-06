# 🌙 Noor AI

**Your light to Islamic knowledge.**

A conversational Islamic Q&A system powered by AWS Bedrock (Claude Haiku 4.5) with conversation memory and school-of-thought filtering.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Infrastructure | AWS CDK (TypeScript) |
| Backend | Python 3.12, FastAPI, LangChain, uv |
| Frontend | Next.js, TypeScript, Tailwind CSS |
| LLM | AWS Bedrock (Claude Haiku 4.5) |
| Database | DynamoDB (chat sessions) |
| Hosting | Lambda + API Gateway (backend), CloudFront + S3 (frontend) |

## Project Structure

```
noor-ai/
├── infra/       → CDK stack (TypeScript) — DynamoDB, Lambda, API Gateway
├── backend/     → FastAPI + LangChain (Python, OOP) — managed with uv
└── frontend/    → Next.js chat UI (TypeScript, Tailwind)
```

## Prerequisites

- AWS Account with Bedrock Claude model access enabled
- AWS CLI configured (`aws configure`)
- Node.js 18+
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`

> **No Docker required.** The Lambda is bundled on the host with `uv` during
> `cdk synth`/`deploy`, targeting the Lambda runtime (linux/x86_64, py3.12).

## Getting Started

### 1. Clone & Setup

```bash
git clone <your-repo>
cd noor-ai
```

### 2. Deploy Backend Infrastructure

```bash
# Install CDK dependencies
cd infra
npm install

# Bootstrap CDK (first time only)
npx cdk bootstrap

# Deploy — the Lambda's Python dependencies are bundled automatically
# on the host with uv (no Docker, no manual requirements.txt).
npx cdk deploy
```

The output will print your **API Gateway URL** — save it.

### 3. Run Backend Locally (Optional)

```bash
cd backend

# Install dependencies
uv sync --extra dev

# Create .env from example
cp .env.example .env
# Edit .env if needed (defaults work if CDK is deployed)

# Run
uv run uvicorn src.app:app --reload --port 8000
```

### 4. Build & Deploy Frontend

```bash
cd frontend
npm install
npm run build     # Generates static export in /out

# CDK deploys it automatically (reads from ../frontend/out)
cd ../infra
npx cdk deploy
```

The output will print your **CloudFront URL** — that's your live site.

> **Note:** CloudFront routes `/api/*` to API Gateway automatically.
> No CORS issues, no separate frontend URL — everything is under one domain.

### Local Frontend Development

The dev API URL lives in `frontend/.env.development` (already committed), which
Next.js loads only for `next dev` — so production builds are unaffected:

```bash
cd frontend
npm install
npm run dev   # uses NEXT_PUBLIC_API_URL from .env.development
```

## API Endpoints

All routes are namespaced under `/api` (identical in local dev, API Gateway,
and CloudFront — no path rewriting anywhere).

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/ask` | Ask a question (with session context) |
| POST | `/api/sessions` | Create a new conversation session |
| GET | `/api/health` | Health check |

### Example

```bash
# Create a session
SESSION_ID=$(curl -s -X POST https://YOUR_API/prod/api/sessions | jq -r '.session_id')

# Ask a question
curl -X POST https://YOUR_API/prod/api/ask \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"What are the pillars of Islam?\", \"session_id\": \"$SESSION_ID\", \"school\": \"general\"}"

# Follow-up (same session — remembers context)
curl -X POST https://YOUR_API/prod/api/ask \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"Tell me more about the third one\", \"session_id\": \"$SESSION_ID\", \"school\": \"general\"}"
```

## Environment Variables

### Backend (`.env` for local, set by CDK on Lambda)

| Variable | Default | Description |
|----------|---------|-------------|
| `BEDROCK_MODEL_ID` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Bedrock model (cross-region inference profile) |
| `BEDROCK_REGION` | `us-east-1` | AWS region for Bedrock |
| `CHAT_TABLE` | `noor-ai-chat-history` | DynamoDB table name |
| `SESSION_TTL_HOURS` | `72` | Session expiry (hours) |
| `MAX_HISTORY_MESSAGES` | `20` | Max messages in context |

### Frontend (`.env.development` — local dev only)

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_API_URL` | Backend host for local dev (`http://localhost:8000`). Loaded only by `next dev`, so production builds fall back to same-origin `/api`, which CloudFront routes to API Gateway — no env var needed in prod. |

## Development

### Backend Commands

```bash
cd backend
uv sync --extra dev          # Install all deps
uv run uvicorn src.app:app --reload  # Run server
uv run pytest                # Run tests
uv add <package>             # Add dependency
```

> Lambda dependencies are resolved and bundled automatically from
> `pyproject.toml` at deploy time — no `requirements.txt` step needed.

### Infrastructure Commands

```bash
cd infra
npx cdk synth      # Generate CloudFormation (dry run)
npx cdk deploy     # Deploy to AWS
npx cdk diff       # Show pending changes
npx cdk destroy    # Tear down (careful!)
```

### Frontend Commands

```bash
cd frontend
npm run dev        # Local dev server (port 3000)
npm run build      # Static export to /out (for S3 deployment)
npm run lint       # Lint check
```

## Cost

~$2-12/month at low traffic (mostly Bedrock token costs). All infrastructure is serverless/pay-per-use.

## License

MIT
