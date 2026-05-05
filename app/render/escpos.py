import logging
import re
from dataclasses import dataclass

from markdown_it.token import Token

from ..config import Config
from .images import fetch_image, resize_for_print

log = logging.getLogger(__name__)

_TASK_RE = re.compile(r"^\[([ xX])\]\s*(.*)$", re.DOTALL)


@dataclass
class TextStyle:
    bold: bool = False
    double_height: bool = False
    double_width: bool = False
    align: str = "left"


def render_escpos(printer, config: Config, tokens: list[Token]) -> None:
    EscposRenderer(printer, config).render(tokens)


class EscposRenderer:
    def __init__(self, printer, config: Config):
        self.printer = printer
        self.config = config
        self._style_stack: list[TextStyle] = [TextStyle()]
        self._list_stack: list[tuple[str, int]] = []
        self._quote_depth = 0

    def render(self, tokens: list[Token]) -> None:
        i = 0
        n = len(tokens)
        while i < n:
            i = self._dispatch(tokens, i)

    @property
    def _style(self) -> TextStyle:
        return self._style_stack[-1]

    def _push_style(self, **changes) -> None:
        new = TextStyle(**self._style.__dict__)
        for k, v in changes.items():
            setattr(new, k, v)
        self._style_stack.append(new)
        self._apply()

    def _pop_style(self) -> None:
        if len(self._style_stack) > 1:
            self._style_stack.pop()
        self._apply()

    def _apply(self) -> None:
        s = self._style
        if s.double_height or s.double_width:
            self.printer.set(
                align=s.align,
                bold=s.bold,
                double_height=s.double_height,
                double_width=s.double_width,
            )
        else:
            self.printer.set(
                align=s.align,
                bold=s.bold,
                normal_textsize=True,
            )

    def _block_prefix(self) -> str:
        return "> " * self._quote_depth + "  " * len(self._list_stack)

    def _dispatch(self, tokens: list[Token], i: int) -> int:
        t = tokens[i]
        ty = t.type
        if ty == "heading_open":
            return self._render_heading(tokens, i)
        if ty == "paragraph_open":
            return self._render_paragraph(tokens, i)
        if ty == "fence":
            return self._render_fence(tokens, i)
        if ty == "code_block":
            return self._render_code_block(tokens, i)
        if ty == "bullet_list_open":
            self._list_stack.append(("ul", 0))
            return i + 1
        if ty == "bullet_list_close":
            if self._list_stack:
                self._list_stack.pop()
            return i + 1
        if ty == "ordered_list_open":
            self._list_stack.append(("ol", 0))
            return i + 1
        if ty == "ordered_list_close":
            if self._list_stack:
                self._list_stack.pop()
            return i + 1
        if ty == "list_item_open":
            return self._render_list_item(tokens, i)
        if ty == "blockquote_open":
            self._quote_depth += 1
            return i + 1
        if ty == "blockquote_close":
            self._quote_depth = max(0, self._quote_depth - 1)
            return i + 1
        if ty == "hr":
            self.printer.text("-" * 32 + "\n")
            return i + 1
        if ty == "table_open":
            return self._render_table(tokens, i)
        return i + 1

    def _render_heading(self, tokens, i):
        level = int(tokens[i].tag[1])
        if level == 1:
            self._push_style(bold=True, double_height=True, double_width=True)
        elif level == 2:
            self._push_style(bold=True, double_width=True)
        else:
            self._push_style(bold=True)
        inline = tokens[i + 1]
        self._emit_inline(inline.children or [])
        self._pop_style()
        self.printer.text("\n")
        return i + 3

    def _render_paragraph(self, tokens, i):
        prefix = self._block_prefix()
        if prefix:
            self.printer.text(prefix)
        inline = tokens[i + 1]
        self._emit_inline(inline.children or [])
        self.printer.text("\n")
        return i + 3

    def _render_fence(self, tokens, i):
        t = tokens[i]
        info = (t.info or "").strip().lower()
        if info == "qr":
            payload = t.content.strip()
            if payload:
                self._push_style(align="center")
                try:
                    self.printer.qr(payload, size=8, native=False)
                except Exception:
                    log.exception("printer.qr failed; rendering as text")
                    self.printer.text(f"[QR: {payload}]\n")
                self._pop_style()
            return i + 1
        for line in (t.content or "").rstrip("\n").split("\n"):
            self.printer.text("  " + line + "\n")
        return i + 1

    def _render_code_block(self, tokens, i):
        t = tokens[i]
        for line in (t.content or "").rstrip("\n").split("\n"):
            self.printer.text("  " + line + "\n")
        return i + 1

    def _render_list_item(self, tokens, i):
        list_type, counter = self._list_stack[-1]
        counter += 1
        self._list_stack[-1] = (list_type, counter)
        depth = len(self._list_stack) - 1
        indent = "  " * depth
        quote = "> " * self._quote_depth

        end = self._find_close(tokens, i, "list_item_open", "list_item_close")

        is_task, checked = False, False
        first_para_idx = -1
        if i + 1 < end and tokens[i + 1].type == "paragraph_open":
            first_para_idx = i + 1
            inline = tokens[first_para_idx + 1]
            if inline.children:
                first = inline.children[0]
                if first.type == "text":
                    m = _TASK_RE.match(first.content)
                    if m:
                        is_task = True
                        checked = m.group(1).lower() == "x"

        if is_task:
            bullet = "[X] " if checked else "[ ] "
        elif list_type == "ol":
            bullet = f"{counter}. "
        else:
            bullet = "- "

        if first_para_idx >= 0:
            self.printer.text(quote + indent + bullet)
            inline = tokens[first_para_idx + 1]
            children = list(inline.children or [])
            if is_task and children and children[0].type == "text":
                m = _TASK_RE.match(children[0].content)
                if m:
                    new = Token("text", "", 0)
                    new.content = m.group(2)
                    new.level = children[0].level
                    children[0] = new
            self._emit_inline(children)
            self.printer.text("\n")
            k = first_para_idx + 3
        else:
            self.printer.text(quote + indent + bullet + "\n")
            k = i + 1

        while k < end:
            k = self._dispatch(tokens, k)
        return end + 1

    def _render_table(self, tokens, i):
        end = self._find_close(tokens, i, "table_open", "table_close")
        rows: list[list[str]] = []
        current_row: list[str] = []
        in_cell = False
        cell_buf: list[str] = []
        j = i + 1
        while j <= end:
            t = tokens[j]
            ty = t.type
            if ty in ("th_open", "td_open"):
                in_cell = True
                cell_buf = []
            elif ty in ("th_close", "td_close"):
                in_cell = False
                current_row.append("".join(cell_buf).strip())
            elif ty == "tr_open":
                current_row = []
            elif ty == "tr_close":
                rows.append(current_row)
                current_row = []
            elif in_cell and ty == "inline":
                cell_buf.append(self._inline_to_plain(t.children or []))
            j += 1
        if rows:
            col_count = max(len(r) for r in rows)
            widths = [0] * col_count
            for r in rows:
                for ci, c in enumerate(r):
                    widths[ci] = max(widths[ci], len(c))
            max_total = 46
            sep = "  "
            total = sum(widths) + len(sep) * max(0, col_count - 1)
            if total > max_total and col_count > 0:
                avail = max_total - len(sep) * max(0, col_count - 1)
                share = max(1, avail // col_count)
                widths = [min(w, share) if w > share else w for w in widths]
            for ri, r in enumerate(rows):
                parts = []
                for ci in range(col_count):
                    cell = r[ci] if ci < len(r) else ""
                    if len(cell) > widths[ci]:
                        cell = cell[: max(1, widths[ci] - 1)] + "…"
                    parts.append(cell.ljust(widths[ci]))
                self.printer.text(sep.join(parts) + "\n")
                if ri == 0 and len(rows) > 1:
                    rule_w = min(46, sum(widths) + len(sep) * max(0, col_count - 1))
                    self.printer.text("-" * rule_w + "\n")
        return end + 1

    def _emit_inline(self, children: list[Token]) -> None:
        for tok in children:
            ty = tok.type
            if ty == "text":
                self.printer.text(tok.content)
            elif ty == "softbreak":
                self.printer.text(" ")
            elif ty == "hardbreak":
                self.printer.text("\n")
            elif ty == "strong_open":
                self._push_style(bold=True)
            elif ty == "strong_close":
                self._pop_style()
            elif ty in ("em_open", "em_close", "s_open", "s_close"):
                pass
            elif ty == "code_inline":
                self.printer.text(tok.content)
            elif ty in ("link_open", "link_close"):
                pass
            elif ty == "image":
                self._emit_image(tok)

    def _emit_image(self, tok: Token) -> None:
        src = tok.attrGet("src") or ""
        if not src:
            return
        self.printer.text("\n")
        img = fetch_image(src, self.config)
        if img is None:
            self.printer.text(f"[image: {src}]\n")
            return
        try:
            sized = resize_for_print(img, self.config.receipt_width_px)
            self._push_style(align="center")
            self.printer.image(sized, center=False, impl="bitImageRaster")
            self._pop_style()
        except Exception:
            log.exception("printer.image failed")
            self.printer.text(f"[image: {src}]\n")

    def _inline_to_plain(self, children: list[Token]) -> str:
        parts: list[str] = []
        for tok in children:
            ty = tok.type
            if ty in ("text", "code_inline"):
                parts.append(tok.content)
            elif ty == "softbreak":
                parts.append(" ")
        return "".join(parts)

    def _find_close(self, tokens, i, open_type, close_type):
        depth = 0
        j = i
        n = len(tokens)
        while j < n:
            t = tokens[j]
            if t.type == open_type:
                depth += 1
            elif t.type == close_type:
                depth -= 1
                if depth == 0:
                    return j
            j += 1
        return n - 1
