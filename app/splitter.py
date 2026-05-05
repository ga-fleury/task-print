SEPARATOR = ";;;"


def split_tasks(text: str) -> list[str]:
    chunks: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        if line.strip() == SEPARATOR:
            joined = "\n".join(buf).strip()
            if joined:
                chunks.append(joined)
            buf = []
        else:
            buf.append(line)
    tail = "\n".join(buf).strip()
    if tail:
        chunks.append(tail)
    return chunks
