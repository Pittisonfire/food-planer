from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.auth_routes import router as auth_router
from app.core.database import engine, Base
from app.models import models  # noqa: F401

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Food Planer API",
    description="Meal planning with Spoonacular + Claude AI",
    version="2.0.0"
)

# CORS - allow frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(auth_router, prefix="/api")
app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    return {"status": "ok", "app": "Food Planer", "version": "2.0.0"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
