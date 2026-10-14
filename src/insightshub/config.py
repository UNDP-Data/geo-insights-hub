from typing import Any
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    storage_secret: SecretStr
    app_name: str
    header_label: str
    public_auth_url: str
    private_auth_url: str
    nb_github_token: str
    nb_github_repo: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="before")
    @classmethod
    def strip_quotes(cls, data: Any) -> Any:
        """Strips surrounding quotes on all string config entries."""
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, str):
                    val = v.strip()
                    if (val.startswith('"') and val.endswith('"')) or (
                        val.startswith("'") and val.endswith("'")
                    ):
                        data[k] = val[1:-1]
        return data


settings = Settings()