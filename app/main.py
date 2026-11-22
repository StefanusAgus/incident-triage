"""FastAPI application lifecycle and local server entry point."""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.config import Settings
from app.constants import APP_TITLE
from app.db.database import build_engine, initialize_database


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime_settings = settings if settings is not None else Settings()
        engine = build_engine(runtime_settings.database_url)
        app.state.engine = engine
        try:
            initialize_database(engine)
            yield
        finally:
            engine.dispose()

    app = FastAPI(title=APP_TITLE, lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    settings = Settings()
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.port)
