from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    resend_api_key: str = ""
    email_to: str = ""
    langsmith_api_key: str = ""

    model: str = "claude-sonnet-5-5"
    max_steps: int = 40  # recursion_limit de LangGraph; el planning también gasta pasos
    allowed_domains: list[str] = ["www.selenium.dev", "localhost", "127.0.0.1"]
    action_timeout_ms: int = 10_000
    artifacts_dir: str = "artifacts"
