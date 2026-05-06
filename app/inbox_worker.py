import logging
import threading
from typing import Callable

import requests

from . import inbox_history
from .config import Config
from .print_job import print_inbox_message

log = logging.getLogger(__name__)

_MAX_BACKOFF = 30.0


def _build_header_extra(label: str | None, sender: str | None) -> str | None:
    parts: list[str] = []
    if label:
        parts.append(f"from {label}")
    if sender:
        parts.append(sender)
    return " · ".join(parts) if parts else None


def _post_ack(config: Config, msg_id: int, status: str, error: str | None) -> dict | None:
    try:
        resp = requests.post(
            f"{config.inbox_server_url}/messages/{msg_id}/ack",
            headers={"Authorization": f"Bearer {config.inbox_worker_token}"},
            json={"status": status, "error": error},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        log.warning("ack for msg %d returned %d: %s", msg_id, resp.status_code, resp.text[:200])
    except requests.RequestException as e:
        log.warning("ack request failed for msg %d: %s", msg_id, e)
    return None


def _handle_message(msg: dict, config: Config, engine) -> None:
    msg_id = msg["id"]
    body = msg.get("body", "")
    label = msg.get("link_label") or None
    sender = msg.get("sender_name") or None
    header_extra = _build_header_extra(label, sender)

    try:
        print_inbox_message(body, header_extra, config)
    except Exception as e:
        log.exception("inbox print failed for msg %d", msg_id)
        result = _post_ack(config, msg_id, "failed", str(e))
        if result and result.get("dead_letter"):
            inbox_history.record_dead_letter(
                engine,
                server_msg_id=msg_id,
                link_label=label,
                sender_name=sender,
                body=body,
                error=str(e),
            )
        return

    log.info("inbox printed msg %d (label=%s, sender=%s)", msg_id, label, sender)
    _post_ack(config, msg_id, "printed", None)


def start_worker(config: Config, engine) -> Callable[[], None]:
    if not config.inbox_enabled:
        log.info("inbox worker disabled (INBOX_ENABLED=0)")
        return lambda: None
    if not config.inbox_server_url or not config.inbox_worker_token:
        log.warning("inbox worker enabled but URL/token not configured; skipping")
        return lambda: None

    inbox_history.init_inbox_history(engine)
    stop = threading.Event()

    def loop() -> None:
        backoff = 1.0
        while not stop.is_set():
            try:
                resp = requests.get(
                    f"{config.inbox_server_url}/pending",
                    headers={"Authorization": f"Bearer {config.inbox_worker_token}"},
                    timeout=config.inbox_long_poll_timeout + 10,
                )
            except requests.RequestException as e:
                log.warning("inbox /pending request failed: %s", e)
                if stop.wait(timeout=backoff):
                    break
                backoff = min(backoff * 2, _MAX_BACKOFF)
                continue

            if resp.status_code != 200:
                log.warning("inbox /pending returned %d: %s", resp.status_code, resp.text[:200])
                if stop.wait(timeout=backoff):
                    break
                backoff = min(backoff * 2, _MAX_BACKOFF)
                continue

            backoff = 1.0
            try:
                data = resp.json()
            except ValueError:
                log.warning("inbox /pending returned non-JSON")
                if stop.wait(timeout=2.0):
                    break
                continue

            messages = data.get("messages", []) or []
            for msg in messages:
                if stop.is_set():
                    break
                try:
                    _handle_message(msg, config, engine)
                except Exception:
                    log.exception("inbox worker: unexpected error handling msg")

    t = threading.Thread(target=loop, name="inbox-worker", daemon=True)
    t.start()
    log.info("inbox worker started (server=%s)", config.inbox_server_url)

    def shutdown() -> None:
        stop.set()

    return shutdown
