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
    receipt_width_px: int = 384


def load_config() -> Config:
    return Config(
        printer_host=os.environ.get("PRINTER_HOST", "192.168.15.26"),
        printer_port=int(os.environ.get("PRINTER_PORT", "9100")),
        printer_timeout=int(os.environ.get("PRINTER_TIMEOUT", "10")),
        dry_run=os.environ.get("DRY_RUN", "0") in ("1", "true", "True"),
        image_fetch_timeout=int(os.environ.get("IMAGE_FETCH_TIMEOUT", "5")),
        image_max_bytes=int(os.environ.get("IMAGE_MAX_BYTES", str(5 * 1024 * 1024))),
    )
