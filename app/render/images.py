import base64
import io
import logging
import re
from typing import Optional
from urllib.parse import unquote

import requests
from PIL import Image

from ..config import Config

log = logging.getLogger(__name__)

_DATA_URI_RE = re.compile(r"^data:([^;,]+)(?:;([^,]+))?,(.+)$", re.DOTALL)


def fetch_image(src: str, config: Config) -> Optional[Image.Image]:
    if not src:
        return None
    if src.startswith("data:"):
        return _decode_data_uri(src)
    if src.startswith(("http://", "https://")):
        return _fetch_url(src, config)
    return None


def _decode_data_uri(src: str) -> Optional[Image.Image]:
    m = _DATA_URI_RE.match(src)
    if not m:
        return None
    encoding = m.group(2) or ""
    payload = m.group(3)
    try:
        if "base64" in encoding:
            data = base64.b64decode(payload)
        else:
            data = unquote(payload).encode("latin-1")
        return Image.open(io.BytesIO(data))
    except Exception:
        log.exception("failed to decode data URI image")
        return None


def _fetch_url(src: str, config: Config) -> Optional[Image.Image]:
    try:
        with requests.get(src, timeout=config.image_fetch_timeout, stream=True) as r:
            r.raise_for_status()
            cl = r.headers.get("content-length")
            if cl and int(cl) > config.image_max_bytes:
                log.warning("image too large (declared): %s (%s bytes)", src, cl)
                return None
            chunks: list[bytes] = []
            total = 0
            for chunk in r.iter_content(chunk_size=65536):
                total += len(chunk)
                if total > config.image_max_bytes:
                    log.warning("image too large (streamed): %s", src)
                    return None
                chunks.append(chunk)
            return Image.open(io.BytesIO(b"".join(chunks)))
    except Exception:
        log.exception("failed to fetch image: %s", src)
        return None


def resize_for_print(img: Image.Image, max_width: int) -> Image.Image:
    if img.mode not in ("RGB", "L", "1"):
        img = img.convert("RGB")
    if img.width > max_width:
        ratio = max_width / img.width
        new_height = max(1, int(img.height * ratio))
        img = img.resize((max_width, new_height), Image.LANCZOS)
    return img
