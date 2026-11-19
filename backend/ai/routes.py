from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from auth.security import current, require_csrf
from repos.jobs import now
from .service import show_turn

router = APIRouter(prefix="/api")
writes = [Depends(require_csrf)]


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1,max_length=2000)


def user(session=Depends(current)):
    return session[1]["_id"]


@router.post("/repositories/{id}/index",status_code=202,dependencies=writes)
def index(id:str,request:Request,owner=Depends(user)):
    request.app.state.ai.enqueue(id,owner)
    return {"index_state":"pending"}


def summary(chat):
    return {"id":str(chat["_id"]),"title":chat["title"],"commit":chat["commit"]}


@router.post("/repositories/{id}/conversations",status_code=201,dependencies=writes)
def create(id:str,request:Request,owner=Depends(user)):
    ai = request.app.state.ai
    repo = ai.owned(id,owner,True)
    with ai.lock(repo["_id"]):
        repo = ai.owned(id,owner,True)
        key = {"repo":repo["_id"],"user_id":owner}
        if ai.chats.count_documents(key,limit=50)>=50:
            raise HTTPException(409,"Conversation limit reached. Delete an older conversation.")
        chat = {**key,"commit":repo["commit_sha"],"title":"New conversation","created_at":now()}
        ai.chats.insert_one(chat)
        return summary(chat)


@router.get("/repositories/{id}/conversations")
def conversations(id:str,request:Request,owner=Depends(user)):
    ai = request.app.state.ai
    repo = ai.owned(id,owner,True)
    key = {"repo":repo["_id"],"user_id":owner,"commit":repo["commit_sha"],"deleting":{"$ne":True}}
    return [summary(c) for c in ai.chats.find(key).sort("_id",-1).limit(50)]


@router.get("/conversations/{id}/messages")
def messages(id:str,request:Request,owner=Depends(user)):
    ai = request.app.state.ai
    chat,_ = ai.conversation(id,owner)
    return [show_turn(t) for t in ai.turns.find({"conversation":chat["_id"],"user_id":owner}).sort("_id",1).limit(100)]


@router.post("/conversations/{id}/messages",status_code=201,dependencies=writes)
def ask(id:str,data:Question,request:Request,owner=Depends(user)):
    return request.app.state.ai.ask(id,owner,data.question)


@router.delete("/conversations/{id}",status_code=204,dependencies=writes)
def delete(id:str,request:Request,owner=Depends(user)):
    ai = request.app.state.ai
    chat,_ = ai.conversation(id,owner)
    with ai.lock(chat["repo"]):
        ai.drop_chat(ai.conversation(id,owner)[0])

