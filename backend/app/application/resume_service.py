"""Per-user temporary resume upload and parsing service."""

import asyncio
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4


class ResumeUpload:
    """Metadata returned for an authenticated user's temporary upload."""

    def __init__(
        self, upload_id: UUID, filename: str, path: str, size_bytes: int
    ) -> None:
        self.upload_id = upload_id
        self.filename = filename
        self.path = path
        self.size_bytes = size_bytes


class ResumeService:
    """Keep one temporary PDF per user until its profile is safely persisted."""

    def __init__(self, upload_directory: Path, max_file_bytes: int) -> None:
        self._upload_directory = upload_directory
        self._max_file_bytes = max_file_bytes
        self._latest_uploads: dict[str, ResumeUpload] = {}
        self._upload_lock = asyncio.Lock()

    async def upload(
        self, user_id: str, filename: str, content: bytes
    ) -> ResumeUpload:
        normalized_user_id = str(UUID(user_id))
        safe_name = Path(filename).name
        if not safe_name.lower().endswith(".pdf"):
            raise ValueError("resume_pdf_required")
        if not content:
            raise ValueError("resume_file_empty")
        if len(content) > self._max_file_bytes:
            raise ValueError("resume_file_too_large")

        upload_id = uuid4()
        user_directory = self._upload_directory / normalized_user_id
        destination = user_directory / f"{upload_id}.pdf"
        await asyncio.to_thread(user_directory.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(destination.write_bytes, content)
        upload = ResumeUpload(upload_id, safe_name, str(destination), len(content))

        async with self._upload_lock:
            previous = self._latest_uploads.get(normalized_user_id)
            self._latest_uploads[normalized_user_id] = upload
        if previous is not None and previous.path != upload.path:
            await self._delete_path(Path(previous.path))
        return upload

    async def parse_latest(self, user_id: str) -> str:
        normalized_user_id = str(UUID(user_id))
        async with self._upload_lock:
            upload = self._latest_uploads.get(normalized_user_id)
        if upload is None:
            raise ValueError("resume_upload_required")
        return await asyncio.to_thread(self._parse_sync, Path(upload.path))

    async def parse_profile(
        self, user_id: str, parser: Any
    ) -> dict[str, object]:
        text = await self.parse_latest(user_id)
        profile = await parser.parse(text)
        if not isinstance(profile, dict):
            raise ValueError("resume_profile_invalid_json")
        return profile

    async def discard_upload(self, user_id: str) -> None:
        """Delete only the authenticated user's successfully processed PDF."""
        normalized_user_id = str(UUID(user_id))
        async with self._upload_lock:
            upload = self._latest_uploads.pop(normalized_user_id, None)
        if upload is None:
            return
        path = Path(upload.path)
        await self._delete_path(path)
        try:
            await asyncio.to_thread(path.parent.rmdir)
        except OSError:
            pass

    @staticmethod
    async def _delete_path(path: Path) -> None:
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _parse_sync(path: Path) -> str:
        data = path.read_bytes()
        text = ""
        try:
            from pypdf import PdfReader

            text = "\n".join(
                page.extract_text() or "" for page in PdfReader(path).pages
            ).strip()
        except Exception:
            pass
        if len(" ".join(text.split())) >= 80:
            return text

        from liteparse import LiteParse

        result = LiteParse(
            ocr_enabled=True,
            output_format="json",
            quiet=True,
            num_workers=1,
        ).parse(data)
        return "\n".join(
            item.text.strip()
            for page in getattr(result, "pages", [])
            for item in getattr(page, "text_items", [])
            if isinstance(getattr(item, "text", None), str) and item.text.strip()
        )