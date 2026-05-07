import logging

from .config import Config
from .header import format_header
from .printer import apply_density, open_printer, print_lock
from .render import make_parser, render_escpos
from .splitter import split_tasks

log = logging.getLogger(__name__)


class PrintFailure(Exception):
    def __init__(self, failed_at: int, total: int, reason: str):
        super().__init__(f"strip {failed_at}/{total} failed: {reason}")
        self.failed_at = failed_at
        self.total = total
        self.reason = reason


def print_tasks(text: str, config: Config) -> int:
    tasks = split_tasks(text)
    if not tasks:
        return 0
    md = make_parser()

    with print_lock(), open_printer(config) as p:
        try:
            p.hw("init")
        except Exception:
            log.warning("printer init failed; continuing")
        apply_density(p, config)

        for idx, body in enumerate(tasks, start=1):
            try:
                _print_strip(p, md, body, config)
            except Exception as e:
                log.exception("strip %d/%d failed", idx, len(tasks))
                raise PrintFailure(idx, len(tasks), str(e)) from e
    return len(tasks)


def print_test_strip(config: Config) -> None:
    md = make_parser()
    sample = (
        "# Hello, printer!\n\n"
        "- [ ] check the **bold**\n"
        "- [x] check task list\n"
        "- normal bullet\n\n"
        "```qr\n"
        "https://example.com\n"
        "```\n"
    )
    with print_lock(), open_printer(config) as p:
        try:
            p.hw("init")
        except Exception:
            log.warning("printer init failed; continuing")
        apply_density(p, config)
        _print_strip(p, md, sample, config)


def print_inbox_message(body: str, header_extra: str | None, config: Config) -> None:
    md = make_parser()
    with print_lock(), open_printer(config) as p:
        try:
            p.hw("init")
        except Exception:
            log.warning("printer init failed; continuing")
        apply_density(p, config)
        _print_strip(p, md, body, config, header_extra=header_extra)


def _print_strip(printer, md, body: str, config: Config, header_extra: str | None = None) -> None:
    header = format_header()
    try:
        printer.set(font="b", align="left", bold=False)
    except Exception:
        printer.set(align="left", bold=False)
    printer.text(header + "\n")
    if header_extra:
        printer.text(header_extra + "\n")
    printer.set()

    tokens = md.parse(body)
    render_escpos(printer, config, tokens)

    printer.set()
    printer.text("\n\n\n")
    try:
        printer.cut(mode="PART")
    except Exception:
        log.warning("partial cut failed; trying full cut")
        try:
            printer.cut(mode="FULL")
        except Exception:
            log.warning("cut failed entirely")
