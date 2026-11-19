import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .schemas import Credentials, Profile, Registration
from .security import COOKIE, DUMMY_HASH, current, issue, require_csrf

router = APIRouter(prefix="/api/auth")
writes = [Depends(require_csrf)]


@router.post("/register", response_model=Profile, status_code=201, dependencies=writes)
def register(data: Registration, request: Request):
    digest = bcrypt.hashpw(data.password.get_secret_value().encode(), bcrypt.gensalt(rounds=12))
    return request.app.state.accounts.register(data.username, data.email, digest)


@router.post("/login", response_model=Profile, dependencies=writes)
def login(data: Credentials, request: Request, response: Response):
    account = request.app.state.accounts.find_login(data.email)
    digest = account["password_hash"] if account else DUMMY_HASH
    matched = bcrypt.checkpw(data.password.get_secret_value().encode(), digest)
    if not matched or not account:
        raise HTTPException(401, "Email or password is incorrect.")
    issue(request, response, account["_id"])
    return account


@router.get("/me", response_model=Profile)
def me(session=Depends(current)):
    return session[1]


@router.post("/logout", status_code=204, dependencies=writes)
def logout(request: Request, response: Response, session=Depends(current)):
    sid, account = session
    request.app.state.accounts.revoke(sid, account["_id"])
    response.delete_cookie(COOKIE, path="/api", httponly=True,
                           secure=request.app.state.settings.secure, samesite="strict")

