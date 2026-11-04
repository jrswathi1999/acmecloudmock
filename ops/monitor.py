"""Monitoring rules. Writes alerts to logs/alerts.jsonl.

    python -m ops.monitor           check once
    python -m ops.monitor --watch   check every 10 seconds

The revenue_daily alert is raised by the job itself (jobs/daily_revenue.py).
"""
import sys
import time
from datetime import timedelta

from ops import common

ERROR_WINDOW = timedelta(minutes=2)
ADMIN_WINDOW = timedelta(minutes=10)
CI_WINDOW = timedelta(minutes=10)


def _raise(component: str, severity: str, message: str) -> dict:
    return common.log("alerts", component=component, severity=severity, message=message)


def _shop_api_rule(ref, alerts) -> list:
    recent = common.since(common.read_log("app"), ERROR_WINDOW, ref)
    if len(recent) < 5:
        return []
    errors = sum(1 for e in recent if int(e.get("status", 0)) >= 500)
    rate = errors / len(recent)
    if rate <= 0.20:
        return []
    if any(a.get("component") == "shop-api" for a in common.since(alerts, ERROR_WINDOW, ref)):
        return []
    return [_raise("shop-api", "critical", f"shop-api 5xx error rate {round(rate * 100)}% (normal under 1%)")]


def _admin_key_rule(ref, alerts) -> list:
    seen = set()
    new_ips = []
    for entry in common.read_log("audit"):
        if not entry.get("allowed"):
            continue
        ip = entry.get("ip")
        recent = ref - common.parse_ts(entry["ts"]) <= ADMIN_WINDOW
        if seen and ip not in seen and recent and ip not in new_ips:
            new_ips.append(ip)
        seen.add(ip)
    out = []
    for ip in new_ips:
        message = f"ADMIN_API_KEY used from a new IP ({ip})"
        if not any(a.get("message") == message for a in alerts):
            out.append(_raise("admin-key", "critical", message))
    return out


def _local_ci_rule(ref, alerts) -> list:
    failed = [e for e in common.since(common.read_log("ci"), CI_WINDOW, ref) if e.get("status") == "failure"]
    if len(failed) < 3:
        return []
    if any(a.get("component") == "local-ci" for a in common.since(alerts, CI_WINDOW, ref)):
        return []
    return [_raise("local-ci", "high", f"local-ci: {len(failed)} CI runs failed in the last 10 minutes")]


def check(quiet: bool = False) -> list:
    ref = common.now()
    alerts = common.read_log("alerts")
    new = _shop_api_rule(ref, alerts) + _admin_key_rule(ref, alerts) + _local_ci_rule(ref, alerts)
    if not quiet:
        for alert in new:
            common.say(f"  monitor: ALERT [{alert['severity']}] {alert['component']}: {alert['message']}")
        if not new:
            common.say("  monitor: no new alerts")
    return new


def main(argv) -> int:
    common.require_company()
    if "--watch" in argv:
        common.say("monitor: checking every 10s (Ctrl+C to stop)")
        try:
            while True:
                new = check(quiet=True)
                for alert in new:
                    common.say(f"{alert['ts']} ALERT [{alert['severity']}] {alert['component']}: {alert['message']}")
                time.sleep(10)
        except KeyboardInterrupt:
            return 0
    check()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except common.OpsError as exc:
        common.say(str(exc))
        sys.exit(2)
