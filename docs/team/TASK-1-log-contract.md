# Task 1: log-contract checker and monitor-rule tests

> **For Claude:** you're helping a teammate on the acme-shop repo. Do the steps in order. Ask the human before
> pushing or opening the PR. Don't change any file outside the "Files you may change" list without asking.

## Background (read first)

acme-shop is a small pretend company ("Acme Cloud") that breaks on purpose, so our hackathon project **Narc** can
investigate it. Narc reads the company's git history and the JSON-lines logs in `run/logs/*.jsonl`, then decides
whether an incident was our bad change, a vendor outage, or an attack.

**Narc parses log fields by name.** If any log line drifts from the contract (a missing field, a wrong type, a
different timestamp format), Narc can quietly give a wrong verdict. Right now nothing checks the contract
automatically. Your job is to add that safety net, plus unit tests for the alert rules.

Read these before you start:
- `README.md`: the sections "Logs (the contract Narc parses)" and "Monitoring rules"
- `CONTRIBUTING.md`: the rules every PR must follow
- `ops/common.py` (`log`, `read_log`, `LOGS`, `STREAMS`), `ops/monitor.py`, `ops/acceptance.py`

## Setup

```
git clone <repo url> acme-shop && cd acme-shop
git checkout -b <your-name>/log-contract
```
Windows (PowerShell):
```
py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt
```
macOS / Linux:
```
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```
Then check that everything works before you change anything:
```
python -m pytest -q
python -m ops.setup          # if it prints a "safe.directory" command, run that command once, then re-run
python -m ops.acceptance     # ~3 minutes, must end with "30/30 checks passed"
```

## Files you may change

- **new** `ops/contract.py`
- **new** `ops_tests/` (folder with `__init__.py`, `test_contract.py`, `test_monitor.py`)
- `ops/acceptance.py`: add checks only, don't remove any
- `.github/workflows/acceptance.yml`: add one step
- `README.md` / `CONTRIBUTING.md`: one or two lines documenting the new command

**Do not touch:** `app/`, `jobs/`, `tests/`, `.github/workflows/ci.yml`, `ops/scenario.py`. Teammate 2 is working in
`ops/scenario.py`. The other paths are edited by the scenarios by exact text, so changes there break the demo.

## Step 1: `ops/contract.py`

A validator for every stream in the README's log table. Requirements:

1. Define the contract as data: for each stream, the required fields with their types and, where the README gives
   them, the allowed values. For example:
   - `ci.status` ∈ {`success`, `failure`}, `ci.run` is an int, `ci.sha` is 7 characters, `ci.log` is a list of str,
     `ci.runner == "local"`
   - `deploys.deploy` matches `dep-\d+`, `deploys.actor` ∈ {`release-bot`, `rollback`}, `deploys.status` ∈ {`live`, `unhealthy`},
     `deploys.previous` is a str or null
   - `app.status` is an int. When `level == "ERROR"` and `status >= 500`, `error` and `where` must be present.
   - `jobs.status` ∈ {`SUCCESS`, `SUCCESS_WITH_WARNINGS`, `FAILED`}
   - `audit.action` ∈ {`list_env_vars`, `create_api_key`}. `new_key` is present only when the action is `create_api_key` **and** `allowed` is true.
   - `alerts.component` ∈ {`shop-api`, `revenue_daily`, `admin-key`, `local-ci`}, `alerts.severity` ∈ {`critical`, `high`}
   - `egress.source == "ci-runner"`, `egress.bytes_out` is an int, `egress.allowed` is a bool
   - Every line: valid JSON, and `ts` matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$` (UTC, seconds, no microseconds).
2. `validate(stream, record) -> list[str]` returns the problems for one record. `validate_dir(path) -> list[str]`
   checks every `*.jsonl` file and reports problems as `"<stream>.jsonl line <n>: <problem>"`.
3. CLI: `python -m ops.contract [logs_dir]` (default `common.LOGS`) prints the problems, or
   `all N lines match the contract`. Exit code 1 if there are problems, otherwise 0.
4. Stdlib only. Open files with `encoding="utf-8"` and use `pathlib`.

**Note on bools:** in Python, `isinstance(True, int)` is True. Make sure an `int` field rejects bools.

## Step 2: tests in `ops_tests/`

These tests are for the tooling, so they must **not** live in `tests/`. `tests/` is copied into the pretend
company and runs in its CI. Run them with `python -m pytest ops_tests -q`.

- `test_contract.py`: one valid example record per stream passes, and at least 8 broken records fail with a useful
  message (wrong ts format, missing field, bool where an int belongs, unknown status, and so on).
- `test_monitor.py`: unit-test each rule in `ops/monitor.py` without starting the shop:
  - monkeypatch `ops.common.LOGS` to `tmp_path` (the monitor reads logs through `common.read_log`, which uses
    `common.LOGS` at call time);
  - write fake `app.jsonl` / `audit.jsonl` / `ci.jsonl` lines with fresh `ts` values;
  - test cases:
    - shop-api fires at >20% 5xx with ≥5 requests;
    - shop-api doesn't fire with 4 requests, or at exactly 20%;
    - shop-api doesn't repeat within 2 minutes;
    - admin-key fires for a new IP but not for the first-ever IP (127.0.0.1 baseline), and only once per IP;
    - local-ci fires at 3 failures in 10 minutes but not at 2.

## Step 3: wire it in

1. `ops/acceptance.py`: at the end of `main()` (before `template files were not modified`), add
   `check("every log line matches the contract", ...)` using `contract.validate_dir(common.LOGS)`. Put the first
   few problems in the detail.
   Also add this once, after step 4 (the attack): run the contract check right then. That's the point where the
   logs hold every stream.
2. `.github/workflows/acceptance.yml`: add `- run: python -m pytest ops_tests -q` after the `python -m pytest -q` step.
3. README "Other commands" table: add a row for `python -m ops.contract`.

## Step 4: prove it

```
python -m pytest -q
python -m pytest ops_tests -q
python -m ops.acceptance         # must end with "32/32 checks passed" (or however many you added)
```
Then break something on purpose to make sure the checker catches it. Temporarily edit `run/logs/ci.jsonl` by hand
and change one `"run": 9001` to `"run": "9001"`. `python -m ops.contract` must report it and exit 1. Then
re-run `python -m ops.setup` to restore the logs. **Never commit anything under `run/`.**

If any of the existing logs fail your contract, **don't change the logging code to make them pass.** Stop and
tell the human which line and field fail. A mismatch like that is a real finding for the Narc owner.

## Definition of done

- [ ] `python -m ops.contract` exists and passes on fresh logs after `ops.setup` and after every scenario
- [ ] `ops_tests/` has the contract tests and monitor-rule tests, all passing
- [ ] Acceptance has the new checks and passes
- [ ] No changes in `app/`, `jobs/`, `tests/`, `ci.yml` or `ops/scenario.py`
- [ ] Works on Windows; on macOS/Linux too if you have access (otherwise GitHub Actions checks it)

## Open the PR

```
git add ops/contract.py ops_tests ops/acceptance.py .github/workflows/acceptance.yml README.md
git commit -m "Add log-contract checker and monitor rule tests"
git push -u origin <your-name>/log-contract
gh pr create --fill     # or open the PR on github.com
```
In the PR description, fill in the template and paste the `N/N checks passed` line. This PR touches log
validation, so ask the Narc owner to review it as well.
