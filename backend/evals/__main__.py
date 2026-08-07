"""`python -m evals` entry point — delegates to the CLI composition root."""
from evals.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
