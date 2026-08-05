"""Per-user temporary resume lifecycle tests."""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from app.application.resume_service import ResumeService


class RecordingParser:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def parse(self, user_id: str, text: str) -> dict[str, object]:
        del user_id
        self.texts.append(text)
        return {"summary": text}


@pytest.mark.asyncio
async def test_uploads_are_isolated_by_user_and_deleted_after_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = ResumeService(tmp_path, max_file_bytes=1_000)
    first_user = str(uuid4())
    second_user = str(uuid4())
    monkeypatch.setattr(
        ResumeService,
        "_parse_sync",
        staticmethod(lambda path: path.read_bytes().decode("utf-8")),
    )

    first = await service.upload(first_user, "first.pdf", b"first profile")
    second = await service.upload(second_user, "second.pdf", b"second profile")
    parser = RecordingParser()

    profile = await service.parse_profile(first_user, parser)
    await service.discard_upload(first_user)

    assert profile == {"summary": "first profile"}
    assert not await asyncio.to_thread(Path(first.path).exists)
    assert await asyncio.to_thread(Path(second.path).exists)
    assert await service.parse_latest(second_user) == "second profile"


@pytest.mark.asyncio
async def test_new_upload_replaces_only_that_users_pending_file(
    tmp_path: Path,
) -> None:
    service = ResumeService(tmp_path, max_file_bytes=1_000)
    user_id = str(uuid4())

    previous = await service.upload(user_id, "old.pdf", b"old")
    current = await service.upload(user_id, "new.pdf", b"new")

    assert not await asyncio.to_thread(Path(previous.path).exists)
    assert await asyncio.to_thread(Path(current.path).exists)


@pytest.mark.asyncio
async def test_user_without_upload_cannot_parse_another_users_file(
    tmp_path: Path,
) -> None:
    service = ResumeService(tmp_path, max_file_bytes=1_000)
    await service.upload(str(uuid4()), "resume.pdf", b"private")

    with pytest.raises(ValueError, match="resume_upload_required"):
        await service.parse_latest(str(uuid4()))
