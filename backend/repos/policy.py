import os
import re
from dataclasses import dataclass
from pathlib import PurePosixPath


class RetrievalError(Exception):
    """Only fixed, user-safe messages belong in this exception."""


def parse_url(url):
    match = re.fullmatch(r"https://github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)/([A-Za-z0-9._-]{1,104})/?", url)
    if not match:
        raise ValueError("Use a public https://github.com/owner/repository URL.")
    owner, name = match.groups()
    name = name.removesuffix(".git")
    if not name or len(name) > 100 or name in {".", ".."} or "--" in owner:
        raise ValueError("Invalid GitHub repository name.")
    return owner, name


@dataclass(frozen=True)
class Limits:
    repo_kib: int = 50000
    files: int = 300
    file_bytes: int = 200000
    download_bytes: int = 12000000
    stored_bytes: int = 4000000
    seconds: int = 120

    @classmethod
    def load(cls):
        limits = cls(**{k: int(os.getenv("REPO_" + k.upper(), v.default)) for k, v in cls.__dataclass_fields__.items()})
        if min(vars(limits).values()) < 1 or limits.stored_bytes > 8000000 or limits.files > 2000:
            raise ValueError("Invalid repository limits.")
        return limits


EXT = {".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".java", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".c"}
SKIP = {"node_modules", "vendor", "dist", "build", "target", "out", "coverage", "venv", "site-packages", "__pycache__", "generated", "third_party", "deps", "bin", "obj"}
SENSITIVE = re.compile(r"credential|secret|private.?key|(^|[./_-])(?:env|token|password|keyfile|id_rsa|id_ed25519)(?:[./_-]|$)", re.I)
CREDENTIAL = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|(?:gh[pousr]_|github_pat_|sk-[a-zA-Z0-9]|xox[baprs]-)[\w-]{12,}|AKIA[A-Z0-9]{16}|ASIA[A-Z0-9]{16}|AIza[\w-]{35}|eyJ[\w-]+\.eyJ[\w-]+\.[\w-]+|://[^\s/@:]+:[^\s/@]+@|(?:password|passwd|secret|api[_-]?key|access[_-]?token|authorization|auth[_-]?token)[\w-]*[\x22']?\s*[:=]\s*[\x22'][^\r\n\x22']+|Bearer\s+[A-Za-z0-9._/-]{12,}", re.I)


def candidate(path):
    if not path or len(path.encode()) > 1024 or "\\" in path or any(ord(c) < 32 for c in path):
        return False
    parts = path.lower().split("/")
    return (all(p and not p.startswith(".") and p not in SKIP for p in parts)
            and PurePosixPath(parts[-1]).suffix in EXT and ".min." not in parts[-1]
            and not SENSITIVE.search(path) and not CREDENTIAL.search(path))


def safe_text(raw):
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if any(ord(c) < 32 and c not in "\r\n\t" for c in text) or CREDENTIAL.search(text):
        return None
    return text

