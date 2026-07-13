from fastapi import FastAPI
from sqlalchemy import text

from contextlib import asynccontextmanager
from app.core.database import engine
from app.core.config import settings
from app.api.routes import auth, upload

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
        {"name": "Upload", "description": "File upload operations"}
    ]
)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(upload.router, prefix="/upload", tags=["Upload"])


@app.get("/")
def root():
    return {"message": "CIAS Backend Running"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/db-test")
def db_test():
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT current_database();"))
            db_name = result.scalar()

        return {
            "status": "connected",
            "database": db_name
        }

    except Exception as e:
        return {
            "status": "failed",
            "error": str(e)
        }