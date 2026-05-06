import logging
from datetime import date, time

from flask import Flask, jsonify, render_template, request

from . import inbox_history, scheduler as sched_mod
from .config import load_config
from .header import format_header
from .inbox_worker import start_worker as start_inbox_worker
from .print_job import PrintFailure, print_tasks, print_test_strip
from .render import make_parser, render_html
from .run_history import init_history, list_recent
from .splitter import split_tasks

log = logging.getLogger(__name__)


def create_app() -> Flask:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )

    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

    config = load_config()
    md = make_parser()

    sched_mod.init_scheduler(config)
    init_history(sched_mod.get_engine())
    start_inbox_worker(config, sched_mod.get_engine())

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            dry_run=config.dry_run,
            default_schedule_time=config.default_schedule_time,
        )

    @app.post("/render")
    def render():
        text = request.form.get("text", "")
        chunks = split_tasks(text)
        if not chunks:
            return render_template("_preview.html", strips=[], total=0)
        ts = format_header()
        strips = [
            {"index": i + 1, "timestamp": ts, "html": render_html(md, body)}
            for i, body in enumerate(chunks)
        ]
        return render_template("_preview.html", strips=strips, total=len(strips))

    @app.post("/print")
    def do_print():
        text = request.form.get("text", "") if request.form else (request.json or {}).get("text", "")
        try:
            n = print_tasks(text, config)
        except PrintFailure as e:
            log.warning("print failed: %s", e)
            return jsonify({"ok": False, "error": str(e), "failed_at": e.failed_at, "total": e.total}), 502
        except Exception as e:
            log.exception("unexpected print error")
            return jsonify({"ok": False, "error": str(e)}), 500
        return jsonify({"ok": True, "printed": n})

    @app.post("/test")
    def do_test():
        try:
            print_test_strip(config)
        except Exception as e:
            log.exception("test print failed")
            return jsonify({"ok": False, "error": str(e)}), 502
        return jsonify({"ok": True})

    @app.post("/schedule")
    def create_schedule():
        text = request.form.get("text", "")
        strips = split_tasks(text)
        if not strips:
            return jsonify({"ok": False, "error": "Body is empty"}), 400

        repeat = request.form.get("repeat", "never")
        date_str = request.form.get("date", "")
        time_str = request.form.get("time", "")
        weekly_days_raw = request.form.getlist("weekly_days")

        try:
            sched_date = date.fromisoformat(date_str)
            sched_time = time.fromisoformat(time_str)
            weekly_days = [int(d) for d in weekly_days_raw] if weekly_days_raw else None
        except ValueError as e:
            return jsonify({"ok": False, "error": f"Invalid date/time: {e}"}), 400

        job_ids = []
        rule = ""
        try:
            for strip_body in strips:
                job = sched_mod.add_schedule(
                    body=strip_body,
                    repeat=repeat,
                    schedule_date=sched_date,
                    schedule_time=sched_time,
                    weekly_days=weekly_days,
                )
                job_ids.append(job.id)
                rule = job.kwargs.get("rule", "")
        except sched_mod.ScheduleError as e:
            for jid in job_ids:
                sched_mod.delete_schedule(jid)
            return jsonify({"ok": False, "error": str(e)}), 400
        except Exception as e:
            log.exception("schedule creation failed")
            for jid in job_ids:
                sched_mod.delete_schedule(jid)
            return jsonify({"ok": False, "error": str(e)}), 500

        return jsonify({
            "ok": True,
            "count": len(job_ids),
            "job_ids": job_ids,
            "rule": rule,
        })

    @app.get("/schedules")
    def schedules_page():
        jobs = sched_mod.list_schedules()
        rows = []
        for j in jobs:
            body = j.kwargs.get("body", "")
            preview_line = next((l for l in body.splitlines() if l.strip()), "").strip()
            if len(preview_line) > 80:
                preview_line = preview_line[:77] + "..."
            next_run = j.next_run_time.strftime("%a %b %d, %H:%M") if j.next_run_time else "—"
            rows.append({
                "id": j.id,
                "preview": preview_line,
                "body": body,
                "rule": j.kwargs.get("rule", ""),
                "next_run": next_run,
            })
        history = list_recent(sched_mod.get_engine(), 20)
        return render_template(
            "schedules.html",
            schedules=rows,
            history=history,
            dry_run=config.dry_run,
        )

    @app.post("/schedules/<job_id>/delete")
    def delete_schedule(job_id):
        if not sched_mod.delete_schedule(job_id):
            return jsonify({"ok": False, "error": "Not found"}), 404
        return jsonify({"ok": True})

    @app.post("/schedules/<job_id>/fire")
    def fire_schedule(job_id):
        if not sched_mod.fire_now(job_id):
            return jsonify({"ok": False, "error": "Not found"}), 404
        return jsonify({"ok": True})

    @app.get("/inbox/failed")
    def inbox_failed_page():
        rows = inbox_history.list_recent(sched_mod.get_engine(), 20)
        return render_template(
            "inbox_failed.html",
            rows=rows,
            dry_run=config.dry_run,
        )

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "dry_run": config.dry_run, "inbox": config.inbox_enabled})

    return app
