from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    resend_api_key: str = ""
    email_to: str = ""
    langsmith_api_key: str = ""

    model: str = "claude-sonnet-5-5"
    max_steps: int = 40  # recursion_limit de LangGraph; el planning también gasta pasos
    # "*" permite cualquier dominio (el envío del formulario siempre pide aprobación)
    allowed_domains: list[str] = ["www.selenium.dev", "localhost", "127.0.0.1"]
    dry_run: bool = False  # llena pero no envía
    action_timeout_ms: int = 10_000
    artifacts_dir: str = "artifacts"
    email_from: str = "onboarding@resend.dev"
    # USD por millón de tokens (estimación; ajustar al precio vigente del modelo)
    price_in_per_mtok: float = 3.0
    price_out_per_mtok: float = 15.0
