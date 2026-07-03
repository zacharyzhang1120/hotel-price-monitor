"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401 - import models before init_db
from app.database import init_db
from app.routers import backups, hotels, prices, reports, scheduler, scrape
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.startup_cleanup import mark_stale_running_scrape_runs


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await mark_stale_running_scrape_runs()
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(title="Hotel Price Monitor", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(hotels.router, prefix="/api/v1")
app.include_router(prices.router, prefix="/api/v1")
app.include_router(reports.router, prefix="/api/v1")
app.include_router(scrape.router, prefix="/api/v1")
app.include_router(backups.router, prefix="/api/v1")
app.include_router(scheduler.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return {
        "name": "Hotel Price Monitor",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
        "api_prefix": "/api/v1",
    }
