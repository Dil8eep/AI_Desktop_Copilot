"""Authenticated resume upload router retained for modular composition."""

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.api.auth_dependencies import require_user_id
from app.application.resume_service import ResumeService
from app.infrastructure.auth_service import JwtService


def create_resume_router(service: ResumeService, jwt_service: JwtService) -> APIRouter:
    """Create user-scoped resume upload routes with explicit dependencies."""
    router = APIRouter(prefix="/api")

    @router.post("/resume/upload")
    async def upload_resume(
        request: Request, authorization: str | None = Header(default=None)
    ) -> JSONResponse:
        user_id = require_user_id(authorization, jwt_service)
        filename = request.headers.get("x-filename", "resume.pdf")
        content_type = request.headers.get("content-type", "")
        if content_type and "application/pdf" not in content_type:
            return JSONResponse({"error": "resume_pdf_required"}, status_code=415)
        try:
            upload = await service.upload(user_id, filename, await request.body())
        except ValueError as error:
            return JSONResponse({"error": str(error)}, status_code=400)
        return JSONResponse(
            {
                "status": "uploaded",
                "uploadId": str(upload.upload_id),
                "filename": upload.filename,
                "sizeBytes": upload.size_bytes,
            },
            status_code=201,
        )

    return router