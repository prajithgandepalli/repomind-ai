import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    secret: str = field(repr=False)
    secure: bool
    lifetime: int = 3600

    @classmethod
    def load(cls):
        secret = os.environ.get("JWT_SECRET", "")
        if len(secret.encode()) < 32:
            raise RuntimeError("Set JWT_SECRET to at least 32 random bytes.")
        secure = os.environ.get("COOKIE_SECURE", "true").lower()
        if secure not in {"true", "false"}:
            raise RuntimeError("COOKIE_SECURE must be true or false.")
        return cls(secret, secure == "true")

