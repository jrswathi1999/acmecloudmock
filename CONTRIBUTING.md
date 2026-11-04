# Contributing to acme-shop

Thanks for helping. This repo is the test subject for Narc, so the bar is: **every scenario still breaks the way
Narc expects, and still runs on Windows, macOS and Linux.**

## Workflow

1. **Never push to `main`.** Create a branch: `git checkout -b <your-name>/<short-topic>`.
2. Set up once: create a venv and run `pip install -r requirements.txt` (see the README).
3. Make your change in the **template** (`app/`, `jobs/`, `tests/`, `ops/`, …), never in `run/`. `run/` is
   generated and gitignored.
4. Before you push, run:
   ```
   python -m pytest -q
   python -m pytest ops_tests -q   # tests for the tooling: log contract and monitor rules
   python -m ops.acceptance        # ~3 min, rebuilds run/, must end with "N/N checks passed"
   ```
5. Open a PR and fill in the template. GitHub Actions runs the acceptance suite on Windows, macOS and Linux.
6. Get **one approving review** (two for the high-risk areas below). Then squash-merge.

Keep each PR small, one topic per PR.

## Rules every PR must follow

- **Cross-platform:** no `shell=True`, no pipes or bash-only commands. Use `subprocess.run([...])` with lists,
  `os.pathsep`, `pathlib`, and `encoding="utf-8"` on every text file. Custom subprocess `env` starts from a copy of
  `os.environ`. Stop processes with `common.stop_pid`.
- **Synthetic only:** secrets contain `synth`, hosts are `*.example.test`, and attacker IPs come from `203.0.113.0/24`.
  Nothing may leave the machine. Outbound traffic from CI must go through the egress proxy.
- **Real, not faked:** never write a log line to pretend something happened. Only `issues` and `agent` are staged.
- **Stdlib plus** `fastapi`, `uvicorn`, `httpx`, `pytest` and `pyyaml`. Add nothing else without team agreement.
- **Don't fix the deliberate weaknesses** (README → "Known weaknesses (on purpose)"). They are the demo.

## PRs that need extra review before merging

These areas can silently break Narc. They need **two reviews, one of them from whoever owns Narc's parsers**,
plus a green acceptance run on all three operating systems:

| area | why it's risky |
|---|---|
| Log fields or formats (`app/logs.py`, `ops/common.py: log`, any `log(...)` / `logs.write(...)` call) | Narc parses fields by name. A renamed field or a changed `ts` format breaks it with no error. |
| Alert messages and monitor rules (`ops/monitor.py`, the alert in `jobs/daily_revenue.py`) | Narc matches the message text, components and severities. |
| Scenario command names or what they commit (`ops/scenario.py`) | Narc's dashboard buttons call these names, and each verdict depends on the exact author, commit message and diff. |
| `app/config.py`, the `orders` schema in `app/db.py`, `tests/test_app.py` | The planted mistakes edit these by exact text, and line numbers matter (`config.py:6`). |
| CI runner, egress proxy, deploy (`ops/ci_local.py`, `ops/egress_proxy.py`, `ops/deploy.py`) | These keep the attack contained and control process handling on Windows. |
| `.github/workflows/ci.yml` | It's the company's real build file. The attack scenario edits it by exact text. |

Everything else (storefront look, dashboard, docs, new taglines, extra tests) needs one review.

## Reviewer checklist

- [ ] The diff touches only the template. Nothing under `run/`, `.venv/`, `logs/` or `data/` is committed.
- [ ] Acceptance passes on Windows, macOS and Linux (check the PR's Actions tab).
- [ ] If logs, alerts or scenarios changed, Narc was re-run against `run/` and still gives the expected verdicts.
- [ ] No real-looking secrets, no real domains, nothing that can reach the internet.
- [ ] README updated if behaviour changed.
