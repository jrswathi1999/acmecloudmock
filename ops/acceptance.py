"""Acceptance checks: run every scenario for real and verify the results. Takes a few minutes.

    python -m ops.acceptance

Run it from the template repo before opening a pull request. It rebuilds ./run from scratch.
"""
import hashlib
import subprocess
import sys

from ops import common

RESULTS = []
TEMPLATE_PATHS = ["app", "jobs", "tests", ".github", "requirements.txt", "pytest.ini"]


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok))
    common.say(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    return ok


def ops(*args) -> int:
    common.say(f"\n>>> python -m {' '.join(args)}")
    proc = subprocess.run([sys.executable, "-m", *args], cwd=str(common.REPO_ROOT), env=common.python_env(),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.stdout.decode("utf-8", "replace")
    tail = [line for line in out.splitlines() if line.strip() and not line.startswith("====")][-4:]
    for line in tail:
        common.say("    | " + line)
    return proc.returncode


def template_hash() -> str:
    h = hashlib.sha256()
    for rel in TEMPLATE_PATHS:
        root = common.REPO_ROOT / rel
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        for f in files:
            h.update(str(f.relative_to(common.REPO_ROOT)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def checkout_status() -> int:
    return common.http("POST", "/checkout", {"product_id": 1, "qty": 1, "region": "US"})[0]


def alert_since(start: int, component: str) -> bool:
    return any(a.get("component") == component for a in common.read_log("alerts")[start:])


def main() -> int:
    if common.IS_COMPANY:
        common.say("Run acceptance from the template repo.")
        return 2
    before = template_hash()

    common.say("1. template tests")
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=str(common.REPO_ROOT), capture_output=True)
    check("python -m pytest -q passes in the template", proc.returncode == 0,
          proc.stdout.decode("utf-8", "replace")[-300:])

    common.say("2. setup")
    code = ops("ops.setup")
    if not check("setup exits 0", code == 0, "if this says 'dubious ownership', run the printed git config command"):
        return report()
    check("shop healthy on :8700", common.http("GET", "/health")[0] == 200)
    check(">= 3 commits", int(common.git("rev-list", "--count", "HEAD")) >= 3)
    check(">= 2 authors", len(set(common.git("log", "--format=%an").splitlines())) >= 2)
    check("every log stream exists", all((common.LOGS / f"{s}.jsonl").exists() for s in common.STREAMS))

    common.say("3. break-checkout + fix")
    start = len(common.read_log("alerts"))
    check("break-checkout exits 0", ops("ops.scenario", "break-checkout", "--red-herring") == 0)
    check("POST /checkout returns 500", checkout_status() == 500)
    check("app log has KeyError: 'PAYMENT_API_URL'",
          any(e.get("error") == "KeyError: 'PAYMENT_API_URL'" for e in common.read_log("app")))
    check("shop-api alert raised", alert_since(start, "shop-api"))
    check("fix exits 0", ops("ops.scenario", "fix") == 0)
    check("POST /checkout works again", checkout_status() == 200)

    common.say("4. attack + break-revenue back to back, then fix twice")
    start = len(common.read_log("alerts"))
    check("break-revenue exits 0", ops("ops.scenario", "break-revenue") == 0)
    check("revenue_daily alert raised", alert_since(start, "revenue_daily"))
    check("attack exits 0", ops("ops.scenario", "attack") == 0)
    egress = common.read_log("egress")
    check("egress has a blocked POST to collect.attacker.example.test with bytes_out > 0",
          any(e["host"] == "collect.attacker.example.test" and e["method"] == "POST"
              and e["bytes_out"] > 0 and e["allowed"] is False for e in egress))
    check("nothing was allowed out", all(e["allowed"] is False for e in egress))
    check("audit log has 203.0.113.50", any(e.get("ip") == "203.0.113.50" for e in common.read_log("audit")))
    check("admin-key alert raised", alert_since(start, "admin-key"))
    check("fix (attack) exits 0", ops("ops.scenario", "fix") == 0)
    check("fix (revenue) exits 0", ops("ops.scenario", "fix") == 0)
    jobs = common.read_log("jobs")
    check("revenue job back to SUCCESS", bool(jobs) and jobs[-1]["status"] == "SUCCESS")
    check("checkout works after both fixes", checkout_status() == 200)

    common.say("5. vendor-outage")
    start = len(common.read_log("alerts"))
    check("vendor-outage exits 0", ops("ops.scenario", "vendor-outage") == 0)
    check("local-ci alert raised", alert_since(start, "local-ci"))

    common.say("6. reset and setup recover")
    check("reset exits 0", ops("ops.scenario", "reset") == 0)
    check("after reset: one commit, shop healthy",
          common.git("rev-list", "--count", "HEAD") == "1" and common.http("GET", "/health")[0] == 200)
    check("setup again exits 0", ops("ops.setup") == 0)
    check("after setup: shop healthy", common.http("GET", "/health")[0] == 200)

    check("template files were not modified", template_hash() == before)
    return report()


def report() -> int:
    failed = [name for name, ok in RESULTS if not ok]
    common.say("")
    common.say(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    for name in failed:
        common.say(f"  FAILED: {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except common.OpsError as exc:
        common.say(str(exc))
        sys.exit(2)
