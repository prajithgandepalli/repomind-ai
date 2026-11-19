import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from bson import ObjectId
from fastapi import HTTPException, Request

COOKIE = "repomind_session"
ISSUER = "repomind"
DUMMY_HASH = bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt(rounds=12))


def require_csrf(request: Request):
    # Browsers require an approved CORS preflight to set this header cross-origin.
    if request.headers.get("X-RepoMind-CSRF") != "1" or request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Request verification failed.")


def issue(request, response, owner):
    settings = request.app.state.settings
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=settings.lifetime)
    sid = secrets.token_urlsafe(32)
    token = jwt.encode(dict(sub=str(owner), jti=sid, iat=now, exp=expires, iss=ISSUER),
                       settings.secret, algorithm="HS256")
    request.app.state.accounts.start_session(sid, owner, expires)
    response.set_cookie(COOKIE, token, max_age=settings.lifetime, path="/api",
                        httponly=True, secure=settings.secure, samesite="strict")


def current(request: Request):
    denied = HTTPException(401, "Sign in to continue.")
    token = request.cookies.get(COOKIE)
    if not token:
        raise denied
    try:
        claims = jwt.decode(token, request.app.state.settings.secret, algorithms=["HS256"],
                            issuer=ISSUER, options={"require": ["sub", "jti", "iat", "exp"]})
    except jwt.InvalidTokenError:
        raise denied from None
    if not ObjectId.is_valid(claims["sub"]):
        raise denied
    owner = ObjectId(claims["sub"])
    profile = request.app.state.accounts.profile(claims["jti"], owner, datetime.now(timezone.utc))
    if not profile:
        raise denied
    return claims["jti"], profile

