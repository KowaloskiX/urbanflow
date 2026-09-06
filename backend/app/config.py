import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = "UrbanFlow API"
    app_mode: str = "DEMO"
    frontend_origin: str = "http://localhost:5173"
    live_max_age_seconds: int = 30
    stale_max_age_seconds: int = 90
    realtime_enabled: bool = False
    seed_fixtures: bool = True
    realtime_poll_seconds: float = 5
    ztp_base_url: str = "https://gtfs.ztp.krakow.pl"


def get_settings() -> Settings:
    return Settings(
        app_mode=os.getenv("APP_MODE", "DEMO").upper(),
        frontend_origin=os.getenv("FRONTEND_ORIGIN", "http://localhost:5173"),
        realtime_enabled=os.getenv("REALTIME_ENABLED", "true").lower()
        in {"1", "true", "yes"},
        seed_fixtures=os.getenv("SEED_FIXTURES", "false").lower()
        in {"1", "true", "yes"},
        realtime_poll_seconds=float(os.getenv("REALTIME_POLL_SECONDS", "5")),
        ztp_base_url=os.getenv("ZTP_BASE_URL", "https://gtfs.ztp.krakow.pl"),
    )
