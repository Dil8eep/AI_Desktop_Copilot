"""LiteParse/Tesseract screen analyzer adapter."""

import asyncio
from typing import Any

from app.domain.vision import ScreenAnalysis, TextBlock


class LiteParseScreenAnalyzer:
    """Runs LiteParse OCR outside the event loop."""
    def __init__(self) -> None:
        self._engine: Any | None = None
        self._engine_lock = asyncio.Lock()
        self._inference_lock = asyncio.Lock()

    async def analyze(self, image_bytes: bytes) -> ScreenAnalysis:
        """Parse a screenshot with LiteParse's bundled Tesseract OCR."""
        engine = self._engine
        if engine is None:
            async with self._engine_lock:
                engine = self._engine
                if engine is None:
                    engine = await asyncio.to_thread(self._create_engine)
                    self._engine = engine
        async with self._inference_lock:
            return await asyncio.to_thread(self._analyze_sync, image_bytes, engine)

    def _analyze_sync(self, image_bytes: bytes, engine: Any) -> ScreenAnalysis:
        result = engine.parse(image_bytes)
        blocks: list[TextBlock] = []
        width = 0
        height = 0
        for page in getattr(result, "pages", []):
            width = max(width, int(getattr(page, "width", 0) or 0))
            height = max(height, int(getattr(page, "height", 0) or 0))
            for item in getattr(page, "text_items", []):
                text = getattr(item, "text", "")
                if not isinstance(text, str) or not text.strip():
                    continue
                bbox = getattr(item, "bbox", (0, 0, 0, 0))
                x1, y1, x2, y2 = [int(value) for value in bbox[:4]]
                blocks.append(
                    TextBlock(
                        text=text,
                        confidence=1.0,
                        polygon=((x1, y1), (x2, y1), (x2, y2), (x1, y2)),
                    )
                )
        return ScreenAnalysis(width=width, height=height, blocks=tuple(blocks))

    def _create_engine(self) -> Any:
        from liteparse import LiteParse

        return LiteParse(
            ocr_enabled=True, output_format="json", quiet=True, num_workers=1
        )
