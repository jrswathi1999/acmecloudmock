"""Local CI runner: executes the `run:` steps of .github/workflows/ci.yml for a commit.

    python -m ops.ci_local <sha>          run CI for a commit
    python -m ops.ci_local outage on|off  simulate a hosted-runner outage (vendor-outage scenario)
"""
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from ops import common, egress_proxy

TAIL_LINES = 6
STEP_TIMEOUT = 900
OUTAGE_FLAG = common.PROD / "runner_outage"
PIP_INSTALL = re.compile(r"^\s*(python3?\s+-m\s+)?pip3?\s+install\b")
SECRET_REF = re.compile(r"\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}")


def next_run_id() -> int:
    runs = [e["run"] for e in common.read_log("ci") if isinstance(e.get("run"), int)]
    return max(runs) + 1 if runs else 9001


def outage_on() -> bool:
    return OUTAGE_FLAG.exists() or os.environ.get("ACME_RUNNER_OUTAGE") == "1"


def set_outage(on: bool) -> None:
    if on:
        common.write_text(OUTAGE_FLAG, "hosted runners unavailable\n")
    elif OUTAGE_FLAG.exists():
        OUTAGE_FLAG.unlink()


def build_env(workdir: Path, job_env: dict) -> dict:
    # Every step sees every build secret: no per-step scoping (weakness #4).
    env = common.python_env()
    env.update(common.BUILD_SECRETS)
    for key, value in (job_env or {}).items():
        env[key] = SECRET_REF.sub(lambda m: common.BUILD_SECRETS.get(m.group(1), ""), str(value))
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env[name] = common.PROXY_URL
    for name in ("NO_PROXY", "no_proxy"):
        env.pop(name, None)
    env["CI"] = "true"
    env["ACME_DB"] = str(workdir / "ci-data" / "shop.db")
    env["ACME_LOG_DIR"] = str(workdir / "ci-logs")
    return env


def _exec(cmd: str, cwd: Path, env: dict):
    argv = shlex.split(cmd)
    if argv and argv[0] in ("python", "python3", "py"):
        argv[0] = sys.executable
    try:
        proc = subprocess.run(argv, cwd=str(cwd), env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=STEP_TIMEOUT)
    except FileNotFoundError:
        return 127, [f"{argv[0]}: command not found"]
    except subprocess.TimeoutExpired:
        return 124, [f"step timed out after {STEP_TIMEOUT}s"]
    out = proc.stdout.decode("utf-8", "replace").splitlines()
    tail = [line.rstrip() for line in out if line.strip()][-TAIL_LINES:]
    return proc.returncode, tail


def _outage_log(run_id: int) -> list:
    return [
        "Requested labels: ubuntu-latest",
        "Waiting for a runner to pick up this job...",
        "The job was not picked up by a hosted runner within 5 minutes",
        f"Error: 503 Service Unavailable from api.github.com (GET /repos/acme/acme-shop/actions/runs/{run_id}/jobs)",
        "The job was not picked up by a hosted runner",
        "Job cancelled: no hosted runner available",
    ]


def run(sha: str) -> dict:
    sha = common.short_sha(sha)
    run_id = next_run_id()
    lines = [f"run {run_id} for {sha} on the local runner"]
    attempts = []
    status = "success"
    if outage_on():
        lines += _outage_log(run_id)
        status = "failure"
    else:
        workdir = Path(tempfile.mkdtemp(prefix=f"acme-ci-{run_id}-"))
        src = workdir / "src"
        try:
            common.unpack(sha, src)
            workflow = yaml.safe_load(common.read_text(src / ".github" / "workflows" / "ci.yml")) or {}
            with egress_proxy.running(run_id) as attempts:
                for job_name, job in (workflow.get("jobs") or {}).items():
                    env = build_env(workdir, job.get("env") or {})
                    lines.append(f"job: {job_name}")
                    for number, step in enumerate(job.get("steps") or [], 1):
                        if "run" not in step:
                            lines.append(f"[{number}] uses {step.get('uses')}: provided by the local runner, skipped")
                            continue
                        name = step.get("name") or str(step["run"]).strip().splitlines()[0]
                        lines.append(f"[{number}] {name}")
                        for cmd in str(step["run"]).strip().splitlines():
                            cmd = cmd.strip()
                            if not cmd or cmd.startswith("#"):
                                continue
                            lines.append(f"  $ {cmd}")
                            if PIP_INSTALL.search(cmd):
                                lines.append("  skipped: pip install (the local runner uses its preinstalled environment)")
                                continue
                            code, tail = _exec(cmd, src, env)
                            lines += ["  " + t for t in tail]
                            lines.append(f"  exit code {code}")
                            if code != 0:
                                status = "failure"
                                break
                        if status == "failure":
                            break
                    if status == "failure":
                        break
                attempts = list(attempts)
        except Exception as exc:  # a broken workflow file is a failed build, not a crash
            status = "failure"
            lines.append(f"runner error: {type(exc).__name__}: {exc}")
        finally:
            common.rmtree(workdir)
    lines.append(f"conclusion: {status}")
    common.log("ci", run=run_id, sha=sha, status=status, log=lines, runner="local")
    common.say(f"  ci run {run_id} on {sha}: {status.upper()}")
    for attempt in attempts:
        common.say(f"  egress proxy BLOCKED {attempt['method']} {attempt['host']} ({attempt['bytes_out']} bytes) during run {run_id}")
    if status == "failure":
        for line in lines[-4:]:
            common.say(f"    {line}")
    return {"run": run_id, "sha": sha, "status": status, "log": lines, "egress": attempts}


def main(argv) -> int:
    if len(argv) == 2 and argv[0] == "outage":
        set_outage(argv[1] == "on")
        common.say(f"runner outage switch: {'ON' if outage_on() else 'off'}")
        return 0
    if len(argv) != 1:
        common.say(__doc__)
        return 2
    common.require_company()
    return 0 if run(argv[0])["status"] == "success" else 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except common.OpsError as exc:
        common.say(str(exc))
        sys.exit(2)
