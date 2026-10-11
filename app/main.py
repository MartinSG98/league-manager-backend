from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import init_db
from app.game.catalog import get_catalog
from app.routers import careers, catalog

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    get_catalog()  # rate every player once at startup rather than on the first request
    yield


app = FastAPI(title="League Manager API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(catalog.router)
app.include_router(careers.router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
