"""FastAPI application lifecycle and local server entry point."""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.config import Settings
from app.constants import APP_TITLE
from app.constants import CORRELATION_ID_HEADER
from app.db.database import build_engine, initialize_database
from app.observability import resolve_correlation_id
from app.routes import router


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime_settings = settings if settings is not None else Settings()
        app.state.settings = runtime_settings
        engine = build_engine(runtime_settings.database_url)
        app.state.engine = engine
        try:
            initialize_database(engine)
            yield
        finally:
            engine.dispose()

    app = FastAPI(title=APP_TITLE, lifespan=lifespan)
    app.include_router(router)

    @app.middleware("http")
    async def correlation_id(request, call_next):
        correlation_id = resolve_correlation_id(request.headers.get(CORRELATION_ID_HEADER))
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    settings = Settings()
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.port)
