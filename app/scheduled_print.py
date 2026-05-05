import logging
import time as time_mod

from .config import load_config
from .print_job import PrintFailure, print_tasks
from .run_history import record
from .scheduler import get_engine

log = logging.getLogger(__name__)

# Backoff schedule between print attempts: 1min, 5min, 30min.
# Total max attempts = len(_RETRY_DELAYS_S) + 1 = 4.
_RETRY_DELAYS_S = [60, 300, 1800]


def run(body: str, rule: str = "") -> None:
    """Invoked by APScheduler when a schedule fires.

    Each attempt is logged to run_history. The function blocks the
    APScheduler worker thread for the duration of any retries — acceptable
    given the small number of schedules expected for this personal tool.
    """
    config = load_config()
    engine = get_engine()

    last_error: str | None = None
    total_attempts = len(_RETRY_DELAYS_S) + 1

    for attempt in range(1, total_attempts + 1):
        try:
            n = print_tasks(body, config)
            record(engine, rule=rule, body=body, status="printed", attempts=attempt)
            log.info("scheduled fire OK after %d attempt(s) (%d strips)", attempt, n)
            return
        except PrintFailure as e:
            last_error = str(e)
            log.warning("scheduled fire attempt %d failed: %s", attempt, e)
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            log.exception("scheduled fire attempt %d crashed", attempt)

        if attempt < total_attempts:
            delay = _RETRY_DELAYS_S[attempt - 1]
            record(
                engine, rule=rule, body=body, status="retrying",
                attempts=attempt, error=last_error,
            )
            time_mod.sleep(delay)

    record(
        engine, rule=rule, body=body, status="failed",
        attempts=total_attempts, error=last_error,
    )
    log.error("scheduled fire gave up after %d attempts: %s", total_attempts, last_error)
