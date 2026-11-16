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

    # Agente de fletes
    hapag_base_url: str = ""  # sandbox/prod de api-portal.hlag.com, con la versión incluida
    hapag_client_id: str = ""
    hapag_client_secret: str = ""
    resend_webhook_secret: str = ""  # whsec_... del webhook email.received
    # Solo estos remitentes pueden disparar el agente (vacío = nadie). Formato en .env: ["a@b.com"]
    allowed_senders: list[str] = []
    state_db: str = "artifacts/freight_state.sqlite"  # checkpoints del agente + correos ya procesados
    mock_db_path: str = "artifacts/mock_freight.sqlite"  # salidas simuladas de hoy a +6 meses (se regenera a diario)
    history_db_path: str = "artifacts/mock_history.sqlite"  # envíos simulados de los últimos 36 meses
    report_dir: str = "artifacts/reports"  # PDFs del informe mensual
