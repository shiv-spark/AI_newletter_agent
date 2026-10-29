from contextlib import asynccontextmanager
import logging

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api import issues, subscriptions, users

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     logger.info("Starting AI Newsletter Agent...")
#     start_scheduler()

#     try:
#         yield
#     finally:
#         stop_scheduler()
#         logger.info("AI Newsletter Agent stopped.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # No more start_scheduler() needed here!
    yield



app = FastAPI(
    title="AI Newsletter Agent",
    description="Personalized news collection and newsletter automation",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(users.router)
app.include_router(issues.router)
app.include_router(subscriptions.router)


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "AI Newsletter Agent",
    }


@app.get("/", include_in_schema=False)
def dashboard():
    """Small web dashboard (manage topics, generate and read issues)."""
    return FileResponse(Path(__file__).parent / "static" / "index.html")
