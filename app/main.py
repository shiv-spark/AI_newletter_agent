from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from app.services.scheduler_service import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AI Newsletter Agent...")
    start_scheduler()

    try:
        yield
    finally:
        stop_scheduler()
        logger.info("AI Newsletter Agent stopped.")


app = FastAPI(
    title="AI Newsletter Agent",
    description="Personalized news collection and newsletter automation",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "AI Newsletter Agent",
    }
