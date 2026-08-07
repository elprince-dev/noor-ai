"""Observability package — structured tracing for the Noor-AI pipeline.

One structured JSON trace per /api/ask request. Single-responsibility
collaborators (context, cost, truncation, sink, repository, finalizer)
wired together via constructor injection; see design doc for the map.

Nothing in this package imports from app.py, chains, or services —
dependencies flow one way (pipeline → observability).
"""
