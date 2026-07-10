from fastapi import FastAPI
from sqlalchemy import text

from app.core.database import engine
from app.api.routes import auth

app = FastAPI(
    title="CIAS API",
    version="1.0.0",
    description="Backend API for Crime Intelligence & Analysis System",
    openapi_tags=[
        {"name": "Auth", "description": "Authentication operations"}
    ]
)

app.include_router(auth.router, prefix="/auth", tags=["Auth"])


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