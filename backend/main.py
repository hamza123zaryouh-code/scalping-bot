"""FastAPI application entry point."""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from json import JSONDecodeError
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.websockets import WebSocketState

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autonomous_xauusd.memory_layer import MemoryLayer
from backend.api.routes import analytics, auth, backtest, dashboard, memory, optimizer, reports, risk, signals, trading
from backend.core.config import Settings, get_settings
from backend.core.logging import setup_logging
from backend.core.security import decode_access_token
from backend.websocket.manager import ws_manager

logger = logging.getLogger(__name__)


def _bootstrap_autonomous_database(settings: Settings) -> None:
    memory = MemoryLayer(settings.database_url)
    memory.initialize()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(level="DEBUG" if not settings.is_production else "INFO")
    logger.info("XAUUSD Trading Platform API v%s starting (%s)", settings.app_version, settings.app_env)

    try:
        _bootstrap_autonomous_database(settings)
        logger.info("Autonomous database schema initialized successfully.")
    except Exception as exc:
        logger.warning("Autonomous database unavailable (offline mode): %s", exc)

    yield
    logger.info("XAUUSD Trading Platform API shutting down")


def _extract_websocket_token(websocket: WebSocket) -> str | None:
    auth_header = websocket.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return websocket.query_params.get("token")


async def _close_policy_violation(websocket: WebSocket, reason: str) -> None:
    if websocket.client_state is WebSocketState.CONNECTED:
        await websocket.send_json({"type": "error", "error": reason})
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=reason)


def _parse_client_message(raw_message: str) -> dict[str, object]:
    import json

    try:
        payload = json.loads(raw_message)
    except JSONDecodeError as exc:
        raise ValueError("WebSocket messages must be JSON.") from exc

    if not isinstance(payload, dict):
        raise ValueError("WebSocket messages must be JSON objects.")

    message_type = str(payload.get("type", "")).strip()
    if not message_type:
        raise ValueError("WebSocket message type is required.")

    return payload


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="XAUUSD Trading Platform API",
        description=(
            "Production-grade FTMO-compliant XAUUSD trading system.\n\n"
            "Provides REST endpoints for dashboard, risk management, "
            "signal streaming, analytics, and report generation."
        ),
        version=settings.app_version,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_logger(request: Request, call_next):
        logger.debug("%s %s", request.method, request.url.path)
        response = await call_next(request)
        logger.debug("%s %s -> %d", request.method, request.url.path, response.status_code)
        return response

    @app.exception_handler(Exception)
    async def global_exc_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    @app.get("/api/v1/health", tags=["system"], summary="Health check")
    async def health():
        return {"status": "healthy", "version": settings.app_version, "env": settings.app_env}

    prefix = "/api/v1"
    app.include_router(auth.router, prefix=f"{prefix}/auth", tags=["auth"])
    app.include_router(backtest.router, prefix=f"{prefix}/backtest", tags=["backtest"])
    app.include_router(dashboard.router, prefix=f"{prefix}/dashboard", tags=["dashboard"])
    app.include_router(risk.router, prefix=f"{prefix}/risk", tags=["risk"])
    app.include_router(reports.router, prefix=f"{prefix}/reports", tags=["reports"])
    app.include_router(signals.router, prefix=f"{prefix}/signals", tags=["signals"])
    app.include_router(analytics.router, prefix=f"{prefix}/analytics", tags=["analytics"])
    app.include_router(trading.router, prefix=f"{prefix}/trading", tags=["trading"])
    app.include_router(memory.router, prefix=f"{prefix}/memory", tags=["memory"])
    app.include_router(optimizer.router, prefix=f"{prefix}/optimizer", tags=["optimizer"])

    @app.websocket("/ws/live")
    async def websocket_live(websocket: WebSocket):
        token = _extract_websocket_token(websocket)
        if not token:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Authentication token required.",
            )
            return

        try:
            user = decode_access_token(token)
        except ValueError:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Invalid authentication token.",
            )
            return

        user_id = str(user.get("sub", "")).strip()
        if not user_id:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Authenticated user is missing a subject.",
            )
            return

        await ws_manager.connect(
            websocket,
            user_id=user_id,
            role=str(user.get("role", "viewer")),
        )
        await ws_manager.send_json(
            websocket,
            {"type": "connection.accepted", "payload": {"user": user_id}},
        )

        try:
            while True:
                raw_message = await websocket.receive_text()
                try:
                    message = _parse_client_message(raw_message)
                except ValueError as exc:
                    await ws_manager.send_json(websocket, {"type": "error", "error": str(exc)})
                    continue

                message_type = str(message["type"])
                if message_type == "ping":
                    await ws_manager.send_json(websocket, {"type": "pong"})
                    continue

                if message_type == "subscribe":
                    await ws_manager.send_json(
                        websocket,
                        {
                            "type": "subscription.updated",
                            "payload": {"channels": message.get("channels", [])},
                        },
                    )
                    continue

                await ws_manager.send_json(
                    websocket,
                    {
                        "type": "error",
                        "error": f"Unsupported client message type '{message_type}'.",
                    },
                )
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)
        except Exception as exc:
            ws_manager.disconnect(websocket)
            await _close_policy_violation(websocket, f"WebSocket connection terminated: {exc}")

    return app


app = create_app()


def serve() -> None:
    settings = get_settings()
    uvicorn.run(
        "backend.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=not settings.is_production,
        log_level="warning",
    )


if __name__ == "__main__":
    serve()
