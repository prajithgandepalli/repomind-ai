import asyncio
import hashlib
import threading
import time
from dataclasses import replace

import httpx
import mongomock
import pytest

from repos.github import retrieve
from repos.jobs import Jobs
from repos.policy import Limits, RetrievalError, candidate, parse_url, safe_text
from test_auth import client, DATA, CREDS


@pytest.mark.parametrize("url", ["http://github.com/a/b", "https://github.com.evil.org/a/b",
    "https://user@github.com/a/b", "https://github.com:443/a/b", "https://github.com/a/b/tree/main",
    "https://github.com/a/%2e%2e", "https://github.com/a/b?x", "https://github.com/a/.."])
def test_reject_url(url):
    with pytest.raises(ValueError):
        parse_url(url)


def test_paths_and_content():
    assert parse_url("https://github.com/Some-Org/example.git/") == ("Some-Org", "example")
    for path in ["a/.env.py", "../a.py", "node_modules/a.js", "x/build/main.cpp", "keys/private_key.py",
                 "config/credentials.ts", "binary.exe", ".git/hooks/file.py"]:
        assert not candidate(path)
    for suffix in ["py", "js", "ts", "jsx", "tsx", "java", "cpp"]:
        assert candidate("src/test." + suffix)
    assert safe_text(b"hello\0world") is None
    assert safe_text(b"\xff") is None
    assert safe_text(b'api_key = "example-credential"') is None


CONTENT = b"print(42)\n"
BLOB = hashlib.sha1(b"blob %d\0" % len(CONTENT) + CONTENT).hexdigest()
COMMIT, TREE = "1" * 40, "2" * 40
BASE = "/repos/org/demo"
ENTRY = {"type": "blob", "mode": "100644", "size": len(CONTENT), "path": "src/main.py", "sha": BLOB}


def scenario(limits=None, meta=None, entries=None, truncated=False, status=None):
    calls, recorded = [], {}

    def handle(req):
        path = req.url.path
        calls.append(path)
        if status:
            return httpx.Response(status)
        if path == BASE:
            return httpx.Response(200, json={"private": False, "size": 10, "default_branch": "main", **(meta or {})})
        if path == BASE + "/commits/main":
            return httpx.Response(200, json={"sha": COMMIT, "commit": {"tree": {"sha": TREE}}})
        if path == BASE + "/git/trees/" + TREE:
            return httpx.Response(200, json={"truncated": truncated, "tree": entries if entries is not None else [ENTRY]})
        assert path == BASE + "/git/blobs/" + BLOB
        return httpx.Response(200, content=CONTENT)

    async def record(fields):
        recorded.update(fields)

    async def active():
        return True

    def run():
        return asyncio.run(retrieve("org", "demo", limits or Limits(), record, active, httpx.MockTransport(handle)))
    return run, calls, recorded


def test_pinned_blobs_and_prefilter():
    run, calls, recorded = scenario(entries=[ENTRY, {**ENTRY, "path":"node_modules/a.js"},
                                             {**ENTRY, "mode":"120000"}, {**ENTRY, "size":999999}])
    files, size = run()
    assert recorded["commit_sha"] == COMMIT and files[0]["text"] == CONTENT.decode() and size == len(CONTENT)
    assert calls == [BASE, BASE+"/commits/main", BASE+"/git/trees/"+TREE, BASE+"/git/blobs/"+BLOB]


@pytest.mark.parametrize("kwargs,message", [
    ({"meta":{"private":True}}, "public"), ({"truncated":True}, "incomplete"),
    ({"limits":replace(Limits(),repo_kib=1)}, "size"), ({"limits":replace(Limits(),download_bytes=4)}, "Download"),
    ({"limits":replace(Limits(),stored_bytes=4)}, "storage"),
    ({"entries":[ENTRY, ENTRY],"limits":replace(Limits(),files=1)}, "count"),
    ({"status":429}, "rate limit"), ({"status":404}, "unavailable"), ({"status":502}, "unreachable")])
def test_failures(kwargs, message):
    run, calls, _ = scenario(**kwargs)
    with pytest.raises(RetrievalError, match=message):
        run()
    if kwargs.get("status") == 502:
        assert len(calls) == 3


def test_routes_worker_and_deletion(client):
    path = "/api/repositories"
    jobs = client.app.state.jobs
    entered, release = threading.Event(), threading.Event()

    async def fetch(owner, name, limits, record, active):
        await record({"commit_sha": COMMIT})
        entered.set()
        while not release.is_set():
            await asyncio.sleep(.01)
        return [{"path":"a.py","text":"42","sha":BLOB}], 2

    jobs.fetch = fetch
    assert client.get(path).status_code == 401
    client.post("/api/auth/register", json=DATA)
    client.post("/api/auth/login", json=CREDS)
    url = {"url":"https://github.com/org/demo"}
    assert client.post(path, json={**url,"user_id":"other"}).status_code == 422
    added = client.post(path, json=url)
    assert added.status_code == 202
    item = path+"/"+added.json()["id"]
    assert entered.wait(2)
    assert client.get(item+"/status").json()["status"] == "retrieving"
    first = dict(client.cookies)
    client.cookies.clear()
    other = {**DATA,"email":"other@example.com"}
    client.post("/api/auth/register", json=other)
    client.post("/api/auth/login", json={**CREDS,"email":other["email"]})
    assert client.get(path).json() == []
    assert all(r.status_code == 404 for r in [client.get(item),client.get(item+"/status"),client.delete(item)])
    client.cookies.clear()
    client.cookies.update(first)
    assert client.delete(item).status_code == 204
    release.set()
    added = client.post(path, json=url).json()
    for _ in range(100):
        state = client.get(path+"/"+added["id"]).json()
        if state["status"]=="retrieved":
            break
        time.sleep(.02)
    assert state["file_count"] == 1 and "sources" not in state
    assert client.get(item).status_code == 404
    assert jobs.collection.count_documents({"sources.text":"42"}) == 1
    assert client.delete(path+"/"+added["id"]).status_code == 204
    assert jobs.collection.count_documents({}) == 0


def test_restart_and_deadline():
    async def run():
        db = mongomock.MongoClient().db.jobs
        db.insert_one({"status":"retrieving"})
        async def slow(*args):
            await asyncio.sleep(10)
        jobs = Jobs(db, slow)
        jobs.limits = replace(jobs.limits, seconds=.02)
        await jobs.start()
        try:
            assert db.find_one()["status"]=="failed"
            await jobs.submit("user","a","b")
            await asyncio.wait_for(jobs.queue.join(), 1)
            assert "time limit" in db.find_one({"user_id":"user"})["error"]
        finally:
            await jobs.stop()
    asyncio.run(run())

