import asyncio
from contextlib import suppress
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import PyMongoError

from .github import retrieve
from .policy import Limits, RetrievalError


def now():
    return datetime.now(timezone.utc)


def public(doc):
    return {"id": str(doc["_id"]), **{k: v for k, v in doc.items() if k not in {"_id", "user_id", "sources", "cleanup_pending", "vectors_started"}}}


class Jobs:
    """One worker in the single-process Compose backend."""
    def __init__(self, collection, fetch=retrieve):
        self.collection = collection
        self.fetch = fetch
        self.limits = Limits.load()
        self.queue = asyncio.Queue(maxsize=20)
        self.lock = asyncio.Lock()

    async def start(self):
        await asyncio.to_thread(self.collection.create_index, [("user_id", 1), ("created_at", -1)])
        await asyncio.to_thread(self.collection.update_many, {"status": {"$in": ["queued", "retrieving"]}},
                                {"$set": {"status": "failed", "error": "Interrupted by restart. Delete and resubmit.", "updated_at": now()}})
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        self.task.cancel()
        with suppress(asyncio.CancelledError):
            await self.task

    async def submit(self, user, owner, name):
        async with self.lock:
            if self.queue.full() or await asyncio.to_thread(self.collection.count_documents, {"user_id": user}, limit=50) >= 50:
                raise HTTPException(429, "Queue or account repository limit reached.")
            stamp = now()
            doc = {"_id": ObjectId(), "user_id": user, "owner": owner, "name": name,
                   "github_url": f"https://github.com/{owner}/{name}", "description": "", "language": None,
                   "commit_sha": None, "file_count": 0, "stored_bytes": 0, "created_at": stamp,
                   "updated_at": stamp, "status": "queued", "error": None}
            await asyncio.to_thread(self.collection.insert_one, doc)
            self.queue.put_nowait(doc)
            return public(doc)

    async def run(self):
        while True:
            job = await self.queue.get()
            try:
                await self.process(job)
            except PyMongoError:
                # Retry persisting the terminal status while the database recovers.
                while True:
                    try:
                        await self.update(job, {"status": "failed", "error": "Database unavailable during retrieval."})
                        break
                    except PyMongoError:
                        await asyncio.sleep(2)
            finally:
                self.queue.task_done()

    def key(self, job):
        return {"_id": job["_id"], "user_id": job["user_id"]}

    async def update(self, job, fields):
        result = await asyncio.to_thread(self.collection.update_one, self.key(job),
                                         {"$set": {**fields, "updated_at": now()}})
        return result.matched_count > 0

    async def process(self, job):
        if not await self.update(job, {"status": "retrieving"}):
            return

        async def active():
            return await asyncio.to_thread(self.collection.count_documents, self.key(job), limit=1)

        async def record(fields):
            if not await self.update(job, fields):
                raise RetrievalError("Repository was deleted.")

        try:
            async with asyncio.timeout(self.limits.seconds):
                files, size = await self.fetch(job["owner"], job["name"], self.limits, record, active)
            await record({"status": "retrieved", "index_state": "pending", "sources": files, "file_count": len(files), "stored_bytes": size})
        except PyMongoError:
            raise
        except Exception as exc:
            message = str(exc) if isinstance(exc, RetrievalError) else (
                "Processing time limit exceeded." if isinstance(exc, TimeoutError) else "Unable to process GitHub data.")
            await self.update(job, {"status": "failed", "error": message})

