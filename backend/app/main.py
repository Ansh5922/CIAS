from fastapi import FastAPI
from sqlalchemy import text

from contextlib import asynccontextmanager
from app.core.database import engine
from app.core.config import settings
from app.api.routes import auth, upload, preprocessing

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create upload directories on startup
    import os
    base_dir = settings.UPLOAD_DIR
    sub_dirs = ["pdf", "images", "csv", "excel", "temp"]
    for sub in sub_dirs:
        os.makedirs(os.path.join(base_dir, sub), exist_ok=True)
    yield

app = FastAPI(
    title="CIAS API",
    version="1.0.0",
    description="Backend API for Crime Intelligence & Analysis System",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Auth", "description": "Authentication operations"},
        {"name": "Upload", "description": "File upload operations"},
        {"name": "Preprocessing", "description": "Document parsing and ingestion pipeline"}
    ]
)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(upload.router, prefix="/upload", tags=["Upload"])
app.include_router(preprocessing.router, prefix="/preprocessing", tags=["Preprocessing"])


@app.get("/")
def root():
    return {"message": "CIAS Backend Running"}


@app.get("/health")
def health():
    return {"status": "healthy"}