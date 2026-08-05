"""Executable entrypoint for the parent-owned Windows local capture helper."""

import asyncio
import sys

from app.infrastructure.liteparse_screen_analyzer import LiteParseScreenAnalyzer
from app.infrastructure.local_capture_helper import (
    JsonLineOutput,
    LocalCaptureHelper,
    run_helper,
)
from app.infrastructure.wasapi_loopback_capture import WasapiLoopbackCapture


async def _main() -> None:
    output = JsonLineOutput(sys.stdout.buffer)
    helper = LocalCaptureHelper(
        LiteParseScreenAnalyzer(),
        WasapiLoopbackCapture(),
        output,
    )
    await run_helper(sys.stdin.buffer, output, helper)


if __name__ == "__main__":
    asyncio.run(_main())
