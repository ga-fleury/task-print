import logging
import threading
from contextlib import contextmanager
from typing import Iterator

from escpos.printer import Dummy, Network

from .config import Config

log = logging.getLogger(__name__)

_print_lock = threading.Lock()


class PrinterError(Exception):
    pass


@contextmanager
def open_printer(config: Config) -> Iterator[Network | Dummy]:
    if config.dry_run:
        p = Dummy(profile="TM-T88III")
        try:
            yield p
        finally:
            log.info("DRY_RUN print: %d bytes", len(p.output))
        return

    try:
        p = Network(
            host=config.printer_host,
            port=config.printer_port,
            timeout=config.printer_timeout,
            profile="TM-T88III",
        )
    except Exception as e:
        raise PrinterError(f"could not connect to printer: {e}") from e

    try:
        yield p
    finally:
        try:
            p.close()
        except Exception:
            pass


@contextmanager
def print_lock() -> Iterator[None]:
    acquired = _print_lock.acquire(timeout=60)
    if not acquired:
        raise PrinterError("another print job is in progress")
    try:
        yield
    finally:
        _print_lock.release()


def apply_density(p, config: Config) -> None:
    if config.printer_density is None:
        return
    n = max(0, min(8, config.printer_density))
    try:
        p._raw(b"\x1d|" + bytes([n]))
    except Exception:
        log.warning("set density failed; continuing")
