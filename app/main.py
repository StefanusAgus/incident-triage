"""FastAPI application lifecycle and local server entry point."""

from contextlib import asynccontextmanager
from time import monotonic

import uvicorn
from fastapi import FastAPI

from app.config import Settings
from app.constants import APP_TITLE
from app.constants import CORRELATION_ID_HEADER
from app.db.database import build_engine, initialize_database, save_correlation_trace
from app.observability import (
    announce_observability,
    bind_correlation_id,
    configure_observability,
    current_trace,
    log_step,
    reset_correlation_id,
    reset_trace,
    resolve_correlation_id,
    start_trace,
)
from app.routes import router


def create_app(settings: Settings | None = None) -> FastAPI:
    configure_observability()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime_settings = settings if settings is not None else Settings()
        app.state.settings = runtime_settings
        engine = build_engine(runtime_settings.database_url)
        app.state.engine = engine
        try:
            initialize_database(engine)
            announce_observability()
            yield
        finally:
            engine.dispose()

    app = FastAPI(title=APP_TITLE, lifespan=lifespan)
    app.include_router(router)

    @app.middleware("http")
    async def correlation_id(request, call_next):
        correlation_id = resolve_correlation_id(request.headers.get(CORRELATION_ID_HEADER))
        request.state.correlation_id = correlation_id
        request.state.chat_messages = []
        token = bind_correlation_id(correlation_id)
        trace_token = start_trace()
        started_at = monotonic()
        log_step("request:start", method=request.method, path=request.url.path)
        try:
            response = await call_next(request)
            response.headers[CORRELATION_ID_HEADER] = correlation_id
            log_step(
                "request:complete",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round((monotonic() - started_at) * 1000, 2),
            )
            return response
        except Exception as exc:
            log_step(
                "request:error",
                method=request.method,
                path=request.url.path,
                failed_step="request",
                error_type=type(exc).__name__,
                duration_ms=round((monotonic() - started_at) * 1000, 2),
            )
            raise
        finally:
            try:
                request_session = getattr(request.state, "db_session", None)
                if request_session is not None:
                    request_session.rollback()
                save_correlation_trace(
                    request.app.state.engine,
                    correlation_id,
                    current_trace(),
                    request.state.chat_messages,
                )
            except Exception as exc:
                log_step(
                    "observability:persistence_error",
                    failed_step="trace_persistence",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            reset_trace(trace_token)
            reset_correlation_id(token)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    settings = Settings()
    uvicorn.run(
        "app.main:app", host="127.0.0.1", port=settings.port, access_log=False,
    )
