# Narc verdicts against acme-shop

How Narc (the incident detective) judged each scenario, after `python -m ops.setup` and
`python -m ops.scenario normal 6` gave the company a varied background history.

> **Status: Narc not run yet.** The Narc incident-detective build (`python -m narc.server`, reads `NARC_APP`)
> wasn't available on the machine this was prepared on. The only local "Narc" checkout there is a different
> project (a Node tech-debt radar that analyses GitHub repos, not `run/`). The *expected* column comes from the
> README. Whoever has the Narc repo should fill in the other columns using the steps below, then remove this note.

## Results

| scenario | expected verdict (README) | Narc's verdict | confidence | culprit commit Narc named | correct? | notes |
|---|---|---|---|---|---|---|
| `break-checkout` | Bad change: priya's commit "Rename PAYMENTS_API_URL to PAYMENT_API_URL", high confidence. Roll back, then revert. | _not run_ | | | | |
| `break-checkout --red-herring` | Bad change: priya's rename, **not** jordan's tagline change shipped mid-outage. | _not run_ | | | | |
| `break-revenue` | Bad change: sam's commit "Store currency as ISO currency_code", high confidence. Fix must rename the column back. | _not run_ | | | | |
| `attack` | Attack via the AI agent (prompt injection in issue #518), high confidence, about 8 clues. | _not run_ | | | | |
| `vendor-outage` | Vendor (GitHub hosted runners), not our fault. Don't roll back. | _not run_ | | | | |

## How to fill this in

1. In acme-shop: `python -m ops.setup`, then `python -m ops.scenario normal 6`. **Wait 2 minutes** before the
   first break scenario (see "Problems found").
2. Point Narc at the company:
   - Windows: `$env:NARC_APP = "<full path>\acme-shop\run"`, then start Narc.
   - macOS: `NARC_APP=<full path>/acme-shop/run .venv/bin/python -m narc.server`.
   - **Don't press "Start the company fresh"** in Narc. It replaces `run/` with Narc's built-in copy.
3. For each row: run the scenario from the acme-shop folder, let Narc investigate, write down the verdict,
   confidence and the culprit commit it named. Run `python -m ops.scenario fix` (or `reset`) between rows.
4. If Narc is wrong, record it here and in "Problems found". Don't change acme-shop to make Narc happy.

## What the background history now looks like

`normal` no longer only changes the tagline. A real sample from `git -C run log --format="%h %an %s" -n 16`
after `ops.setup` and `normal 12` run twice (macOS, every CI run SUCCESS, every deploy LIVE):

```
bafdb06 priya Add test for checkout amount with qty > 1
02d75b5 alex Update tagline: Deploy on Friday. We dare you.
8efdfd8 priya Add test for unknown routes
c958585 sam daily_revenue: clearer log wording
bc4a4a3 jordan Update tagline: Less glue code, more product.
9a3d758 sam daily_revenue: clearer log wording
e76b2e9 jordan Update tagline: Deploy on Friday. We dare you.
6d7dc1b alex Docs: add runbook note
127071c jordan Storefront: shorter hero copy
9faf9e3 priya Update tagline: From commit to customer in minutes.
1c4bd54 sam daily_revenue: clearer log wording
08bcd73 alex Docs: add runbook note
65142e3 priya Add test for checkout quantity validation
d64a02a sam daily_revenue: clearer log wording
95bbe87 priya Add test for the revenue dashboard page
3df7b18 jordan Storefront: tighten pricing subheading
```

After that, `break-checkout --red-herring` → `fix` and `break-revenue` → `fix` both reverted cleanly
(`Revert da039aa`, `Revert 16ba77b`).

Things a detective should now handle:
- **Plausible neighbours to every culprit.** priya also appends tests to `tests/test_app.py` (the file her bad
  rename edits). sam also edits `jobs/daily_revenue.py` (the job that reports $0). jordan edits `app/copy.py`
  and the storefront. Narc has to pick the commit whose diff explains the error, not the author who touched a
  related file.
- **Docs commits that mention recent work.** alex's changelog entries quote earlier commit subjects with their
  short sha. They are ordinary README edits, never a culprit.

## Problems found

- Not run yet (see the note at the top).
- **acme-shop (monitor), not Narc: `break-checkout` right after a long `normal` raises no `shop-api` alert.**
  On a fast machine a ship takes about 3 s, so the 2-minute window of `ops/monitor.py` still holds every
  checkout `normal` just made. Running `normal 12` twice and then `break-checkout --red-herring` straight away
  gave 504 requests in the window, 30 of them 5xx (6%, under the 20% threshold), so Narc gets no alert to start
  from. This also happened with the old tagline-only `normal`, which sent the same 15 checkouts per ship.
  Even `normal 6` (step 1 below) may be too much: with setup's traffic that's roughly 170 OK requests against
  30 failures, about 18%. Workaround for demos: wait 2 minutes after `normal` before a break scenario. Possible fix for the monitor owner (not done here, `ops/monitor.py` is off-limits for this task): count
  only requests made after the latest deploy, or only `/checkout` requests.
- Expected from the README, worth checking first: Narc may not know the `local-ci` alert component used by
  `vendor-outage` yet.
