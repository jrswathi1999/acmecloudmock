"""Unit tests for the alert rules in ops/monitor.py, without starting the shop.

The monitor reads and writes logs through ops.common, which uses common.LOGS at call time, so pointing
common.LOGS at a temp folder gives every test its own empty company logs.
"""
import json
from datetime import timedelta

import pytest

from ops import common, contract, monitor


@pytest.fixture(autouse=True)
def logs(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "LOGS", tmp_path)
    return tmp_path


def requests(ok: int, failed: int) -> None:
    for status in [200] * ok + [500] * failed:
        common.log("app", service="shop-api", level="ERROR" if status >= 500 else "INFO", version="a1b2c3d",
                   path="/checkout", status=status, ms=3.0,
                   **({"error": "KeyError: 'PAYMENT_API_URL'", "where": "config.py:6"} if status >= 500 else {}))


def admin_call(ip: str, allowed: bool = True) -> None:
    common.log("audit", key="ADMIN_API_KEY", key_hint="9c21" if allowed else "", ip=ip, action="list_env_vars",
               allowed=allowed)


def ci_runs(failed: int, ok: int = 0) -> None:
    for i, status in enumerate(["failure"] * failed + ["success"] * ok):
        common.log("ci", run=9001 + i, sha="a1b2c3d", status=status, log=["$ pytest -q"], runner="local")


def fired(component: str) -> list:
    return [a for a in monitor.check(quiet=True) if a["component"] == component]


def backdate(stream: str, delta: timedelta) -> None:
    """Move every line of a stream back in time (the rules look at recent windows)."""
    old = (common.now() - delta).isoformat()
    lines = common.read_log(stream)
    (common.LOGS / f"{stream}.jsonl").unlink()
    for line in lines:
        line["ts"] = old
        with open(common.LOGS / f"{stream}.jsonl", "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(line) + "\n")


# --------------------------------------------------------------------------- shop-api

def test_shop_api_fires_above_20_percent_with_5_requests():
    requests(ok=3, failed=2)  # 40% of 5
    alerts = fired("shop-api")
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "critical"
    assert alerts[0]["message"] == "shop-api 5xx error rate 40% (normal under 1%)"


def test_shop_api_quiet_with_only_4_requests():
    requests(ok=0, failed=4)  # 100%, but fewer than 5 requests
    assert fired("shop-api") == []


def test_shop_api_quiet_at_exactly_20_percent():
    requests(ok=4, failed=1)
    assert fired("shop-api") == []


def test_shop_api_ignores_requests_older_than_2_minutes():
    requests(ok=0, failed=10)
    backdate("app", timedelta(minutes=3))
    assert fired("shop-api") == []


def test_shop_api_does_not_repeat_within_2_minutes():
    requests(ok=0, failed=6)
    assert len(fired("shop-api")) == 1
    requests(ok=0, failed=6)
    assert fired("shop-api") == []


def test_shop_api_fires_again_after_2_minutes():
    requests(ok=0, failed=6)
    assert len(fired("shop-api")) == 1
    backdate("alerts", timedelta(minutes=3))
    assert len(fired("shop-api")) == 1


# --------------------------------------------------------------------------- admin-key

def test_admin_key_quiet_for_the_first_ever_ip():
    admin_call("127.0.0.1")
    admin_call("127.0.0.1")
    assert fired("admin-key") == []


def test_admin_key_fires_for_a_new_ip():
    admin_call("127.0.0.1")
    admin_call("203.0.113.50")
    alerts = fired("admin-key")
    assert [a["message"] for a in alerts] == ["ADMIN_API_KEY used from a new IP (203.0.113.50)"]
    assert alerts[0]["severity"] == "critical"


def test_admin_key_fires_only_once_per_ip():
    admin_call("127.0.0.1")
    admin_call("203.0.113.50")
    assert len(fired("admin-key")) == 1
    admin_call("203.0.113.50")
    assert fired("admin-key") == []
    admin_call("203.0.113.77")  # a different new IP still fires
    assert [a["message"] for a in fired("admin-key")] == ["ADMIN_API_KEY used from a new IP (203.0.113.77)"]


def test_admin_key_ignores_refused_calls():
    admin_call("127.0.0.1")
    admin_call("203.0.113.50", allowed=False)
    assert fired("admin-key") == []


def test_admin_key_ignores_use_older_than_10_minutes():
    admin_call("127.0.0.1")
    admin_call("203.0.113.50")
    backdate("audit", timedelta(minutes=11))
    assert fired("admin-key") == []


# --------------------------------------------------------------------------- local-ci

def test_local_ci_fires_at_3_failures_in_10_minutes():
    ci_runs(failed=3, ok=1)
    alerts = fired("local-ci")
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "high"
    assert alerts[0]["message"] == "local-ci: 3 CI runs failed in the last 10 minutes"


def test_local_ci_quiet_at_2_failures():
    ci_runs(failed=2, ok=3)
    assert fired("local-ci") == []


def test_local_ci_ignores_failures_older_than_10_minutes():
    ci_runs(failed=5)
    backdate("ci", timedelta(minutes=11))
    assert fired("local-ci") == []


def test_local_ci_does_not_repeat_within_10_minutes():
    ci_runs(failed=3)
    assert len(fired("local-ci")) == 1
    assert fired("local-ci") == []


# --------------------------------------------------------------------------- output

def test_no_alerts_on_a_quiet_company():
    requests(ok=10, failed=0)
    admin_call("127.0.0.1")
    ci_runs(failed=0, ok=3)
    assert monitor.check(quiet=True) == []


def test_alerts_the_monitor_writes_match_the_contract(logs):
    requests(ok=0, failed=6)
    admin_call("127.0.0.1")
    admin_call("203.0.113.50")
    ci_runs(failed=3)
    assert len(monitor.check(quiet=True)) == 3
    assert contract.validate_dir(logs) == []
