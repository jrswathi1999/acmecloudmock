"""Shared helpers for the company tooling: paths, people, git, logs, HTTP and processes.

ops/ works in two places:
  * in the template repo:  operates on ./run (the generated company)
  * inside run/ops:        operates on run/ itself (marked by the file ops/COMPANY)
"""
import io
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

OPS_DIR = Path(__file__).resolve().parent
REPO_ROOT = OPS_DIR.parent
IS_COMPANY = (OPS_DIR / "COMPANY").exists()
COMPANY = Path(os.environ["ACME_COMPANY_DIR"]).resolve() if os.environ.get("ACME_COMPANY_DIR") else (
    REPO_ROOT if IS_COMPANY else REPO_ROOT / "run"
)
LOGS = COMPANY / "logs"
DATA = COMPANY / "data"
PROD = COMPANY / "prod"
DB_PATH = DATA / "shop.db"

STREAMS = ["ci", "egress", "deploys", "app", "jobs", "audit", "issues", "agent", "alerts"]

PEOPLE = {
    "alex": ("alex", "alex@acme.example.test"),            # tech lead
    "priya": ("priya", "priya@acme.example.test"),         # backend
    "sam": ("sam", "sam@acme.example.test"),               # data
    "jordan": ("jordan", "jordan@acme.example.test"),      # frontend
    "dev-agent": ("dev-agent", "dev-agent@bots.acme.example.test"),  # the AI coding agent
}
HUMANS = ["alex", "priya", "sam", "jordan"]

SHOP_HOST = "127.0.0.1"
SHOP_PORT = 8700
SHOP_URL = f"http://{SHOP_HOST}:{SHOP_PORT}"
PROXY_PORT = 8799
PROXY_URL = f"http://127.0.0.1:{PROXY_PORT}"

ADMIN_KEY = "acme_admin_synth_7f3a9c21"
BUILD_SECRETS = {
    "ACME_ADMIN_KEY": ADMIN_KEY,
    "STRIPE_SECRET_KEY": "rk_synth_4f9a2c7e1b3d5a90",
    "DATABASE_URL": "postgres://app:Winter2026synth@db.acme.example.test:5432/prod",
    "NPM_TOKEN": "npm_synth_e0b47c19d2",
}
SERVER_SETTINGS = {
    "PAYMENTS_API_URL": "http://payments.acme.example.test/v1",
    "ACME_ADMIN_KEYS": ADMIN_KEY,
}


# --------------------------------------------------------------------------- output

def say(msg: str = "") -> None:
    print(msg, flush=True)


class OpsError(RuntimeError):
    """A failure with a message meant for humans (no traceback needed)."""


# --------------------------------------------------------------------------- time + logs

def now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def now_iso() -> str:
    return now().isoformat()


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def log(stream: str, **fields) -> dict:
    LOGS.mkdir(parents=True, exist_ok=True)
    record = {"ts": now_iso(), **fields}
    with open(LOGS / f"{stream}.jsonl", "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read_log(stream: str) -> list:
    path = LOGS / f"{stream}.jsonl"
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def since(entries: list, window: timedelta, ref: datetime = None) -> list:
    ref = ref or now()
    return [e for e in entries if "ts" in e and ref - parse_ts(e["ts"]) <= window]


def touch_logs() -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    for stream in STREAMS:
        (LOGS / f"{stream}.jsonl").touch()


# --------------------------------------------------------------------------- git

class DubiousOwnership(OpsError):
    pass


def ownership_fix(path: Path) -> str:
    return (
        f"git refuses to work in {path} (\"detected dubious ownership\").\n"
        "This happens when the folder is on an exFAT/FAT drive or owned by another user.\n"
        "Fix it once by running this yourself, then re-run the command:\n\n"
        f"    git config --global --add safe.directory {path.as_posix()}\n"
    )


def _git_run(args, author=None, cwd=None):
    env = dict(os.environ)
    if author:
        name, email = PEOPLE[author]
        env.update(GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email,
                   GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL=email)
    cwd = Path(cwd or COMPANY)
    proc = subprocess.run(["git", *args], cwd=str(cwd), env=env, capture_output=True)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")
        if "dubious ownership" in err:
            raise DubiousOwnership(ownership_fix(cwd))
    return proc


def git(*args, author=None, check=True, cwd=None) -> str:
    proc = _git_run(list(args), author=author, cwd=cwd)
    out = proc.stdout.decode("utf-8", "replace").strip()
    if check and proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise OpsError(f"git {' '.join(args)} failed: {err or out}")
    return out


def short_sha(rev: str = "HEAD") -> str:
    return git("rev-parse", "--short=7", rev)


def unpack(sha: str, dest: Path) -> None:
    """Extract a commit's files into dest using `git archive` + tarfile (no shell pipes)."""
    proc = _git_run(["archive", "--format=tar", sha])
    if proc.returncode != 0:
        raise OpsError(f"git archive {sha} failed: {proc.stderr.decode('utf-8', 'replace').strip()}")
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(str(dest), filter="data")
        else:
            tar.extractall(str(dest))


# --------------------------------------------------------------------------- files

def rmtree(path: Path) -> None:
    """shutil.rmtree that also removes read-only files (git objects on Windows)."""
    path = Path(path)
    if not path.exists():
        return

    def _retry(func, p, *_):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_retry)
    else:
        shutil.rmtree(path, onerror=_retry)


def read_text(path: Path) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# --------------------------------------------------------------------------- http (never via a proxy)

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http(method: str, path: str, body=None, headers=None, timeout: float = 10.0):
    """Call the local shop. Returns (status, parsed JSON or text). status 0 = no connection."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(SHOP_URL + path, data=data, method=method, headers=dict(headers or {}))
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with _opener.open(req, timeout=timeout) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (urllib.error.URLError, OSError) as exc:
        return 0, str(exc)
    text = raw.decode("utf-8", "replace")
    try:
        return status, json.loads(text)
    except json.JSONDecodeError:
        return status, text


# --------------------------------------------------------------------------- processes

def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def stop_pid(pid: int) -> None:
    """Stop a process (and its children on Windows). 'Already gone' counts as success."""
    if not pid:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        pass


def spawn_detached(argv, cwd: Path, env: dict, log_path: Path) -> subprocess.Popen:
    """Start a long-running process that outlives this script."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    out = open(log_path, "ab")
    try:
        kwargs = dict(cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT)
        if os.name == "nt":
            base = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            try:  # leave the caller's job object so closing the terminal doesn't kill the shop
                return subprocess.Popen(argv, creationflags=base | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kwargs)
            except OSError:
                return subprocess.Popen(argv, creationflags=base, **kwargs)
        return subprocess.Popen(argv, start_new_session=True, **kwargs)
    finally:
        out.close()


def python_env(**extra) -> dict:
    """A copy of os.environ (Windows needs SYSTEMROOT) plus UTF-8 output and extras."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update({k: str(v) for k, v in extra.items()})
    return env


def require_company() -> None:
    if not (COMPANY / ".git").exists():
        raise OpsError(f"No company found at {COMPANY}. Run `python -m ops.setup` from the template repo first.")
