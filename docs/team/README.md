# Team plan: who does what

acme-shop already works end to end: every scenario, `fix`, `reset` and `python -m ops.acceptance`
(30/30 on Windows). The remaining work is split into **two independent tasks**, one per teammate. They touch
different files, so you can both work at the same time without merge conflicts.

| | Task | Main files | Size |
|---|---|---|---|
| **Teammate 1** | [TASK-1-log-contract.md](TASK-1-log-contract.md): log-contract checker and tests for the monitor rules | new `ops/contract.py`, new `ops_tests/`, `ops/acceptance.py`, `.github/workflows/acceptance.yml` | ~half a day |
| **Teammate 2** | [TASK-2-realistic-history.md](TASK-2-realistic-history.md): make the `normal` scenario produce a realistic, varied team history, then check Narc's verdicts | `ops/scenario.py` (only `cmd_normal` and new helpers), new `docs/narc-verdicts.md` | ~half a day |

## How to use these files with Claude

Open Claude Code in your clone of this repo and say:

> Read `docs/team/TASK-1-log-contract.md` and do the task, step by step. Stop and ask me before pushing.

(Teammate 2 uses `TASK-2-realistic-history.md`.) Each task file is self-contained: setup, rules, steps, a
definition of done, and how to open the PR.

## For the repo owner (do this first, once)

1. Make the template a git repo and push it (from `D:\acme`):
   ```
   git init -b main
   git add -A
   git commit -m "acme-shop: initial template"
   git remote add origin https://github.com/<you>/acme-shop.git
   git push -u origin main
   ```
   On an exFAT drive, first run `git config --global --add safe.directory D:/acme` (and `D:/acme/run`).
2. On GitHub, add both teammates as collaborators.
3. Settings → Branches → add a rule for `main`: require a pull request, 1 approval, and the `acceptance`
   status checks. (The pretend company in `run/` has no protection on purpose. This real repo should.)
4. Send each teammate the link to their task file.

## Merge order

The tasks are independent, so merge whichever PR is ready first. The other teammate then runs
`git pull --rebase origin main`, re-runs `python -m ops.acceptance` and pushes again.
