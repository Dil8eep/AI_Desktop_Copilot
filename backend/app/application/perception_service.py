"""Application use case for screen OCR and bounded screen context."""

from app.domain.ports import ScreenAnalyzer
from app.domain.protocol import EventEnvelope
from app.domain.vision import ScreenAnalysis


def _remove_adjacent_ocr_duplicates(text: str) -> str:
    tokens = text.split()
    cleaned: list[str] = []
    index = 0
    while index < len(tokens):
        if index + 1 < len(tokens) and tokens[index].casefold().strip(
            ".,:;!?()"
        ) == tokens[index + 1].casefold().strip(".,:;!?()"):
            cleaned.append(tokens[index])
            index += 2
        else:
            cleaned.append(tokens[index])
            index += 1
    return " ".join(cleaned)


class PerceptionService:
    """Transforms raw OCR output into protocol-safe, bounded context events."""

    def __init__(self, screen_analyzer: ScreenAnalyzer) -> None:
        self._screen_analyzer = screen_analyzer

    async def analyze_screen(
        self, event: EventEnvelope, image_bytes: bytes
    ) -> tuple[EventEnvelope, EventEnvelope]:
        """Analyze a user-authorized image and emit OCR plus context updates."""

        analysis: ScreenAnalysis = await self._screen_analyzer.analyze(image_bytes)
        blocks = [
            {
                "text": block.text,
                "confidence": round(block.confidence, 4),
                "polygon": [list(point) for point in block.polygon],
            }
            for block in analysis.blocks
        ]
        screen_text = _remove_adjacent_ocr_duplicates(
            "\n".join(block.text for block in analysis.blocks)
        )[:12_000]
        return (
            EventEnvelope.create(
                event="vision.updated",
                session_id=event.session_id,
                request_id=event.request_id,
                payload={
                    "width": analysis.width,
                    "height": analysis.height,
                    "blocks": blocks,
                },
            ),
            EventEnvelope.create(
                event="context.updated",
                session_id=event.session_id,
                request_id=event.request_id,
                payload={
                    "screenText": screen_text,
                    "truncated": len(screen_text) >= 12_000,
                },
            ),
        )
