"""Deploys: unpack a commit into prod/releases/<sha> and (re)start the shop from it.

    python -m ops.deploy <sha>             deploy a commit
    python -m ops.deploy rollback [<sha>]  redeploy the previous live release (or a given one)
    python -m ops.deploy stop              stop the shop
    python -m ops.deploy status            show what is live
"""
import json
import sys
import time

from ops import common

STATE = common.PROD / "state.json"
RELEASES = common.PROD / "releases"
HEALTH_TIMEOUT = 12.0


def load_state() -> dict:
    try:
        return json.loads(common.read_text(STATE))
    except (OSError, ValueError):
        return {"live": None, "history": []}


def save_state(state: dict) -> None:
    common.write_text(STATE, json.dumps(state, indent=2))


def next_deploy_id() -> str:
    numbers = []
    for entry in common.read_log("deploys"):
        try:
            numbers.append(int(str(entry.get("deploy", "")).split("-")[1]))
        except (IndexError, ValueError):
            pass
    return f"dep-{max(numbers) + 1 if numbers else 2001}"


def server_env(sha: str) -> dict:
    """The server's settings. They live here, on the 'server', not in the code."""
    env = common.python_env(
        ACME_VERSION=sha,
        ACME_LOG_DIR=common.LOGS,
        ACME_DB=common.DB_PATH,
        **common.SERVER_SETTINGS,
    )
    env.pop("PAYMENT_API_URL", None)
    return env


def live_release():
    live = load_state().get("live")
    if live and (RELEASES / live["sha"]).exists():
        return RELEASES / live["sha"]
    return None


def stop_server() -> bool:
    """Stop the shop if it's running. Returns True if something was stopped."""
    state = load_state()
    live = state.get("live") or {}
    pid = live.get("pid")
    # Only kill the saved PID while the port is actually serving, so a stale PID
    # (e.g. after a reboot) can never take down an unrelated process.
    if pid and common.port_open(common.SHOP_PORT):
        common.stop_pid(pid)
        deadline = time.time() + 10
        while time.time() < deadline and common.port_open(common.SHOP_PORT):
            time.sleep(0.2)
        if live:
            live["pid"] = None
            save_state(state)
        return True
    return False


def _wait_healthy(proc, sha: str):
    deadline = time.time() + HEALTH_TIMEOUT
    last = "no response"
    while time.time() < deadline:
        if proc.poll() is not None:
            return False, f"server exited with code {proc.returncode} (see prod/server.log)"
        status, body = common.http("GET", "/health", timeout=2)
        if status == 200 and isinstance(body, dict):
            if body.get("version") == sha:
                return True, None
            last = f"/health reports version {body.get('version')}, expected {sha}"
        elif status:
            last = f"/health returned HTTP {status}"
        else:
            last = f"connection failed: {body}"
        time.sleep(0.3)
    return False, f"not healthy after {HEALTH_TIMEOUT:.0f}s: {last}"


def deploy(sha: str, actor: str = "release-bot") -> dict:
    sha = common.short_sha(sha)
    deploy_id = next_deploy_id()
    state = load_state()
    previous = (state.get("live") or {}).get("deploy")
    release = RELEASES / sha
    if not release.exists():
        common.unpack(sha, release)
    stop_server()
    state = load_state()
    if common.port_open(common.SHOP_PORT):
        common.say(f"  warning: something else is listening on port {common.SHOP_PORT}")
    proc = common.spawn_detached(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", common.SHOP_HOST, "--port", str(common.SHOP_PORT), "--log-level", "warning"],
        cwd=release,
        env=server_env(sha),
        log_path=common.PROD / "server.log",
    )
    healthy, error = _wait_healthy(proc, sha)
    status = "live" if healthy else "unhealthy"
    common.log("deploys", deploy=deploy_id, service="shop-api", sha=sha, previous=previous,
               actor=actor, status=status, health_error=error)
    state["live"] = {"deploy": deploy_id, "sha": sha, "pid": proc.pid}
    state.setdefault("history", []).append({"deploy": deploy_id, "sha": sha, "status": status, "actor": actor})
    save_state(state)
    common.say(f"  deploy {deploy_id}: {sha} {status.upper()} (actor {actor}, previous {previous})")
    if healthy:
        # Post-deploy smoke check with the shared admin key, from 127.0.0.1.
        check, _ = common.http("GET", "/admin/env", headers={"x-api-key": common.ADMIN_KEY})
        common.say(f"  post-deploy admin check: HTTP {check}")
    else:
        common.say(f"  health error: {error}")
    return {"deploy": deploy_id, "sha": sha, "status": status, "previous": previous, "health_error": error}


def rollback(to_sha: str = None) -> dict:
    state = load_state()
    current = (state.get("live") or {}).get("sha")
    if to_sha:
        target = common.short_sha(to_sha)
    else:
        candidates = [h["sha"] for h in reversed(state.get("history", []))
                      if h["status"] == "live" and h["sha"] != current]
        if not candidates:
            raise common.OpsError("rollback: there is no earlier live release to go back to")
        target = candidates[0]
    common.say(f"  rollback: {current} -> {target}")
    return deploy(target, actor="rollback")


def main(argv) -> int:
    common.require_company()
    if not argv:
        common.say(__doc__)
        return 2
    if argv[0] == "rollback":
        result = rollback(argv[1] if len(argv) > 1 else None)
    elif argv[0] == "stop":
        common.say("shop stopped" if stop_server() else "shop was not running")
        return 0
    elif argv[0] == "status":
        common.say(json.dumps(load_state().get("live"), indent=2))
        return 0
    else:
        result = deploy(argv[0])
    return 0 if result["status"] == "live" else 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except common.OpsError as exc:
        common.say(str(exc))
        sys.exit(2)
