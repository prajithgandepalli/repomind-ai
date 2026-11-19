from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from auth.security import current, require_csrf
from .jobs import public
from .policy import parse_url


router = APIRouter(prefix="/api/repositories")
writes = [Depends(require_csrf)]


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(max_length=256)


def key(id, session):
    if not ObjectId.is_valid(id):
        raise HTTPException(404, "Repository not found.")
    return {"_id": ObjectId(id), "user_id": session[1]["_id"]}


@router.post("", status_code=202, dependencies=writes)
async def submit(data: Submission, request: Request, session=Depends(current)):
    try:
        owner, name = parse_url(data.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    request.app.state.ai.limit(session[1]['_id'],'submission',4)
    return await request.app.state.jobs.submit(session[1]["_id"], owner, name)


@router.get("")
def repositories(request: Request, session=Depends(current)):
    docs = request.app.state.jobs.collection.find({"user_id": session[1]["_id"]}, {"sources": 0})
    return [public(doc) for doc in docs.sort("created_at", -1)]


@router.get("/{id}")
@router.get("/{id}/status")
def repository(id: str, request: Request, session=Depends(current)):
    doc = request.app.state.jobs.collection.find_one(key(id, session), {"sources": 0})
    if not doc:
        raise HTTPException(404, "Repository not found.")
    return public(doc)


@router.delete("/{id}", status_code=204, dependencies=writes)
def remove(id: str, request: Request, session=Depends(current)):
    request.app.state.ai.delete_repo(id,session[1]["_id"])

