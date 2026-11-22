"""Minimal FastAPI application and local server entry point."""

import uvicorn
from fastapi import FastAPI

from app.config import Settings
from app.constants import APP_TITLE

app = FastAPI(title=APP_TITLE)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    settings = Settings()
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.port)
