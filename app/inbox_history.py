import logging
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Column, DateTime, Integer, MetaData, String, Table, Text, desc, insert, select,
)
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

_metadata = MetaData()

inbox_failed = Table(
    "inbox_failed",
    _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=False), nullable=False),
    Column("server_msg_id", Integer, nullable=False),
    Column("link_label", String(160), nullable=True),
    Column("sender_name", String(120), nullable=True),
    Column("body_preview", Text, nullable=False),
    Column("error", Text, nullable=True),
)


def init_inbox_history(engine: Engine) -> None:
    _metadata.create_all(engine)


def _preview(body: str) -> str:
    line = next((l for l in body.splitlines() if l.strip()), "")
    line = line.strip()
    if len(line) > 160:
        line = line[:157] + "..."
    return line


def record_dead_letter(
    engine: Engine,
    *,
    server_msg_id: int,
    link_label: str | None,
    sender_name: str | None,
    body: str,
    error: str | None,
) -> None:
    try:
        with engine.begin() as conn:
            conn.execute(insert(inbox_failed).values(
                ts=datetime.now(),
                server_msg_id=server_msg_id,
                link_label=link_label,
                sender_name=sender_name,
                body_preview=_preview(body),
                error=error,
            ))
    except Exception:
        log.exception("failed to record inbox dead-letter")


def list_recent(engine: Engine, limit: int = 20) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(inbox_failed).order_by(desc(inbox_failed.c.id)).limit(limit)
        ).mappings().all()
    return [dict(r) for r in rows]
