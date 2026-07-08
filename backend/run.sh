#!/bin/bash
# Entry point used by AWS Lambda Web Adapter (LWA). LWA proxies the Function
# URL request to this uvicorn server on $PORT and streams the response back.
PATH=$PATH:$LAMBDA_TASK_ROOT/bin \
    PYTHONPATH=$PYTHONPATH:/opt/python:$LAMBDA_RUNTIME_DIR \
    exec python -m uvicorn --port=$PORT src.app:app
