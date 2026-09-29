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

    # Comma-separated Pi agents: "Living|http://10.0.0.20:8190,Kitchen|http://10.0.0.21:8190"
    # Name is optional: "http://10.0.0.20:8190" is fine.
    multiroom_agents: str = ""

    def agent_urls(self) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for raw in self.multiroom_agents.split(","):
            piece = raw.strip()
            if not piece:
                continue
            if "|" in piece:
                name, url = piece.split("|", 1)
            else:
                name, url = "", piece
            out.append({"name": name.strip() or url.strip(), "url": url.strip()})
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
