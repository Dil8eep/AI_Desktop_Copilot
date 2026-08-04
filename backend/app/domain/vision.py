"""Screen OCR domain models."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TextBlock:
    """One recognized screen text region."""

    text: str
    confidence: float
    polygon: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class ScreenAnalysis:
    """Transient OCR output for a single user-authorized capture."""

    width: int
    height: int
    blocks: tuple[TextBlock, ...]
