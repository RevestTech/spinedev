"""Entrypoint: uvicorn HTTP server on GRPC_PORT (default 50051) for parity with compose."""

import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("GRPC_PORT", "50051"))
    uvicorn.run(
        "tron.sandbox.server:app",
        # Binding to all interfaces is intentional: this process runs inside the
        # isolated sandbox container (no public network, drop-ALL caps, read-only
        # rootfs) and must be reachable from the API container on the docker
        # network via the service name.
        host="0.0.0.0",  # nosec B104
        port=port,
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )
