import atexit
import logging
import os
import threading
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from .config import Config

log = logging.getLogger(__name__)

_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_DAY_CRON_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_MONTH_NAMES = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

_scheduler: BackgroundScheduler | None = None
_engine: Engine | None = None
_tz: ZoneInfo | None = None


class ScheduleError(ValueError):
    pass


def init_scheduler(config: Config) -> BackgroundScheduler:
    global _scheduler, _engine, _tz
    if _scheduler is not None:
        return _scheduler

    db_path = config.scheduler_db_path
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    _engine = create_engine(f"sqlite:///{db_path}", future=True)
    _tz = ZoneInfo(config.scheduler_tz)

    _scheduler = BackgroundScheduler(
        jobstores={
            "default": SQLAlchemyJobStore(engine=_engine),
            "heartbeat": MemoryJobStore(),
        },
        timezone=_tz,
        job_defaults={
            "coalesce": True,
            "misfire_grace_time": config.misfire_grace_hours * 3600,
            "max_instances": 1,
        },
    )
    _scheduler.start()
    # Heartbeat: caps the scheduler's longest sleep at ~60s. Without this,
    # APScheduler can be mid-sleep when the OS suspends, and on resume the
    # sleep continues counting down from where it was (instead of noticing
    # wall-clock time has jumped). The heartbeat forces a wakeup ~every
    # minute, so missed fires get caught up shortly after a suspend.
    _scheduler.add_job(
        _heartbeat,
        trigger=IntervalTrigger(seconds=60),
        id="_heartbeat",
        jobstore="heartbeat",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    atexit.register(_shutdown)
    log.info(
        "scheduler started (tz=%s, db=%s, grace=%dh, heartbeat=60s)",
        config.scheduler_tz, db_path, config.misfire_grace_hours,
    )
    return _scheduler


def _heartbeat() -> None:
    pass


def _shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            log.exception("scheduler shutdown failed")
        _scheduler = None


def get_scheduler() -> BackgroundScheduler:
    if _scheduler is None:
        raise RuntimeError("scheduler not initialized")
    return _scheduler


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("scheduler not initialized")
    return _engine


def get_tz() -> ZoneInfo:
    if _tz is None:
        raise RuntimeError("scheduler not initialized")
    return _tz


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def build_trigger_and_rule(
    *,
    repeat: str,
    schedule_date: date,
    schedule_time: time,
    weekly_days: list[int] | None = None,
):
    tz = get_tz()
    hh = schedule_time.hour
    mm = schedule_time.minute
    hhmm = f"{hh:02d}:{mm:02d}"

    if repeat == "never":
        run_at = datetime.combine(schedule_date, schedule_time, tzinfo=tz)
        if run_at <= datetime.now(tz):
            raise ScheduleError("Date/time must be in the future")
        return DateTrigger(run_date=run_at, timezone=tz), f"Once on {schedule_date.isoformat()} at {hhmm}"

    if repeat == "daily":
        return CronTrigger(hour=hh, minute=mm, timezone=tz), f"Every day at {hhmm}"

    if repeat == "weekly":
        if not weekly_days:
            raise ScheduleError("Pick at least one weekday for Weekly")
        days_sorted = sorted({int(d) for d in weekly_days})
        for d in days_sorted:
            if d < 0 or d > 6:
                raise ScheduleError("Invalid weekday")
        cron_days = ",".join(_DAY_CRON_KEYS[d] for d in days_sorted)
        if len(days_sorted) == 7:
            rule = f"Every day at {hhmm}"
        else:
            rule = f"Weekly on {', '.join(_DAY_NAMES[d] for d in days_sorted)} at {hhmm}"
        return CronTrigger(day_of_week=cron_days, hour=hh, minute=mm, timezone=tz), rule

    if repeat == "monthly":
        d = schedule_date.day
        return CronTrigger(day=d, hour=hh, minute=mm, timezone=tz), f"Every month on the {_ordinal(d)} at {hhmm}"

    if repeat == "yearly":
        d = schedule_date.day
        m = schedule_date.month
        return (
            CronTrigger(month=m, day=d, hour=hh, minute=mm, timezone=tz),
            f"Every year on {_MONTH_NAMES[m - 1]} {d} at {hhmm}",
        )

    raise ScheduleError(f"Unknown repeat option: {repeat}")


def add_schedule(
    *,
    body: str,
    repeat: str,
    schedule_date: date,
    schedule_time: time,
    weekly_days: list[int] | None = None,
):
    trigger, rule = build_trigger_and_rule(
        repeat=repeat,
        schedule_date=schedule_date,
        schedule_time=schedule_time,
        weekly_days=weekly_days,
    )
    sched = get_scheduler()
    job = sched.add_job(
        "app.scheduled_print:run",
        trigger=trigger,
        kwargs={"body": body, "rule": rule},
    )
    log.info("scheduled job %s: %s", job.id, rule)
    return job


def list_schedules():
    sched = get_scheduler()
    jobs = sched.get_jobs()
    far_future = datetime.max.replace(tzinfo=get_tz())
    return sorted(jobs, key=lambda j: j.next_run_time or far_future)


def get_schedule(job_id: str):
    return get_scheduler().get_job(job_id)


def delete_schedule(job_id: str) -> bool:
    sched = get_scheduler()
    if not sched.get_job(job_id):
        return False
    sched.remove_job(job_id)
    return True


def fire_now(job_id: str) -> bool:
    """Run a scheduled job immediately, in a background thread, without
    disturbing its normal schedule. One-shot DateTrigger schedules remain
    queued for their original time.
    """
    sched = get_scheduler()
    job = sched.get_job(job_id)
    if not job:
        return False
    body = job.kwargs.get("body", "")
    rule = job.kwargs.get("rule", "")
    from .scheduled_print import run as run_job
    threading.Thread(
        target=run_job,
        kwargs={"body": body, "rule": rule},
        daemon=True,
    ).start()
    return True
