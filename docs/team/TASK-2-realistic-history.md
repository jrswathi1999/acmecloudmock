# Task 2: realistic team history in the `normal` scenario, then check Narc's verdicts

> **For Claude:** you're helping a teammate on the acme-shop repo. Do the steps in order. Ask the human before
> pushing or opening the PR. Don't change any file outside the "Files you may change" list without asking.

## Background (read first)

acme-shop is a small pretend company ("Acme Cloud") that breaks on purpose, so our hackathon project **Narc** can
investigate it. Narc reads the company's git history (in `run/`) and its logs, then decides who broke production.

Right now `python -m ops.scenario normal [n]` only ever changes **the tagline** in `app/copy.py`. The history
looks fake: every everyday commit is "Update tagline: ...". A detective that sees real-looking background work
(small UI tweaks, a new test, docs, a log message) is a much stronger demo. It also makes the red herrings harder,
which is the point.

Your job: make `normal` produce a **varied, believable stream of small safe changes by the right people**. Then
run Narc against each scenario and record its verdicts.

Read these before you start:
- `README.md`: the sections "Scenarios" and "Known weaknesses (on purpose)"
- `CONTRIBUTING.md`: the rules every PR must follow
- `ops/scenario.py`: especially `cmd_normal`, `ship`, `edit`, `set_tagline` and the break scenarios

## Setup

```
git clone <repo url> acme-shop && cd acme-shop
git checkout -b <your-name>/realistic-history
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

- `ops/scenario.py`: **only** `cmd_normal`, plus new helper functions and new constants near `TAGLINES`
- **new** `docs/narc-verdicts.md`
- `README.md`: update the `normal` row of the scenarios table

**Do not touch:** `app/`, `jobs/`, `tests/`, `.github/`, `ops/monitor.py`, `ops/acceptance.py`. Teammate 1 is
working in `ops/acceptance.py`. The template files are what the company starts from, and the break scenarios edit
them by exact text.

## The hard rules for "everyday changes"

Each change runs inside the company (`run/`) through `ship()`, so it gets a real commit, real CI and a real deploy.
Every change must:

1. **Pass CI.** That means `python -m pytest -q` inside the company. A failing build means no deploy, and the
   history goes wrong.
2. **Always produce a diff, every time.** `normal` can run many times in a row. Use toggles (A→B, B→A),
   pick-a-different-value, or append-a-new-item patterns, like `set_tagline` does today.
3. **Never touch the lines the break scenarios edit,** or `fix`'s `git revert` will hit merge conflicts:
   - `app/config.py`: don't touch it at all
   - `app/db.py`: don't touch it at all
   - `app/main.py`: don't touch the checkout function or the `INSERT INTO orders ...` line. Ideally leave the file alone.
   - `.github/workflows/ci.yml` and `requirements.txt`: don't touch them (the attack edits them, and Narc treats
     build-file edits as a clue)
   - `tests/test_app.py`: don't change existing lines (priya's rename edits the fixture). **Appending** a new test
     function at the end of the file is fine.
   - `app/copy.py`: keep the `TAGLINE = "..."` and `BUY_LABEL = "..."` lines in that exact one-line format
   - `jobs/daily_revenue.py`: don't change its first docstring line (vendor-outage toggles it), and don't change the
     `WARN column \`currency\`` text or the alert message
4. **Never write log lines yourself.** Only `ship()`, the shop and the job write logs.
5. **Right person for the file:**
   - jordan (frontend): `app/copy.py` plan text, `app/web/*.html` wording
   - priya (backend): a new test appended to `tests/test_app.py`
   - sam (data): a log message wording in `jobs/daily_revenue.py`, other than the protected lines
   - alex (tech lead): the company's `README.md`
   - any of them can still change the tagline

## Step 1: a pool of everyday changes

In `ops/scenario.py`, add a list of change functions. Each one takes an `rng`, edits files under `COMPANY`
with `common.read_text` / `common.write_text`, and returns `(author, commit_message)`. Aim for **at least 8 kinds**,
for example:

| author | change | commit message |
|---|---|---|
| jordan | swap one feature bullet in `PLAN_DETAILS` for an alternative from a small list | `Copy: clarify Team plan features` |
| jordan | toggle a heading in `app/web/storefront.html`, e.g. "Simple, predictable pricing" ↔ "Pricing that scales with you" | `Storefront: tweak pricing heading` |
| jordan | toggle the hero subtitle sentence in `storefront.html` | `Storefront: shorter hero copy` |
| priya | append a new, *passing* test, e.g. `/api/revenue` returns a `rows` list, or `/` returns `text/html`. Give it a unique function name each run (add a counter suffix). | `Add test for <thing>` |
| sam | toggle one non-protected log line wording in the job, e.g. `read N orders` ↔ `loaded N orders` (keep the WARN and alert lines exactly as they are) | `daily_revenue: clearer log wording` |
| alex | append a line to the company `README.md` (a "Runbook" or "Changelog" bullet) | `Docs: add runbook note` |
| alex / any | the existing tagline change | `Update tagline: ...` |

Keep `cmd_normal`'s behaviour:
- same command and signature (`normal [n]`);
- pick a change whose author differs from the previous commit's author, so setup always ends with ≥2 authors;
- `ship()` each change, then `traffic.run(15)`;
- after the loop: `run_job()`, `monitor.check()`, `finish(start)`.

## Step 2: prove it

```
python -m pytest -q
python -m ops.setup
python -m ops.scenario normal 12          # every commit must say CI SUCCESS and deploy LIVE
git -C run log --format="%h %an %s"       # varied authors and messages, no failed builds
python -m ops.scenario break-checkout --red-herring
python -m ops.scenario fix                # revert must apply cleanly (no conflict)
python -m ops.scenario break-revenue
python -m ops.scenario fix
python -m ops.acceptance                  # must end with "30/30 checks passed"
```
Run `normal 12` **twice in a row** too. Every change must still produce a diff the second time.

## Step 3: check Narc's verdicts (needs the Narc repo)

1. `python -m ops.setup`, then `python -m ops.scenario normal 6`.
2. Point Narc at the company. Windows: `$env:NARC_APP = "<full path>\acme-shop\run"`, then start Narc.
   macOS: `NARC_APP=<full path>/acme-shop/run .venv/bin/python -m narc.server`.
   **Don't press Narc's "Start the company fresh" button.** It replaces `run/` with Narc's built-in copy.
3. For each scenario, run it from the acme-shop folder, let Narc investigate, and write down the result:
   `break-checkout`, `break-checkout --red-herring`, `break-revenue`, `attack`, `vendor-outage`.
   Run `python -m ops.scenario fix` (or `reset`) between them.
4. Create `docs/narc-verdicts.md` with a table: scenario | expected verdict (from the README) | Narc's verdict |
   confidence | culprit commit Narc named | correct? | notes. Add a short "Problems found" list at the bottom,
   e.g. "Narc doesn't know the `local-ci` alert component yet".

If Narc gets something wrong, **don't change acme-shop to make Narc happy.** Write it down. That's a Narc bug for
the Narc owner.

## Definition of done

- [ ] `normal` picks from ≥8 kinds of everyday changes, by the right people, with realistic messages
- [ ] `normal 12` run twice: every build green, every deploy live
- [ ] `fix` still reverts cleanly after `break-checkout --red-herring` and after `break-revenue`
- [ ] `python -m ops.acceptance` passes
- [ ] `docs/narc-verdicts.md` filled in (or a note saying you couldn't run Narc, and why)
- [ ] No changes in `app/`, `jobs/`, `tests/`, `.github/`, `ops/acceptance.py`, `ops/monitor.py`

## Open the PR

```
git add ops/scenario.py docs/narc-verdicts.md README.md
git commit -m "Make the normal scenario produce a varied team history; record Narc verdicts"
git push -u origin <your-name>/realistic-history
gh pr create --fill     # or open the PR on github.com
```
In the PR description, fill in the template, paste the `N/N checks passed` line and a sample of
`git -C run log --format="%h %an %s" -n 12`. This PR changes scenario output, so ask the Narc owner to review it.
