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

Dependencies are bundled on the host with `uv` during `cdk synth`/`deploy`
— **no Docker required**. CDK resolves the dependency set from `pyproject.toml`
and installs Lambda-compatible wheels (linux/x86_64, py3.12) into the asset,
so there is no manual `requirements.txt` step.

Just deploy from the infra directory:

```bash
cd ../infra
npx cdk deploy
```

> Requires `uv` on the machine running the deploy. If `uv` is missing, the
> bundling step fails fast with an install hint (it does not fall back to Docker).
