from bisect import bisect_right
import json
from pathlib import PurePosixPath
from uuid import NAMESPACE_URL, uuid5

from langchain_text_splitters import RecursiveCharacterTextSplitter
from repos.policy import candidate, safe_text


class AIError(Exception):
    """Only fixed messages suitable for display."""


LANGUAGES = {k: lang for lang, extensions in {
    "Python": ["py"], "JavaScript": ["js","jsx","mjs","cjs"], "TypeScript": ["ts","tsx"],
    "Java": ["java"], "C++": ["cc","cpp","cxx","hpp","h"], "C": ["c"]}.items() for k in extensions}


def chunks(repo, size, overlap, limit):
    splitter = RecursiveCharacterTextSplitter(chunk_size=size-overlap, chunk_overlap=0,
        strip_whitespace=False, keep_separator=True, separators=["\n\n", "\n", " ", ""])
    rid, commit = str(repo["_id"]), repo["commit_sha"]
    result = []
    for file in repo.get("sources", []):
        path, text = file["path"], file["text"]
        if not candidate(path) or not text.strip() or safe_text(text.encode()) is None:
            continue
        # A lossless partition makes offsets independent of repeated substrings.
        pieces = splitter.split_text(text)
        if "".join(pieces) != text:
            raise AIError("Source offsets could not be verified.")
        starts = [0] + [i+1 for i, c in enumerate(text) if c=="\n"]
        cursor = 0
        for piece in pieces:
            start = max(0, cursor-overlap)
            cursor += len(piece)
            identifier = str(uuid5(NAMESPACE_URL, json.dumps([rid,commit,path,start,cursor])))
            result.append(dict(id=identifier, repo=rid, commit=commit, path=path,
                language=LANGUAGES[PurePosixPath(path).suffix.lower()[1:]], text=text[start:cursor],
                start=bisect_right(starts,start), end=bisect_right(starts,cursor-1)))
            if len(result)>limit:
                raise AIError("Repository exceeds the configured chunk limit.")
    return result

