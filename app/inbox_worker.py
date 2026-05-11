import base64
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
    return " - ".join(parts) if parts else None


def _fetch_attachment(config: Config, url_path: str) -> tuple[bytes, str] | None:
    """Fetch attachment bytes using the worker bearer. Returns (bytes, mime) or None."""
    try:
        resp = requests.get(
            f"{config.inbox_server_url}{url_path}",
            headers={"Authorization": f"Bearer {config.inbox_worker_token}"},
            timeout=config.image_fetch_timeout + 5,
            stream=True,
        )
        if resp.status_code != 200:
            log.warning("attachment fetch %s returned %d", url_path, resp.status_code)
            return None
        cl = resp.headers.get("content-length")
        if cl and int(cl) > config.image_max_bytes:
            log.warning("attachment too large: %s (%s bytes)", url_path, cl)
            return None
        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > config.image_max_bytes:
                log.warning("attachment too large (streamed): %s", url_path)
                return None
            chunks.append(chunk)
        mime = resp.headers.get("content-type", "image/png").split(";")[0].strip()
        return b"".join(chunks), mime
    except requests.RequestException as e:
        log.warning("attachment fetch failed for %s: %s", url_path, e)
        return None


def _compose_body(body: str, attachments: list[dict], config: Config) -> tuple[str, bool]:
    """Prepend each attachment as a data-URI markdown image. Returns (body, all_ok)."""
    if not attachments:
        return body, True
    parts: list[str] = []
    all_ok = True
    for att in attachments:
        url = att.get("url")
        if not url:
            all_ok = False
            continue
        fetched = _fetch_attachment(config, url)
        if fetched is None:
            all_ok = False
            continue
        raw, mime = fetched
        b64 = base64.b64encode(raw).decode("ascii")
        parts.append(f"![]({'data:'}{mime};base64,{b64})")
    if not parts:
        return body, False
    composed = "\n\n".join(parts)
    if body:
        composed = composed + "\n\n" + body
    return composed, all_ok


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
    body = msg.get("body", "") or ""
    label = msg.get("link_label") or None
    sender = msg.get("sender_name") or None
    attachments = msg.get("attachments") or []
    header_extra = _build_header_extra(label, sender)

    composed, images_ok = _compose_body(body, attachments, config)
    if attachments and not images_ok:
        if composed:
            composed = composed + "\n\n*[image unavailable]*"
        elif body.strip():
            composed = body + "\n\n*[image unavailable]*"
        else:
            err = "image unavailable and body is empty"
            log.warning("inbox msg %d: %s", msg_id, err)
            result = _post_ack(config, msg_id, "failed", err)
            if result and result.get("dead_letter"):
                inbox_history.record_dead_letter(
                    engine,
                    server_msg_id=msg_id,
                    link_label=label,
                    sender_name=sender,
                    body=body,
                    error=err,
                )
            return

    try:
        print_inbox_message(composed, header_extra, config)
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

    log.info(
        "inbox printed msg %d (label=%s, sender=%s, attachments=%d, images_ok=%s)",
        msg_id, label, sender, len(attachments), images_ok,
    )
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
