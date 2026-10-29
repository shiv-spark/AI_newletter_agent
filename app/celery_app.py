from celery import Celery
from app.config import settings

celery_app = Celery(
    "ai_newsletter",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.services.scheduler_service", "app.api.issues"],
)

celery_app.conf.update(
    timezone="Asia/Kolkata",
    enable_utc=True,
    # Celery Beat: runs the due-user check every 1 minute
    beat_schedule={
        "check-due-newsletters-every-minute": {
            "task": "app.services.scheduler_service.scheduled_newsletter_run",
            "schedule": 60.0,
        },
    },
)
