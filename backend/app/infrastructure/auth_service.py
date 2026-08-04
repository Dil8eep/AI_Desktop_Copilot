"""JWT and bcrypt credential services."""

from datetime import UTC, datetime, timedelta
from typing import Any


class PasswordService:
    """Hash and verify passwords with bcrypt."""

    @staticmethod
    def hash(password: str) -> str:
        import bcrypt

        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    @staticmethod
    def verify(password: str, password_hash: str) -> bool:
        import bcrypt

        return bcrypt.checkpw(password.encode(), password_hash.encode())


class JwtService:
    """Issue and validate signed HS256 JWT access tokens."""

    def __init__(self, secret: str, access_minutes: int) -> None:
        self._secret = secret
        self._access_minutes = access_minutes

    def issue_access_token(self, user_id: str) -> str:
        import jwt

        now = datetime.now(UTC)
        payload: dict[str, Any] = {
            "sub": user_id,
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=self._access_minutes),
        }
        return str(jwt.encode(payload, self._secret, algorithm="HS256"))

    def verify_access_token(self, token: str) -> str:
        import jwt

        payload = jwt.decode(token, self._secret, algorithms=["HS256"])
        if payload.get("type") != "access" or not isinstance(payload.get("sub"), str):
            raise ValueError("invalid_access_token")
        return str(payload["sub"])
