"""Log contract: check that every line in logs/*.jsonl has the fields, types and values Narc parses.

    python -m ops.contract [logs_dir]      default: the company's logs (common.LOGS)

Prints each problem as "<stream>.jsonl line <n>: <problem>" and exits 1, or prints
"all N lines match the contract" and exits 0.

The contract is the README table "Logs (the contract Narc parses)", written down as data. Narc reads these fields
by name, so a renamed field, a wrong type or a different timestamp format would quietly give a wrong verdict.
Unexpected extra fields are reported too: a rename usually shows up as one missing field plus one unexpected one.
"""
import ipaddress
import json
import re
import sys
from pathlib import Path

from ops import common

TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")  # UTC, seconds, no microseconds
SHA = re.compile(r"^[0-9a-f]{7}$")
DEPLOY = re.compile(r"^dep-\d+$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------- field checks
# Each check takes the value and returns None (fine) or a short description of what's wrong.

def _show(value) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 40 else text[:37] + "..."


def _type_name(value) -> str:
    return "null" if value is None else type(value).__name__


def is_int(value):
    # bool is a subclass of int in Python: True must not pass as 1
    if isinstance(value, bool) or not isinstance(value, int):
        return f"expected int, got {_type_name(value)} ({_show(value)})"
    return None


def is_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"expected a number, got {_type_name(value)} ({_show(value)})"
    return None


def is_str(value):
    return None if isinstance(value, str) else f"expected str, got {_type_name(value)} ({_show(value)})"


def is_bool(value):
    return None if isinstance(value, bool) else f"expected bool, got {_type_name(value)} ({_show(value)})"


def is_str_list(value):
    if not isinstance(value, list):
        return f"expected a list of str, got {_type_name(value)} ({_show(value)})"
    bad = [i for i, item in enumerate(value) if not isinstance(item, str)]
    return f"expected a list of str, item {bad[0]} is {_type_name(value[bad[0]])}" if bad else None


def nullable(check):
    def inner(value):
        return None if value is None else check(value)
    return inner


def one_of(*allowed):
    def inner(value):
        return None if value in allowed else f"expected one of {', '.join(map(str, allowed))}, got {_show(value)}"
    return inner


def matches(pattern: re.Pattern, what: str):
    def inner(value):
        if not isinstance(value, str):
            return f"expected str ({what}), got {_type_name(value)} ({_show(value)})"
        return None if pattern.match(value) else f"expected {what}, got {_show(value)}"
    return inner


def all_of(*checks):
    def inner(value):
        for check in checks:
            problem = check(value)
            if problem:
                return problem
        return None
    return inner


def at_least(minimum: int):
    return all_of(is_int, lambda v: None if v >= minimum else f"expected >= {minimum}, got {v}")


def non_empty_str(value):
    return is_str(value) or (None if value.strip() else "expected a non-empty str")


def ip_address(value):
    if not isinstance(value, str):
        return f"expected an IP address, got {_type_name(value)} ({_show(value)})"
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return f"expected an IP address, got {_show(value)}"
    return None


# --------------------------------------------------------------------------- the contract, as data
# stream -> (required fields, optional fields). Cross-field rules live in RULES below.

CONTRACT = {
    "ci": ({
        "run": at_least(9001),
        "sha": matches(SHA, "a 7-character commit sha"),
        "status": one_of("success", "failure"),
        "log": is_str_list,
        "runner": one_of("local"),
    }, {}),
    "egress": ({
        "source": one_of("ci-runner"),
        "run": nullable(is_int),
        "method": non_empty_str,
        "host": is_str,
        "bytes_out": all_of(is_int, lambda v: None if v >= 0 else f"expected >= 0, got {v}"),
        "allowed": is_bool,
    }, {}),
    "deploys": ({
        "deploy": matches(DEPLOY, "dep-<number>"),
        "service": one_of("shop-api"),
        "sha": matches(SHA, "a 7-character commit sha"),
        "previous": nullable(matches(DEPLOY, "dep-<number> or null")),
        "actor": one_of("release-bot", "rollback"),
        "status": one_of("live", "unhealthy"),
        "health_error": nullable(is_str),
    }, {}),
    "app": ({
        "service": one_of("shop-api"),
        "level": one_of("INFO", "WARN", "ERROR"),
        "version": non_empty_str,
        "path": matches(re.compile(r"^/"), "a path starting with /"),
        "status": all_of(is_int, lambda v: None if 100 <= v <= 599 else f"expected an HTTP status, got {v}"),
        "ms": is_number,
    }, {
        "error": non_empty_str,
        "where": non_empty_str,
    }),
    "jobs": ({
        "job": one_of("daily_revenue"),
        "status": one_of("SUCCESS", "SUCCESS_WITH_WARNINGS", "FAILED"),
        "day": matches(DAY, "a YYYY-MM-DD date"),
        "log": is_str_list,
        "rows": all_of(is_int, lambda v: None if v >= 0 else f"expected >= 0, got {v}"),
    }, {}),
    "audit": ({
        "key": one_of("ADMIN_API_KEY"),
        "key_hint": all_of(is_str, lambda v: None if len(v) <= 4 else f"expected at most 4 characters, got {len(v)}"),
        "ip": ip_address,
        "action": one_of("list_env_vars", "create_api_key"),
        "allowed": is_bool,
    }, {
        "new_key": non_empty_str,
    }),
    "issues": ({
        "number": is_int,
        "author": non_empty_str,
        "account_age_days": all_of(is_int, lambda v: None if v >= 0 else f"expected >= 0, got {v}"),
        "title": is_str,
        "body": is_str,
    }, {}),
    "agent": ({
        "agent": one_of("dev-agent"),
        "action": one_of("read_issue", "push"),
    }, {
        "issue": is_int,
        "text": is_str,
        "branch": non_empty_str,
        "note": is_str,
    }),
    "alerts": ({
        "component": one_of("shop-api", "revenue_daily", "admin-key", "local-ci"),
        "severity": one_of("critical", "high"),
        "message": non_empty_str,
    }, {}),
}


def _app_rule(r: dict) -> list:
    crashed = r.get("level") == "ERROR" and isinstance(r.get("status"), int) and r["status"] >= 500
    if crashed:
        return [f"missing field '{f}' (required when level is ERROR and status >= 500)"
                for f in ("error", "where") if f not in r]
    return [f"field '{f}' is only allowed when level is ERROR and status >= 500" for f in ("error", "where") if f in r]


def _audit_rule(r: dict) -> list:
    minted = r.get("action") == "create_api_key" and r.get("allowed") is True
    if minted and "new_key" not in r:
        return ["missing field 'new_key' (required when action is create_api_key and allowed is true)"]
    if not minted and "new_key" in r:
        return ["field 'new_key' is only allowed when action is create_api_key and allowed is true"]
    return []


def _agent_rule(r: dict) -> list:
    needs = {"read_issue": ("issue", "text"), "push": ("branch", "note")}.get(r.get("action"), ())
    others = {"issue", "text", "branch", "note"} - set(needs)
    return ([f"missing field '{f}' (required when action is {r['action']})" for f in needs if f not in r]
            + [f"field '{f}' is not allowed when action is {r.get('action')}" for f in sorted(others) if f in r])


RULES = {"app": _app_rule, "audit": _audit_rule, "agent": _agent_rule}


# --------------------------------------------------------------------------- validation

def validate(stream: str, record) -> list:
    """Problems with one record of `stream` ([] if it matches the contract)."""
    if stream not in CONTRACT:
        return [f"unknown stream '{stream}' (known: {', '.join(CONTRACT)})"]
    if not isinstance(record, dict):
        return [f"expected a JSON object, got {_type_name(record)}"]
    required, optional = CONTRACT[stream]
    problems = []
    if "ts" not in record:
        problems.append("missing field 'ts'")
    elif not isinstance(record["ts"], str) or not TS.match(record["ts"]):
        problems.append(f"ts: expected UTC with seconds like 2026-11-04T18:22:05+00:00, got {_show(record['ts'])}")
    for name, check in required.items():
        if name not in record:
            problems.append(f"missing field '{name}'")
            continue
        problem = check(record[name])
        if problem:
            problems.append(f"{name}: {problem}")
    for name, check in optional.items():
        if name in record:
            problem = check(record[name])
            if problem:
                problems.append(f"{name}: {problem}")
    known = {"ts", *required, *optional}
    problems += [f"unexpected field '{name}'" for name in record if name not in known]
    if stream in RULES:
        problems += RULES[stream](record)
    return problems


def validate_dir(path=None) -> list:
    """Problems in every *.jsonl file under `path`, as '<stream>.jsonl line <n>: <problem>'."""
    problems, _ = _check_dir(Path(path) if path is not None else common.LOGS)
    return problems


def _check_dir(path: Path):
    problems, lines = [], 0
    if not path.is_dir():
        return [f"{path}: no such directory"], 0
    for file in sorted(path.glob("*.jsonl")):
        stream = file.stem
        if stream not in CONTRACT:
            problems.append(f"{file.name}: not a known stream (known: {', '.join(CONTRACT)})")
            continue
        with open(file, encoding="utf-8") as f:
            for n, raw in enumerate(f, 1):
                if not raw.strip():
                    continue
                lines += 1
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError as exc:
                    problems.append(f"{file.name} line {n}: not valid JSON ({exc.msg})")
                    continue
                problems += [f"{file.name} line {n}: {p}" for p in validate(stream, record)]
    return problems, lines


def main(argv) -> int:
    path = Path(argv[0]) if argv else common.LOGS
    problems, lines = _check_dir(path)
    for p in problems:
        common.say(p)
    if problems:
        common.say(f"{len(problems)} problem{'s' if len(problems) != 1 else ''} in {path}")
        return 1
    common.say(f"all {lines} lines match the contract")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
