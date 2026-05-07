import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    printer_host: str
    printer_port: int
    printer_timeout: int
    dry_run: bool
    image_fetch_timeout: int
    image_max_bytes: int
    printer_density: int | None = None
    receipt_width_px: int = 384
    default_schedule_time: str = "09:00"
    scheduler_tz: str = "America/Sao_Paulo"
    misfire_grace_hours: int = 24
    scheduler_db_path: str = "data/schedules.sqlite"
    inbox_enabled: bool = False
    inbox_server_url: str = ""
    inbox_worker_token: str = ""
    inbox_long_poll_timeout: int = 25


def load_config() -> Config:
    density_raw = os.environ.get("PRINTER_DENSITY", "").strip()
    printer_density = int(density_raw) if density_raw else None
    if printer_density is not None:
        printer_density = max(0, min(8, printer_density))

    return Config(
        printer_host=os.environ.get("PRINTER_HOST", "192.168.15.26"),
        printer_port=int(os.environ.get("PRINTER_PORT", "9100")),
        printer_timeout=int(os.environ.get("PRINTER_TIMEOUT", "10")),
        dry_run=os.environ.get("DRY_RUN", "0") in ("1", "true", "True"),
        image_fetch_timeout=int(os.environ.get("IMAGE_FETCH_TIMEOUT", "5")),
        image_max_bytes=int(os.environ.get("IMAGE_MAX_BYTES", str(5 * 1024 * 1024))),
        printer_density=printer_density,
        default_schedule_time=os.environ.get("DEFAULT_SCHEDULE_TIME", "09:00"),
        scheduler_tz=os.environ.get("SCHEDULER_TZ", os.environ.get("TZ", "America/Sao_Paulo")),
        misfire_grace_hours=int(os.environ.get("MISFIRE_GRACE_HOURS", "24")),
        scheduler_db_path=os.environ.get("SCHEDULER_DB_PATH", "data/schedules.sqlite"),
        inbox_enabled=os.environ.get("INBOX_ENABLED", "0") in ("1", "true", "True"),
        inbox_server_url=os.environ.get("INBOX_SERVER_URL", "").rstrip("/"),
        inbox_worker_token=os.environ.get("INBOX_WORKER_TOKEN", ""),
        inbox_long_poll_timeout=int(os.environ.get("INBOX_LONG_POLL_TIMEOUT", "25")),
    )
