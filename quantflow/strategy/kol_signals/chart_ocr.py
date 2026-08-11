"""TradingView / chart image attachment pipeline.

Default backend is a lightweight heuristic + optional Tesseract OCR.
Vision LLM backends can be plugged later via ``ocr_backend='vision_stub'``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from quantflow.strategy.kol_signals.models import AttachmentMeta
from quantflow.strategy.kol_signals.parser import parse_trade_text

logger = logging.getLogger(__name__)

_CHART_NAME = re.compile(r"(?i)(tradingview|chart|screenshot|tv_|binance|bybit|okx|kline|candl)")
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def is_chart_likely(filename: str = "", content_type: str = "", url: str = "") -> bool:
    blob = f"{filename} {content_type} {url}".lower()
    if any(ext in blob for ext in _IMAGE_EXT) or "image/" in content_type.lower():
        if _CHART_NAME.search(blob):
            return True
        # Discord CDN images without name still treated as possible charts
        if "cdn.discordapp.com" in blob or "media.discordapp.net" in blob:
            return True
    return bool(_CHART_NAME.search(blob))


def download_attachment(
    url: str,
    dest_dir: str | Path,
    *,
    filename: str = "",
    timeout: float = 20.0,
) -> Path | None:
    """Download attachment to dest_dir. Returns local path or None on failure."""
    if not url:
        return None
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    name = filename or Path(urlparse(url).path).name or "attachment.bin"
    # sanitize
    name = re.sub(r"[^\w.\-]+", "_", name)[:180]
    path = dest / name
    try:
        import urllib.request

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "QuantFlow-KOL-Ingest/0.1"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        path.write_bytes(data)
        return path
    except Exception as exc:  # pragma: no cover - network
        logger.warning("attachment download failed: %s", exc)
        return None


def ocr_image(
    path: str | Path,
    *,
    backend: str = "auto",
) -> tuple[str, str]:
    """Return (text, backend_used).

    backend:
      - none: skip
      - auto: try tesseract, else empty
      - tesseract: require pytesseract+PIL
      - vision_stub: placeholder for future multimodal API
    """
    p = Path(path)
    if not p.is_file():
        return "", "none"
    b = backend
    if b in ("none", ""):
        return "", "none"
    if b == "vision_stub":
        # Explicit no-op hook — operators can replace with real vision later.
        return "", "vision_stub"
    if b in ("auto", "tesseract"):
        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore

            text = pytesseract.image_to_string(Image.open(p))
            return (text or "").strip(), "tesseract"
        except ImportError:
            if b == "tesseract":
                logger.warning("pytesseract/Pillow not installed")
            return "", "none"
        except Exception as exc:  # pragma: no cover
            logger.warning("tesseract OCR failed: %s", exc)
            return "", "none"
    return "", "none"


def process_attachment(
    *,
    url: str = "",
    local_path: str = "",
    content_type: str = "",
    filename: str = "",
    dest_dir: str | Path = "data/kol_signals/attachments",
    ocr_backend: str = "auto",
    download: bool = True,
) -> AttachmentMeta:
    """Download (optional) + OCR + chart heuristic."""
    chart = is_chart_likely(filename=filename, content_type=content_type, url=url)
    path = local_path
    if download and url and not path:
        dl = download_attachment(url, dest_dir, filename=filename)
        path = str(dl) if dl else ""
    text, used = ("", "none")
    if (path and chart) or (path and ocr_backend not in ("none", "")):
        text, used = ocr_image(path, backend=ocr_backend)
    return AttachmentMeta(
        url=url,
        local_path=path,
        content_type=content_type,
        filename=filename,
        ocr_text=text,
        ocr_backend=used,
        is_chart_likely=chart,
    )


def enrich_text_with_ocr(raw_text: str, attachments: list[AttachmentMeta]) -> dict[str, Any]:
    """Merge message text with OCR blobs and re-parse."""
    parts = [raw_text or ""]
    for a in attachments:
        if a.ocr_text:
            parts.append(a.ocr_text)
    merged = "\n".join(p for p in parts if p).strip()
    parsed = parse_trade_text(merged)
    parsed["merged_text"] = merged
    parsed["ocr_used"] = any(a.ocr_text for a in attachments)
    return parsed
