import logging
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Column, DateTime, Integer, MetaData, String, Table, Text, desc, insert, select,
)
from sqlalchemy.engine import Engine

log = logging.getLogger(__name__)

_metadata = MetaData()

run_history = Table(
    "run_history",
    _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime(timezone=False), nullable=False),
    Column("rule", Text, nullable=False),
    Column("body_preview", Text, nullable=False),
    Column("status", String(16), nullable=False),  # 'printed' | 'retrying' | 'failed'
    Column("attempts", Integer, nullable=False),
    Column("error", Text, nullable=True),
)


def init_history(engine: Engine) -> None:
    _metadata.create_all(engine)


def _preview(body: str) -> str:
    line = next((l for l in body.splitlines() if l.strip()), "")
    line = line.strip()
    if len(line) > 120:
        line = line[:117] + "..."
    return line


def record(
    engine: Engine,
    *,
    rule: str,
    body: str,
    status: str,
    attempts: int = 1,
    error: str | None = None,
) -> None:
    try:
        with engine.begin() as conn:
            conn.execute(insert(run_history).values(
                ts=datetime.now(),
                rule=rule,
                body_preview=_preview(body),
                status=status,
                attempts=attempts,
                error=error,
            ))
    except Exception:
        log.exception("failed to record run history")


def list_recent(engine: Engine, limit: int = 20) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(run_history).order_by(desc(run_history.c.id)).limit(limit)
        ).mappings().all()
    return [dict(r) for r in rows]
