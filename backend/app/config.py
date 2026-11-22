from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "sqlite:///./insightiq.db"
    openrouter_api_key: str | None = None
    llm_model: str | None = None
    llm_base_url: str = "https://openrouter.ai/api/v1"
    frontend_url: str = "http://localhost:3000"
    business_timezone: str = "Asia/Kolkata"
    default_currency: str = "INR"
    inactive_customer_days: int = 90
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
