# Backup AI operator

Approved by the user on 2026-11-26 (CLAUDE.md section 3): a backup for when Claude is not around. It runs on GitHub
Actions every 3 hours at minute 37, and by hand from the Actions tab ("Backup AI operator", Run workflow, mode
`all | check | report | rerun | fix`). The workflow lives in `cloud/workflows/backup-ai.yml`; it runs only once it is
switched on by copying it, unchanged, to `.github/workflows/backup-ai.yml` (the tests check the two are identical
whenever the second exists).

Same permissions as Claude, minus anything to do with real money. It never imports or runs live.py, never opens
paper.db or live.db, never reads keys, and changes no rule, limit or lock. Its output is advice only.

## Four jobs: model-written code never runs where a token or the key is
| Job | Permissions and secrets | What it does |
|---|---|---|
| `operate` | NVIDIA key; GitHub token with contents read, issues write, actions write, pull requests read | `check`, `report`, `rerun`; for `fix` it only **proposes**: the diff and its metadata are uploaded as an artifact. Nothing from the model is applied or run here. |
| `status` | contents write; no key | Commits `ops/status/` to main: exactly one commit by `tradebot-runner`, only `ops/status/` paths, hooks off (`core.hooksPath=/dev/null`); checked again before every push, including after each rebase retry. Anything else is refused. |
| `test` | `permissions: {}`, no secret, no token, no stored credentials | Downloads the proposal, re-checks it against the path rules, applies it, runs `tests/run_all.py` (hard limit 300 s, no bytecode files) and fails unless the files changed afterwards (`git status --porcelain --ignored --untracked-files=all` plus `git diff --no-renames --name-only HEAD`) are exactly the diff's own files. Uploads the result (pass or fail, the end of the test output, the file set). |
| `publish` | contents write, pull requests write; no key | Runs only if `test` passed, and runs **nothing** from the diff: a fresh checkout of the same commit, the path rules again, `git apply`, stages exactly the diff's paths (never `git add -A`), commits without hooks, pushes `backup-ai/fix-<failed run id>` and opens the pull request with `git show --stat` of the real commit and the test result: **Do not merge without review**. It never merges. |

## What each step does
| Step | AI? | What it does |
|---|---|---|
| `check` | no | Latest runs **on main** of every workflow in `.github/workflows` (status, result, age against the schedule in its cron lines plus a grace for GitHub's late starts), and the age of the newest commit in `research/data/live20`, `research/data/plan19` (only Nov 28 - Dec 28, until scored), `research/data/plan20`, `research/results` and `trial/`. Writes `ops/status/status.json` and `status.md`. |
| `report` | yes | Sends the status (and the last 200 lines of failed runs' logs, with anything that looks like a key, token or e-mail address removed) to the model for a plain-English report. Opens or updates ONE issue labelled `backup-ai` ("Backup AI: <date> <n> problems") while anything is failed or stale, so GitHub e-mails you; closes it when all is green. A failed issue call is listed under the status problems. Without the key the issue is still kept, with the non-AI table. |
| `rerun` | no | Runs with or without the key. Re-runs a failed run once (`gh run rerun <id> --failed`), only for live20, plan19, plan5-lip, probe18/19 and the trial scan and settle; only the newest run on main, first attempt, under 12 hours old; recorded in `ops/status/reruns.json` so never twice. A failed re-run is listed under the status problems. Never plan10, plan15-18, plan20 (one-time stages), the backstop or itself. |
| `fix` | yes | Needs the key. Only when no commit with `Co-Authored-By: Claude` reached main in the last 24 hours (if git cannot tell, it does nothing), and only for a workflow whose failed run on main was started by its schedule or by hand. One failing workflow at a time: the model gets the failure log and up to 6 related files and proposes a minimal diff, which then goes through `test` and `publish` above. One open proposal per workflow; never twice for a run (`ops/status/fixes.json`). |

### What a fix may change
First an **allowlist**: `freshness.py`, `check.py`, `marks.py`, `learn.py`, `dashboard.py`, `dashboard_assets.py`,
`control_view.py`, `account_view.py`, `tbcommon/**.py`, and `research/*.py` except frozen or pre-registered code
(`research/plan*.py`, `research/live*.py`, `research/nov11.py`, `research/backtest*.py`, `research/lip.py`,
`research/fetch.py`, `research/placebo.py`). Then the **deny list**, checked as well: live.py and every module it
imports (worked out from live.py's source at run time; if that fails, every path is refused), the bot's databases,
config/strategy/weather/nws/gate/core, kalshi.py, stationfc.py, shadow.py, main.py, backup.py, jobs.py, export.py,
joblock.py, scan_window.py, audit.py, CLAUDE.md, any dotfile or dot folder (`.gitattributes`, `.gitmodules`, `.claude/`,
`.github/`), `sitecustomize.py`, `*.pth`, `pyproject.toml`, `setup.cfg`, `__init__.py`, workflows, `agents/`, `tasks/`,
`tests/` (the model may not add or edit tests), `ops/`, `research/data/`, `research/results/`, `research/PLAN*.md`,
`backups/`, `trial/`, scripts (`.cmd .ps1 .bat .sh`) and key files. Deleting, renaming or copying files, mode changes
and binary patches are refused. The diff is checked in all three jobs.

On main it commits only `ops/status/**` (refused otherwise).

## Models (NVIDIA hosted API, OpenAI-compatible)
`pick(task)` reads `GET /v1/models` at run time and takes the first preferred id that is listed, else the first listed
id of the same family, else reports "no model" and falls back to the non-AI text. The ids below are a best guess and
are only trusted once the API lists them; the model used is recorded in `status.json`, the issue and the pull request.
- check-summary: meta/llama-3.1-8b-instruct, meta/llama-3.2-3b-instruct, mistral-7b, gemma-2-9b, phi-3-mini, nemotron-nano
- diagnose: deepseek-ai/deepseek-r1, nvidia llama-3.3-nemotron-super-49b, nemotron-ultra-253b, qwen/qwq-32b, llama-3.3-70b, llama-3.1-405b
- code-fix: qwen/qwen3-coder-480b-a35b-instruct, qwen2.5-coder-32b, codestral-22b, deepseek-coder-6.7b, codellama-70b

At most 6 model calls and 6 minutes of model time a run (each request at most 90 s, retries and waits included),
temperature 0.2, limited retries on 429 and 5xx. Job limits: operate 30 min (its main step 15), status 10, test 15
(the tests themselves 300 s), publish 10.

## What you need to do
1. Repository Settings > Secrets and variables > Actions > New repository secret: `NVIDIA_API_KEY` (your key from
   build.nvidia.com). Never paste it into chat or a file. Without it the job runs the non-AI check, re-runs and the
   issue only.
2. Repository Settings > Actions > General > Workflow permissions: tick "Allow GitHub Actions to create and approve pull
   requests" (needed for `publish`). The workflow never approves or merges.
3. To get the e-mails, watch the repository (or at least Issues).

## Reviewing a fix proposal
- **Read the pull request's Files tab.** It shows the real change. The text in the pull request body (the model's
  cause, the test output) is redacted, may be cut short and comes partly from the job that ran the proposed code, so
  it is a summary, not proof.
- A fix proposal is a suggestion from a model; read the diff and the test result before merging, or ask Claude.

## Limits
- It sees GitHub only. The PC (its scheduled tasks, paper.db, live.py, the Kalshi account) is not reachable from here.
- GitHub starts scheduled runs late or not at all, this job included.
- The action versions are pinned by commit; check the pins of `actions/upload-artifact` (v4.6.2) and
  `actions/download-artifact` (v4.3.0) against GitHub before switching the workflow on.
