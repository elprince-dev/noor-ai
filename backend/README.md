# Noor AI Backend

## Local Development (uv)

```bash
cd backend

# Create venv and install deps
uv sync

# Install dev dependencies too
uv sync --extra dev

# Run locally
uv run uvicorn src.app:app --reload --port 8000

# Run tests
uv run pytest

# Add a new dependency
uv add <package>
```

## Deployment

CDK's `PythonFunction` construct uses pip internally to bundle dependencies.
Before deploying, export a `requirements.txt` from uv:

```bash
cd backend
uv export --no-hashes --no-dev > requirements.txt
```

Then deploy from the infra directory:

```bash
cd ../infra
npx cdk deploy
```
