import asyncio
import hashlib
import json
import os
import re
from urllib.parse import quote

import httpx

from .policy import RetrievalError, candidate, safe_text


def sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise RetrievalError("GitHub returned an invalid object identifier.")
    return value


async def retrieve(owner, name, limits, record, active, transport=None):
    consumed = 0
    headers = {"Accept-Encoding": "identity", "User-Agent": "RepoMind", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    async with httpx.AsyncClient(base_url="https://api.github.com", headers=headers, timeout=8,
                                 follow_redirects=False, transport=transport) as client:
        async def get(path, raw=False):
            nonlocal consumed
            for attempt in range(3):
                if not await active():
                    raise RetrievalError("Repository was deleted.")
                try:
                    async with client.stream("GET", path, headers={"Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json"}) as res:
                        if res.status_code in (403, 429):
                            raise RetrievalError("GitHub denied access or reached its rate limit. Try again later.")
                        if res.status_code in (404, 301, 302):
                            raise RetrievalError("Public repository or commit unavailable. Check the canonical URL.")
                        if res.status_code >= 500:
                            raise httpx.RequestError("upstream")
                        if res.status_code != 200:
                            raise RetrievalError("GitHub could not provide this repository.")
                        if res.headers.get("content-encoding", "identity") != "identity":
                            raise RetrievalError("Unexpected GitHub response encoding.")
                        body = bytearray()
                        async for chunk in res.aiter_bytes(16384):
                            consumed += len(chunk)
                            if consumed > limits.download_bytes or (raw and len(body)+len(chunk)>limits.file_bytes):
                                raise RetrievalError("Download size limit exceeded.")
                            body.extend(chunk)
                        return bytes(body) if raw else json.loads(body)
                except httpx.RequestError:
                    if attempt == 2:
                        raise RetrievalError("GitHub is temporarily unreachable.") from None
                    await asyncio.sleep(0.25 * 2**attempt)

        base = f"/repos/{owner}/{name}"
        meta = await get(base)
        if meta.get("private") is not False or meta.get("visibility", "public") != "public":
            raise RetrievalError("Only public repositories are supported.")
        if meta["size"] > limits.repo_kib:
            raise RetrievalError("Repository size limit exceeded.")
        commit = await get(base + "/commits/" + quote(meta["default_branch"], safe=""))
        commit_sha = sha(commit["sha"])
        tree_sha = sha(commit["commit"]["tree"]["sha"])
        await record({"commit_sha": commit_sha, "description": (meta.get("description") or "")[:500],
                      "language": meta.get("language")})
        tree = await get(base + "/git/trees/" + tree_sha + "?recursive=1")
        if tree.get("truncated") is not False:
            raise RetrievalError("GitHub returned an incomplete file tree.")
        entries = [e for e in tree["tree"] if e["type"] == "blob" and e["mode"] in ("100644", "100755")
                   and candidate(e["path"]) and 0 <= e["size"] <= limits.file_bytes]
        if len(entries) > limits.files:
            raise RetrievalError("Eligible file count exceeds the configured limit.")
        files = []
        stored = 0
        for entry in entries:
            blob = sha(entry["sha"])
            data = await get(base + "/git/blobs/" + blob, raw=True)
            if len(data) != entry["size"] or hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() != blob:
                raise RetrievalError("GitHub file integrity check failed.")
            text = safe_text(data)
            if text is not None:
                stored += len(data)
                if stored > limits.stored_bytes:
                    raise RetrievalError("Source storage limit exceeded.")
                files.append({"path": entry["path"], "sha": blob, "text": text})
        return files, stored

