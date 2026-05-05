from markdown_it import MarkdownIt


def make_parser() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"breaks": False, "html": False, "linkify": True})
    md.enable(["table", "strikethrough"])
    return md
