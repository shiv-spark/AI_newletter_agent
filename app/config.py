
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
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"
    base_url: str = "http://localhost:8000"

    # Web API. When API_KEY is set, every /api request must send it in the
    # X-API-Key header (or the api_key query parameter). Empty = open API,
    # which is fine on your own computer but not on a public server.
    api_key: str = ""

    # Look of the HTML newsletter: "forest" (dark green) or "light".
    newsletter_theme: str = "forest"

    # Name shown as sender, in the subject and in the email header/footer.
    newsletter_brand: str = "Sparkbrains"
    # The Writer's title must be short; longer ones are repaired or cut.
    newsletter_title_max_chars: int = 55

    # Editorial pipeline (Curator -> Analyst -> Writer -> Editor).
    # Empty editor model means "use openrouter_model".
    openrouter_editor_model: str = ""
    max_correction_attempts: int = 2
    curator_min_stories: int = 3
    curator_max_stories: int = 5
    curator_candidate_limit: int = 20
    # Comma-separated publisher names, for example "Reuters,BBC News".
    trusted_sources: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def trusted_sources_list(self) -> list[str]:
        return [
            name.strip()
            for name in self.trusted_sources.split(",")
            if name.strip()
        ]

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
