
# from app.database.db import test_connection
# def test_postgres_connection():
#     assert test_connection() == "PostgreSQL connection successful"


from app.database.db import test_connection as check_database_connection


def test_postgres_connection():
    assert (
        check_database_connection()
        == "PostgreSQL connection successful"
    )




