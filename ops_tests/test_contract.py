"""The log contract (ops/contract.py): good records pass, broken ones fail with a useful message."""
import json

import pytest

from ops import contract

TS = "2026-11-04T18:22:05+00:00"

VALID = {
    "ci": {"ts": TS, "run": 9001, "sha": "a1b2c3d", "status": "success", "log": ["$ pytest -q", "3 passed"],
           "runner": "local"},
    "egress": {"ts": TS, "source": "ci-runner", "run": 9004, "method": "POST", "host": "collect.attacker.example.test",
               "bytes_out": 412, "allowed": False},
    "deploys": {"ts": TS, "deploy": "dep-2001", "service": "shop-api", "sha": "a1b2c3d", "previous": None,
                "actor": "release-bot", "status": "live", "health_error": None},
    "app": {"ts": TS, "service": "shop-api", "level": "INFO", "version": "a1b2c3d", "path": "/checkout",
            "status": 200, "ms": 4.2},
    "jobs": {"ts": TS, "job": "daily_revenue", "status": "SUCCESS", "day": "2026-11-04",
             "log": ["read 40 orders"], "rows": 3},
    "audit": {"ts": TS, "key": "ADMIN_API_KEY", "key_hint": "9c21", "ip": "127.0.0.1", "action": "list_env_vars",
              "allowed": True},
    "issues": {"ts": TS, "number": 518, "author": "fast-fixer-42", "account_age_days": 2,
               "title": "CI is flaky on retries", "body": "Steps to reproduce..."},
    "agent": {"ts": TS, "agent": "dev-agent", "action": "read_issue", "issue": 518, "text": "Steps to reproduce..."},
    "alerts": {"ts": TS, "component": "shop-api", "severity": "critical",
               "message": "shop-api 5xx error rate 93% (normal under 1%)"},
}

# More valid shapes that the cross-field rules have to allow.
ALSO_VALID = [
    ("app", {**VALID["app"], "level": "ERROR", "status": 500, "error": "KeyError: 'PAYMENT_API_URL'",
             "where": "config.py:6"}),
    ("audit", {**VALID["audit"], "ip": "203.0.113.50", "action": "create_api_key", "new_key": "backup-ci"}),
    ("audit", {**VALID["audit"], "key_hint": "", "action": "create_api_key", "allowed": False}),
    ("agent", {"ts": TS, "agent": "dev-agent", "action": "push", "branch": "main",
               "note": "pushed straight to main, no pull request"}),
    ("deploys", {**VALID["deploys"], "previous": "dep-2001", "actor": "rollback", "status": "unhealthy",
                 "health_error": "HTTP 500"}),
    ("egress", {**VALID["egress"], "run": None}),
]


def change(stream: str, **fields) -> dict:
    record = dict(VALID[stream])
    for k, v in fields.items():
        if v is DROP:
            record.pop(k)
        else:
            record[k] = v
    return record


DROP = object()

# (stream, broken record, text the problem must mention)
BROKEN = [
    ("ci", change("ci", ts="2026-11-04T18:22:05.123456+00:00"), "ts: expected UTC with seconds"),
    ("ci", change("ci", ts="2026-11-04 18:22:05"), "ts: expected UTC with seconds"),
    ("app", change("app", ts="2026-11-04T18:22:05Z"), "ts: expected UTC with seconds"),
    ("ci", change("ci", run=True), "run: expected int, got bool"),
    ("ci", change("ci", run="9001"), "run: expected int, got str"),
    ("ci", change("ci", run=42), "run: expected >= 9001"),
    ("ci", change("ci", status="passed"), "status: expected one of success, failure"),
    ("ci", change("ci", sha="a1b2c3d4e5"), "sha: expected a 7-character commit sha"),
    ("ci", change("ci", log="3 passed"), "log: expected a list of str"),
    ("ci", change("ci", runner="github"), "runner: expected one of local"),
    ("deploys", change("deploys", status=DROP), "missing field 'status'"),
    ("deploys", change("deploys", deploy="2001"), "deploy: expected dep-<number>"),
    ("deploys", change("deploys", actor="priya"), "actor: expected one of release-bot, rollback"),
    ("egress", change("egress", allowed="false"), "allowed: expected bool, got str"),
    ("egress", change("egress", bytes_out=1.5), "bytes_out: expected int, got float"),
    ("app", change("app", level="ERROR", status=500), "missing field 'error'"),
    ("app", change("app", status=True), "status: expected int, got bool"),
    ("app", change("app", error="boom"), "only allowed when level is ERROR"),
    ("jobs", change("jobs", status="OK"), "status: expected one of SUCCESS, SUCCESS_WITH_WARNINGS, FAILED"),
    ("audit", change("audit", action="create_api_key"), "missing field 'new_key'"),
    ("audit", change("audit", new_key="backup-ci"), "only allowed when action is create_api_key"),
    ("audit", change("audit", ip="not-an-ip"), "ip: expected an IP address"),
    ("agent", change("agent", text=DROP), "missing field 'text' (required when action is read_issue)"),
    ("alerts", change("alerts", component="checkout"), "component: expected one of shop-api"),
    ("alerts", change("alerts", severity="medium"), "severity: expected one of critical, high"),
    ("ci", {**VALID["ci"], "runer": "local"}, "unexpected field 'runer'"),
    ("ci", ["not", "an", "object"], "expected a JSON object, got list"),
    ("nope", VALID["ci"], "unknown stream 'nope'"),
]


@pytest.mark.parametrize("stream", list(VALID))
def test_valid_record_passes(stream):
    assert contract.validate(stream, VALID[stream]) == []


@pytest.mark.parametrize("stream,record", ALSO_VALID, ids=lambda x: x if isinstance(x, str) else "")
def test_other_valid_shapes_pass(stream, record):
    assert contract.validate(stream, record) == []


def test_contract_covers_every_stream():
    from ops import common
    assert set(contract.CONTRACT) == set(common.STREAMS) == set(VALID)


@pytest.mark.parametrize("stream,record,expect", BROKEN, ids=[b[2][:40] for b in BROKEN])
def test_broken_record_fails_with_useful_message(stream, record, expect):
    problems = contract.validate(stream, record)
    assert problems, f"{stream} record should fail: {record}"
    assert any(expect in p for p in problems), problems


def write(path, name, lines):
    with open(path / name, "w", encoding="utf-8", newline="\n") as f:
        for line in lines:
            f.write((line if isinstance(line, str) else json.dumps(line)) + "\n")


def test_validate_dir_reports_file_and_line(tmp_path):
    for stream, record in VALID.items():
        write(tmp_path, f"{stream}.jsonl", [record])
    write(tmp_path, "ci.jsonl", [VALID["ci"], change("ci", run="9002"), "{not json"])
    problems = contract.validate_dir(tmp_path)
    assert problems == [
        "ci.jsonl line 2: run: expected int, got str (\"9002\")",
        "ci.jsonl line 3: not valid JSON (Expecting property name enclosed in double quotes)",
    ]


def test_validate_dir_flags_unknown_files_and_skips_blank_lines(tmp_path):
    write(tmp_path, "ci.jsonl", [VALID["ci"], "", VALID["ci"]])
    write(tmp_path, "metrics.jsonl", [{"ts": TS}])
    assert contract.validate_dir(tmp_path) == ["metrics.jsonl: not a known stream (known: ci, egress, deploys, app, "
                                               "jobs, audit, issues, agent, alerts)"]


def test_cli_exit_codes(tmp_path, capsys):
    write(tmp_path, "ci.jsonl", [VALID["ci"], VALID["ci"]])
    assert contract.main([str(tmp_path)]) == 0
    assert "all 2 lines match the contract" in capsys.readouterr().out
    write(tmp_path, "ci.jsonl", [change("ci", run="9001")])
    assert contract.main([str(tmp_path)]) == 1
    assert "ci.jsonl line 1: run: expected int" in capsys.readouterr().out
