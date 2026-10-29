"""Run the whole test suite against a separate PostgreSQL database.

The tests create and delete users, articles and issues. They must never
share a database with the real articles collected by the research pipeline,
otherwise those real articles leak into the tests.

This file is loaded by pytest before any test module, so the environment
variable below is set before app.config reads its settings. Environment
variables take priority over the .env file. Only the database name is
changed; host, user and password still come from .env.

Override the name with TEST_POSTGRES_DATABASE if you want a different one.
"""
import os

TEST_DATABASE = os.environ.get("TEST_POSTGRES_DATABASE", "ai_newsletter_test_db")

os.environ["POSTGRES_DATABASE"] = TEST_DATABASE

import psycopg  # noqa: E402
import pytest  # noqa: E402
from psycopg import sql  # noqa: E402

from app.config import settings  # noqa: E402
from app.celery_app import celery_app  # noqa: E402

celery_app.conf.update(
    task_always_eager=True,
    task_eager_propagates=True,
    task_store_eager_result=True,
    result_backend="cache+memory://",
)


def _create_database_if_missing() -> None:
    """Create the test database by connecting to the default 'postgres' one."""
    with psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        dbname="postgres",
        autocommit=True,
    ) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DATABASE,)
        ).fetchone()

        if not exists:
            connection.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TEST_DATABASE))
            )


@pytest.fixture(scope="session", autouse=True)
def test_database():
    """Make sure the test database exists and has all tables."""
    # Safety check: never touch a database that is not clearly a test one.
    assert settings.postgres_database == TEST_DATABASE, (
        "Tests must run on the test database, "
        f"but settings point to {settings.postgres_database!r}."
    )
    assert "test" in TEST_DATABASE.lower(), (
        f"Refusing to run tests on {TEST_DATABASE!r}: the name must contain 'test'."
    )

    _create_database_if_missing()

    from app.database.db import initialize_database

    initialize_database()

    yield