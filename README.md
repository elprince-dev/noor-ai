# 🌙 Noor AI

**Your light to Islamic knowledge.**

A conversational Islamic Q&A system powered by AWS Bedrock (Claude 3.5 Sonnet) with conversation memory.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Infrastructure | AWS CDK (TypeScript) |
| Backend | Python, FastAPI, LangChain |
| Frontend | Next.js, TypeScript, Tailwind CSS |
| LLM | AWS Bedrock (Claude 3.5 Sonnet) |
| Database | DynamoDB (chat sessions) |

## Project Structure

```
noor-ai/
├── infra/       → CDK stack (TypeScript)
├── backend/     → FastAPI + LangChain (Python)
└── frontend/    → Next.js chat UI (TypeScript)
```

## Quick Start

### Prerequisites

- AWS Account with Bedrock Claude model access enabled
- Node.js 18+
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- AWS CLI configured

### Backend — Local Development

```bash
cd backend
uv sync --extra dev
uv run uvicorn src.app:app --reload --port 8000
```

### Deploy Backend

```bash
# Generate requirements.txt for CDK bundling
cd backend
uv export --no-hashes --no-dev > requirements.txt

# Deploy infrastructure
cd ../infra
npm install
npx cdk bootstrap   # First time only
npx cdk deploy
```

### Run Frontend Locally

```bash
cd frontend
npm install
echo "NEXT_PUBLIC_API_URL=https://YOUR_API_GATEWAY_URL/prod" > .env.local
npm run dev
```

### Deploy Frontend

```bash
cd frontend
npx vercel --prod
# Set NEXT_PUBLIC_API_URL in Vercel environment variables
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/ask` | Ask a question (with session context) |
| POST | `/sessions` | Create a new conversation session |
| GET | `/health` | Health check |

### Example Request

```bash
# Create session
curl -X POST https://YOUR_API/prod/sessions

# Ask a question
curl -X POST https://YOUR_API/prod/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the pillars of Islam?", "session_id": "YOUR_SESSION_ID", "school": "general"}'
```

## Cost

~$2-12/month at low traffic (mostly Bedrock token costs).
