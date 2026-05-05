import base64
import html
import io
import logging

import qrcode
from markdown_it import MarkdownIt

log = logging.getLogger(__name__)


def render_html(md: MarkdownIt, source: str) -> str:
    _install_qr_rule(md)
    return md.render(source)


def _install_qr_rule(md: MarkdownIt) -> None:
    if getattr(md, "_qr_installed", False):
        return
    default_fence = md.renderer.rules.get("fence")

    def fence_rule(tokens, idx, options, env):
        token = tokens[idx]
        info = (token.info or "").strip().lower()
        if info == "qr":
            return _render_qr(token.content.strip())
        if default_fence is not None:
            return default_fence(tokens, idx, options, env)
        escaped = html.escape(token.content)
        return f"<pre><code>{escaped}</code></pre>\n"

    md.renderer.rules["fence"] = fence_rule
    md._qr_installed = True


def _render_qr(payload: str) -> str:
    if not payload:
        return '<div class="qr qr-empty">[empty QR]</div>\n'
    try:
        img = qrcode.make(payload, box_size=4, border=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        preview = payload if len(payload) <= 80 else payload[:80] + "…"
        alt = html.escape(f"QR: {preview}", quote=True)
        return (
            f'<div class="qr">'
            f'<img src="data:image/png;base64,{b64}" alt="{alt}" />'
            f'</div>\n'
        )
    except Exception:
        log.exception("failed to render QR for preview")
        escaped = html.escape(payload)
        return f'<div class="qr qr-error">[QR error: {escaped}]</div>\n'
