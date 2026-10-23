
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database.models import Base

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


def test_connection() -> str:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    return "PostgreSQL connection successful"




def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)

