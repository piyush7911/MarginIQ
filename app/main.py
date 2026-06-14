from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import BASE_DIR
from app.db.sqlite import initialize_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="MarginIQ",
    version="0.2.0",
    description="Adaptive multi-agent promotion intelligence backend.",
    lifespan=lifespan,
)


app.include_router(router, prefix="/api/v1")
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")


@app.get("/", include_in_schema=False)
async def frontend() -> FileResponse:
    # No-cache so the page (and its versioned asset links) is always fresh.
    return FileResponse(
        BASE_DIR / "app" / "static" / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/health")
async def healthcheck() -> dict:
    return {"status": "ok"}
