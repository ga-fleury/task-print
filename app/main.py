import logging

from flask import Flask, jsonify, render_template, request

from .config import load_config
from .header import format_header
from .print_job import PrintFailure, print_tasks, print_test_strip
from .render import make_parser, render_html
from .splitter import split_tasks

log = logging.getLogger(__name__)


def create_app() -> Flask:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

    config = load_config()
    md = make_parser()

    @app.get("/")
    def index():
        return render_template("index.html", dry_run=config.dry_run)

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

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "dry_run": config.dry_run})

    return app
