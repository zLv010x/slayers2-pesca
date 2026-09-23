"""Leitura de texto na tela usando o OCR que já vem no Windows (Windows.Media.Ocr)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import cv2
import numpy as np
from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter

# Texto pequeno é lido melhor quando ampliado antes do OCR.
MIN_HEIGHT_PX = 120

_engine: OcrEngine | None = None


def _get_engine() -> OcrEngine:
    global _engine
    if _engine is None:
        _engine = OcrEngine.try_create_from_user_profile_languages()
        if _engine is None:
            raise RuntimeError("OCR do Windows indisponível: instale um pacote de idioma com OCR.")
    return _engine


def _to_bitmap(bgr: np.ndarray) -> SoftwareBitmap:
    bgra = cv2.cvtColor(bgr, cv2.COLOR_BGR2BGRA)
    h, w = bgra.shape[:2]
    writer = DataWriter()
    writer.write_bytes(bgra.tobytes())
    return SoftwareBitmap.create_copy_with_alpha_from_buffer(
        writer.detach_buffer(), BitmapPixelFormat.BGRA8, w, h, BitmapAlphaMode.PREMULTIPLIED
    )


@dataclass(frozen=True)
class Line:
    text: str
    x: int
    y: int
    w: int
    h: int


async def _recognize(bitmap: SoftwareBitmap, scale: float) -> list[Line]:
    result = await _get_engine().recognize_async(bitmap)
    lines = []
    for line in result.lines:
        rects = [word.bounding_rect for word in line.words]
        x0 = min(r.x for r in rects)
        y0 = min(r.y for r in rects)
        x1 = max(r.x + r.width for r in rects)
        y1 = max(r.y + r.height for r in rects)
        lines.append(Line(
            line.text,
            int(x0 / scale), int(y0 / scale),
            int((x1 - x0) / scale), int((y1 - y0) / scale),
        ))
    return lines


def read_lines(bgr: np.ndarray, min_height: int = MIN_HEIGHT_PX) -> list[Line]:
    """Devolve as linhas de texto (com posição em pixels da imagem original)."""
    h = bgr.shape[0]
    scale = 1.0
    if h < min_height:
        scale = min_height / max(h, 1)
        bgr = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return asyncio.run(_recognize(_to_bitmap(bgr), scale))
