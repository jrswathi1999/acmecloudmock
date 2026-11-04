## What does this PR change?

<!-- One or two sentences. Link the issue if there is one. -->

## Which area?

- [ ] Shop (`app/`, `jobs/`, `tests/`) — this is what the company's git history starts from
- [ ] Company tooling (`ops/`)
- [ ] Log fields or alert messages (Narc parses these — **needs Narc owner review**)
- [ ] Scenario behaviour or command names (Narc's buttons call these — **needs Narc owner review**)
- [ ] Docs only

## Checklist

- [ ] `python -m pytest -q` passes
- [ ] `python -m ops.acceptance` passes locally (paste the `N/N checks passed` line): 
- [ ] Tested on: [ ] Windows  [ ] macOS  [ ] Linux
- [ ] No `shell=True`, no bash-only commands, `encoding="utf-8"` on every text file, `pathlib` paths
- [ ] Secrets stay synthetic (contain `synth`), hosts stay `*.example.test`, nothing can leave the machine
- [ ] I did **not** "fix" one of the deliberate weaknesses listed in the README
- [ ] README updated if commands, scenarios, logs or weaknesses changed
