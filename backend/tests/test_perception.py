from uuid import uuid4

import pytest

from app.application.perception_service import PerceptionService
from app.domain.protocol import EventEnvelope
from app.domain.vision import ScreenAnalysis, TextBlock


class FakeScreenAnalyzer:
    async def analyze(self, image_bytes: bytes) -> ScreenAnalysis:
        assert image_bytes == b"test-image"
        return ScreenAnalysis(
            width=1920,
            height=1080,
            blocks=(
                TextBlock(
                    text="Copilot test", confidence=0.99, polygon=((1, 2), (3, 4))
                ),
            ),
        )


@pytest.mark.asyncio
async def test_screen_analysis_produces_vision_and_bounded_context() -> None:
    service = PerceptionService(FakeScreenAnalyzer())
    request = EventEnvelope.create(
        event="screen.capture",
        session_id=uuid4(),
        payload={"mimeType": "image/png", "byteLength": 10},
    )

    vision, context = await service.analyze_screen(request, b"test-image")

    assert vision.event == "vision.updated"
    assert vision.payload["blocks"][0]["text"] == "Copilot test"
    assert context.payload == {"screenText": "Copilot test", "truncated": False}
