import asyncio
import hashlib
import re
from collections import defaultdict, deque
from threading import Lock, BoundedSemaphore
from time import monotonic
from urllib.parse import quote

from bson import ObjectId
from fastapi import HTTPException
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from repos.jobs import now
from repos.policy import candidate, safe_text
from .chunks import AIError, chunks
from .provider import Providers, RateLimit


def oid(value):
    if not ObjectId.is_valid(value):
        raise HTTPException(404,"Record not found.")
    return ObjectId(value)


def citation(repo,p):
    path = quote(p["path"],safe="/")
    return {"path":p["path"],"start":p["start"],"end":p["end"],
            "url":f'{repo["github_url"]}/blob/{repo["commit_sha"]}/{path}#L{p["start"]}-L{p["end"]}'}


def grounded(provider,repo,question,history):
    hits = provider.search(repo,question)
    evidence = {}
    budget = 16000
    for hit in hits:
        if not candidate(hit["path"]) or safe_text(hit["text"].encode()) is None:
            continue
        if len(hit["text"])>budget:
            continue
        budget -= len(hit["text"])
        evidence[str(len(evidence)+1)] = hit
    fallback = [{"text":"The retrieved source does not provide enough evidence to answer this question.","citations":[]}]
    if not evidence:
        return fallback
    raw = provider.answer(question,[{"id":k,"path":v["path"],"text":v["text"]} for k,v in evidence.items()],history)
    if not isinstance(raw,list) or len(raw)>20:
        raise AIError("Invalid answer format. Please retry.")
    paragraphs = []
    for row in raw:
        if not isinstance(row,dict) or not isinstance(row.get("text"),str) or len(row["text"])>10000:
            raise AIError("Invalid answer format. Please retry.")
        ids = row.get("ids")
        if not isinstance(ids,list) or not ids:
            continue
        ids = [str(i) if type(i) is int else i for i in ids]
        if any(not isinstance(i,str) or i not in evidence for i in ids):
            continue
        paragraphs.append({"text":row["text"],"citations":[citation(repo,evidence[i]) for i in dict.fromkeys(ids)]})
    if raw and not paragraphs:
        raise AIError("The answer could not be linked to verified source citations. Please retry.")
    return paragraphs or fallback


class AI:
    def __init__(self,db):
        self.repos, self.chats, self.turns = db.repositories, db.conversations, db.messages
        self.provider = Providers()
        self.locks = [Lock() for _ in range(64)]
        self.slots = BoundedSemaphore(3)
        self.rate_lock = Lock()
        self.rates = defaultdict(deque)
        self.stop_event = asyncio.Event()

    def lock(self,rid):
        return self.locks[int(str(rid)[-6:],16)%len(self.locks)]

    def limit(self,user,kind,maximum):
        with self.rate_lock:
            stamp = monotonic()
            for key in list(self.rates):
                bucket = self.rates[key]
                while bucket and bucket[0]<stamp-60:
                    bucket.popleft()
                if not bucket:
                    del self.rates[key]
            bucket = self.rates[(user,kind)]
            if len(bucket)>=maximum:
                raise HTTPException(429,"Too many requests. Try again in a minute.")
            bucket.append(stamp)

    def setup(self):
        self.chats.create_index([("user_id",1),("repo",1),("_id",-1)])
        self.turns.create_index([("user_id",1),("conversation",1),("_id",1)])
        self.repos.create_index([("index_state",1),("status",1)])
        self.repos.update_many({"index_state":"processing"},{"$set":{"index_state":"failed","cleanup_pending":True,"indexed_chunks":0,"index_error":"Interrupted by restart. Retry indexing."}})
        self.next_cleanup = 0
        for chat in self.chats.find({"deleting":True}):
            self.drop_chat(chat)

    def owned(self,rid,user,ready=False):
        repo = self.repos.find_one({"_id":oid(rid),"user_id":user},{"sources":0})
        if not repo:
            raise HTTPException(404,"Repository not found.")
        if ready and (repo.get("index_state")!="completed" or repo.get("deleting")):
            raise HTTPException(409,"Repository index is unavailable.")
        return repo

    def enqueue(self,rid,user):
        repo = self.owned(rid,user)
        if repo["status"]!="retrieved" or repo.get("deleting"):
            raise HTTPException(409,"Source retrieval must finish first.")
        self.limit(user,"index",4)
        result = self.repos.update_one({"_id":repo["_id"],"deleting":{"$ne":True},
            "index_state":{"$nin":["processing","pending","completed"]}},
            {"$set":{"index_state":"pending","index_error":None}})
        if not result.modified_count:
            raise HTTPException(409,"An index already exists or is being processed.")

    def step(self):
        if monotonic() >= self.next_cleanup:
            self.next_cleanup = monotonic()+30
            partial = self.repos.find_one({"index_state":"failed","cleanup_pending":True},{"vectors_started":1})
            if partial:
                with self.lock(partial["_id"]):
                    try:
                        if partial.get("vectors_started"):
                            self.provider.purge(partial["_id"])
                        self.repos.update_one({"_id":partial["_id"]},{"$unset":{"cleanup_pending":""}})
                    except AIError:
                        pass
            pending_delete = self.repos.find_one({"deleting":True},{"user_id":1})
            if pending_delete:
                try:
                    self.delete_repo(pending_delete["_id"],pending_delete["user_id"])
                except (AIError,HTTPException):
                    pass
        job = self.repos.find_one_and_update({"index_state":"pending","status":"retrieved","deleting":{"$ne":True}},
            {"$set":{"index_state":"processing","cleanup_pending":False,"index_error":None}},return_document=ReturnDocument.AFTER)
        if not job:
            return False
        rid = job["_id"]
        active = {"_id":rid,"deleting":{"$ne":True},"index_state":"processing"}
        p = self.provider
        dirty = job.get("vectors_started",False)
        try:
            pieces = chunks(job,p.size,p.overlap,p.max_chunks)
            if not pieces:
                raise AIError("No eligible source chunks to index.")
            signature = hashlib.sha256(("|".join([p.model,str(p.dim)]+[c["id"] for c in pieces])).encode()).hexdigest()
            offset = job.get("indexed_chunks",0) if dirty and job.get("chunk_signature")==signature else 0
            p.verify(p.model,"embedContent")
            p.ensure_collection()
            with self.lock(rid):
                if not self.repos.count_documents(active):
                    return True
                if dirty and not offset:
                    p.purge(rid)
                self.repos.update_one(active,{"$set":{"vectors_started":True,"chunk_signature":signature,"indexed_chunks":offset}})
                dirty = True
            deadline = monotonic()+600
            for pos in range(offset,len(pieces),p.batch):
                if monotonic()>deadline:
                    raise AIError("Indexing exceeded ten minutes. Retry a smaller repository.")
                if not self.repos.count_documents(active):
                    return True
                group = pieces[pos:pos+p.batch]
                vectors = p.embed([c["text"] for c in group])
                with self.lock(rid):
                    if not self.repos.count_documents(active):
                        return True
                    p.put(group,vectors)
                    self.repos.update_one(active,{"$set":{"indexed_chunks":pos+len(group)}})
            self.repos.update_one(active,{"$set":{"index_state":"completed","chunk_count":len(pieces),
                "index_model":p.model,"index_dim":p.dim,"indexed_at":now()}})
        except Exception as exc:
            msg = str(exc) if isinstance(exc,AIError) else "Indexing failed. Check services and retry."
            with self.lock(rid):
                cleanup_pending = False
                keep = isinstance(exc,RateLimit)
                if dirty and not keep and self.repos.count_documents(active):
                    try:
                        p.purge(rid)
                    except Exception:
                        cleanup_pending = True
                        msg += " Vector cleanup will run again on retry or deletion."
                fields = {"index_state":"failed","cleanup_pending":cleanup_pending,"index_error":msg}
                if not keep:
                    fields["indexed_chunks"] = 0
                self.repos.update_one(active,{"$set":fields})
        return True

    async def worker(self):
        while not self.stop_event.is_set():
            try:
                if await asyncio.to_thread(self.step):
                    continue
            except PyMongoError:
                pass
            try:
                await asyncio.wait_for(self.stop_event.wait(),1)
            except TimeoutError:
                pass

    def drop_chat(self,chat):
        self.chats.update_one({"_id":chat["_id"]},{"$set":{"deleting":True}})
        self.turns.delete_many({"conversation":chat["_id"],"user_id":chat["user_id"]})
        self.chats.delete_one({"_id":chat["_id"],"user_id":chat["user_id"]})

    def delete_repo(self,rid,user):
        rid = oid(rid)
        with self.lock(rid):
            repo = self.owned(rid,user)
            self.repos.update_one({"_id":rid},{"$set":{"deleting":True}})
            if repo.get("vectors_started"):
                self.provider.purge(rid)
            self.turns.delete_many({"repo":rid,"user_id":user})
            self.chats.delete_many({"repo":rid,"user_id":user})
            self.repos.delete_one({"_id":rid,"user_id":user})

    def conversation(self,cid,user):
        chat = self.chats.find_one({"_id":oid(cid),"user_id":user,"deleting":{"$ne":True}})
        if not chat:
            raise HTTPException(404,"Conversation not found.")
        repo = self.owned(chat["repo"],user,True)
        if repo["commit_sha"]!=chat["commit"]:
            raise HTTPException(409,"The conversation belongs to a different commit.")
        return chat,repo

    def ask(self,cid,user,question):
        chat,repo = self.conversation(cid,user)
        if safe_text(question.encode()) is None:
            raise HTTPException(422,"Remove credentials or control characters from the question.")
        if not self.slots.acquire(blocking=False):
            raise HTTPException(429,"All answer slots are busy. Try again.")
        lock = self.lock(repo["_id"])
        try:
            if not lock.acquire(blocking=False):
                raise HTTPException(409,"Another request is in progress. Try again.")
            try:
                chat,repo = self.conversation(cid,user)
                if repo.get("index_model")!=self.provider.model or repo.get("index_dim")!=self.provider.dim:
                    raise AIError("Restore the embedding model and dimensions used by this index.")
                self.limit(user,"question",12)
                key = {"conversation":chat["_id"],"user_id":user}
                if self.turns.count_documents(key,limit=100)>=100:
                    raise HTTPException(409,"Conversation is full. Start a new one.")
                previous = list(self.turns.find(key).sort("_id",-1).limit(3))
                history = [{"question":t["question"][:400],"answer":" ".join(p["text"] for p in t["answer"])[:800]} for t in reversed(previous)]
                try:
                    names = re.findall(r"[\w.-]+\.(?:jsx?|tsx?|py|java|cpp|hpp|cc|h|c)\b",question,re.I)
                    if names:
                        snapshot = self.repos.find_one({"_id":repo["_id"],"user_id":user,"commit_sha":repo["commit_sha"]},{"sources.path":1})
                        wanted = {name.casefold() for name in names}
                        repo["named_paths"] = [f["path"] for f in (snapshot or {}).get("sources", [])
                            if f["path"].rsplit("/",1)[-1].casefold() in wanted][:10]
                    answer = grounded(self.provider,repo,question,history)
                except (ValueError,TypeError,KeyError,IndexError):
                    raise AIError("Provider returned unexpected data. Try again.") from None
                turn = {**key,"repo":repo["_id"],"commit":chat["commit"],"question":question,"answer":answer,"created_at":now()}
                self.turns.insert_one(turn)
                self.chats.update_one({"_id":chat["_id"],"title":"New conversation"},{"$set":{"title":question[:80]}})
                return show_turn(turn)
            finally:
                lock.release()
        finally:
            self.slots.release()


def show_turn(t):
    return {"id":str(t["_id"]),"question":t["question"],"answer":t["answer"],"created_at":t["created_at"]}

