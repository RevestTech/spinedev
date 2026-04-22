"""Entrypoint: uvicorn HTTP server on GRPC_PORT (default 50051) for parity with compose."""

import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("GRPC_PORT", "50051"))
    uvicorn.run(
        "tron.sandbox.server:app",
        host="0.0.0.0",
        port=port,
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )
