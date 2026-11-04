"""Create a fresh "company" in ./run from this template, then give it some history.

    python -m ops.setup

Re-running wipes ./run and starts over. Template files are never modified.
"""
import shutil
import sys

from ops import common

COPY = ["app", "jobs", "tests", ".github/workflows/ci.yml", "requirements.txt", "pytest.ini", "ops"]

COMPANY_GITIGNORE = """__pycache__/
*.pyc
.pytest_cache/
data/
logs/
prod/
"""

COMPANY_README = """# acme-shop

Acme Cloud's online shop: storefront, checkout, orders and the daily revenue job.

- `app/`: FastAPI service (`uvicorn app.main:app`)
- `jobs/daily_revenue.py`: nightly revenue rollup
- `tests/`: run with `python -m pytest -q`
"""


def build_company() -> None:
    run = common.COMPANY
    template = common.REPO_ROOT
    if run.exists():
        from ops import deploy
        if deploy.stop_server():
            common.say("  stopped the running shop")
        common.rmtree(run)
        common.say(f"  wiped {run}")
    run.mkdir(parents=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "COMPANY")
    for item in COPY:
        src, dst = template / item, run / item
        if src.is_dir():
            shutil.copytree(src, dst, ignore=ignore)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    common.write_text(run / ".gitignore", COMPANY_GITIGNORE)
    common.write_text(run / "README.md", COMPANY_README)
    common.write_text(run / "ops" / "COMPANY", "This copy of ops/ operates on the folder above it.\n")
    common.say(f"  copied {', '.join(COPY)} into {run}")

    common.git("init", "-q", "-b", "main")
    common.git("status", "--porcelain")  # surfaces "dubious ownership" now, not mid-scenario
    common.git("config", "core.autocrlf", "false")
    common.git("config", "commit.gpgsign", "false")
    exclude = run / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with open(exclude, "a", encoding="utf-8", newline="\n") as f:
        f.write("\n# company tooling, not part of the shop's history\nops/\n")
    common.say("  git init -b main (ops/ excluded via .git/info/exclude)")


def summary() -> int:
    authors = sorted(set(common.git("log", "--format=%an").splitlines()))
    commits = int(common.git("rev-list", "--count", "HEAD"))
    missing = [s for s in common.STREAMS if not (common.LOGS / f"{s}.jsonl").exists()]
    status, body = common.http("GET", "/health")
    common.say("")
    common.say("=" * 72)
    common.say(f"acme-shop is up at {common.SHOP_URL}" if status == 200 else f"WARNING: shop not healthy ({status} {body})")
    common.say(f"company repo: {common.COMPANY}")
    common.say(f"commits: {commits} by {', '.join(authors)}")
    common.say(f"logs: {common.LOGS}" + (f" (MISSING: {', '.join(missing)})" if missing else " (all streams present)"))
    common.say("next: python -m ops.scenario break-checkout | break-revenue | attack | fix | reset")
    common.say("=" * 72)
    return 0 if status == 200 and not missing else 1


def main() -> int:
    if common.IS_COMPANY:
        common.say("Run setup from the template repo, not from inside run/.")
        return 2
    from ops import scenario
    try:
        common.say("setup: creating a fresh Acme Cloud company")
        build_company()
        scenario.cmd_init()
        scenario.cmd_normal(2)
    except common.DubiousOwnership as exc:
        common.say("")
        common.say(str(exc))
        return 2
    except common.OpsError as exc:
        common.say("")
        common.say(f"setup failed: {exc}")
        return 1
    return summary()


if __name__ == "__main__":
    sys.exit(main())
