from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    navidrome_url: str = "http://127.0.0.1:4533"
    navidrome_user: str = ""
    navidrome_password: str = ""

    snapcast_host: str = "127.0.0.1"
    snapcast_control_port: int = 1705
    snapcast_tcp_port: int = 4953

    hub_host: str = "0.0.0.0"
    hub_port: int = 8080
    data_dir: str = "./data"


@lru_cache
def get_settings() -> Settings:
    return Settings()
