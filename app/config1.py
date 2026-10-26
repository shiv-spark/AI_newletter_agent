
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI Newsletter Agent"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_database: str = "ai_newsletter_db"
    postgres_user: str = "postgres"
    postgres_password: str
    openrouter_api_key: str = ""
    openrouter_model: str = "nvidia/nemotron-3.5-super-vl:free"
    resend_api_key: str = ""
    resend_from_email: str = ""
    scheduler_enabled: bool = False
    scheduler_send_enabled: bool = False
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        from sqlalchemy.engine import URL

        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_database,
        ).render_as_string(hide_password=False)


settings = Settings()

# from pydantic_settings import BaseSettings, SettingsConfigDict


# class Settings(BaseSettings):
#     app_name: str = "AI Newsletter Agent"

#     postgres_host: str = "localhost"
#     postgres_port: int = 5432
#     postgres_database: str = "ai_newsletter_db"
#     postgres_user: str = "postgres"
#     postgres_password: str

#     model_config = SettingsConfigDict(
#         env_file=".env",
#         env_file_encoding="utf-8",
#         extra="ignore",
#     )

#     @property
#     def database_url(self) -> str:
#         from sqlalchemy.engine import URL

#         return URL.create(
#             drivername="postgresql+psycopg",
#             username=self.postgres_user,
#             password=self.postgres_password,
#             host=self.postgres_host,
#             port=self.postgres_port,
#             database=self.postgres_database,
#         ).render_as_string(hide_password=False)


# settings = Settings()
