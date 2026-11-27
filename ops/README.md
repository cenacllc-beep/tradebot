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
| `status` | contents write; no key | Runs before `test`, and refuses unless the downloaded status files match the `status_sha256` digest `operate` wrote as a job output. Commits `ops/status/` to main: exactly one commit by `tradebot-runner`, only `ops/status/` paths, hooks off (`core.hooksPath=/dev/null`); checked again before every push, including after each rebase retry. Anything else is refused. |
| `test` | `permissions: {}`, no secret, no token, no stored credentials | Downloads the proposal, re-checks it against the path rules, applies it, runs `tests/run_all.py` (hard limit 300 s, no bytecode files) and fails unless the files changed afterwards (`git status --porcelain --ignored --untracked-files=all` plus `git diff --no-renames --name-only HEAD`) are exactly the diff's own files. That changed-file check is **advisory**: the tested code runs in this same job and could defeat it. The binding check is `publish`'s re-validation on a fresh checkout. Uploads the result (pass or fail, the end of the test output, the file set). |
| `publish` | contents write, pull requests write; no key | Runs only if `test` passed, and runs **nothing** from the diff: a fresh checkout of the same commit, the hashes and path rules again, `git apply`, stages exactly the diff's paths (never `git add -A`), commits without hooks (the commit carries `Backup-AI-Run: <workflow run id>` and `Backup-AI-Diff-SHA256`), pushes `backup-ai/fix-<failed run id>` and opens the pull request with `git show --stat` of the real commit and the test result: **Do not merge without review**. The label is added in a separate step that may fail without failing the job. If the branch already exists, it is reused only when it is this same workflow run's earlier push of the same diff (one runner commit on the base commit, same trailers, same files); then only the pull request is opened (or nothing, if it is open). Any other existing branch is refused. It never merges. |

### Artifacts and the `test` job
Code run in `test` holds the runner's artifact credential (the upload step's token is reachable from the job), so it
could upload artifacts of its own. Therefore:
- `operate` writes job outputs `diff_sha256` and `meta_sha256` (the proposal files) and `status_sha256` (the status
  files), computed by `ops/backup_ai.py` itself. `test` and `publish` get them as command-line arguments and refuse
  unless the downloaded `fix.diff` and `meta.json` match byte for byte; `status` checks the status files the same way.
  Hashes stored inside an artifact are never trusted.
- `status` runs before `test` (`test` needs `status`), so the status artifact is used before any proposed code runs.
- No upload uses `overwrite`, so an artifact name already taken cannot be replaced.
- The pull request's "cause" comes only from `operate`'s hash-checked `meta.json` and is redacted.
- The tests run in their own process group, which is killed when they finish as well as at the time limit. This is
  partial: a process that starts its own session escapes the group. It does not matter for the binding checks, which
  run in `publish`.

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
and binary patches are refused. New files are refused outright. Every file section must start with
`diff --git a/X b/X` (the same X on both sides) and its `---` / `+++` lines must be exactly `a/X` / `b/X`; a diff
without `diff --git` headers is refused (otherwise `--- tbcommon/config.py` would be read as an allowed path while
`git apply` at -p1 changes the root `config.py`). Hunks are counted, so a removed line starting `--- ` is not mistaken
for a header. The diff is checked in all three jobs.

On main it commits only `ops/status/**` (refused otherwise).

## Models (NVIDIA hosted API, OpenAI-compatible)
`pick(task)` reads `GET /v1/models` at run time and takes the first preferred id that is listed, else the first listed
id of the same family, else reports "no model" and falls back to the non-AI text. The ids below are a best guess and
are only trusted once the API lists them; the model used is recorded in `status.json`, the issue and the pull request.
- check-summary: meta/llama-3.1-8b-instruct, meta/llama-3.2-3b-instruct, mistral-7b, gemma-2-9b, phi-3-mini, nemotron-nano
- diagnose: deepseek-ai/deepseek-r1, nvidia llama-3.3-nemotron-super-49b, nemotron-ultra-253b, qwen/qwq-32b, llama-3.3-70b, llama-3.1-405b
- code-fix: qwen/qwen3-coder-480b-a35b-instruct, qwen2.5-coder-32b, codestral-22b, deepseek-coder-6.7b, codellama-70b

At most 6 model calls and 6 minutes of model time a run (each request at most 150 s, retries and waits included),
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

## When Claude is unavailable
Claude's three daily cloud tasks (the 3:21 PM afternoon report, the 9:25 PM evening report and the 11:41 PM late-night
scan check) stop when Claude hits its usage limit. The GitHub backup AI above cannot replace them: it cannot see the
PC's `logs\tasks.log`, and the PC's data must never go to the public repository. So the PC writes its own report
(added 2026-11-27):

| When | What runs | What it writes |
|---|---|---|
| End of the afternoon settle and of the evening job | `jobs.py` runs `ops/pc_report.py settle` / `evening` after the job's done line | `logs\report_latest.md` and `logs\reports\YYYY-MM-DD-<job>.md` (newest 30 kept) |
| Hourly job at 11:20 PM and 12:20 AM | `ops/pc_report.py latenight` first | a report only when tonight's scan is missing or still waiting (before 1 AM) |

- **Facts, always:** read only from the latest block of that job in `logs\tasks.log`: trades settled, markets logged
  and paper trades opened, the Brier line, the gate verdict exactly as stored (GATE LOOK), the FRESHNESS line, the
  Kalshi demo and prod lines, and every problem line from a narrow list (KILL SWITCH, TRADES BLOCKED, AUDIT failures,
  JOB LOCK, WAITING FOR NETWORK, backup and scan failures, unknown order outcomes, unreadable settles, a stale
  FRESHNESS, a non-zero exit, tonight's scan missing). Per-market errors that are retried (an estimator timeout, a
  price-history miss, one failed scan try) are not problems and raise no toast. It never opens paper.db or live.db,
  never imports live.py and runs nothing that trades.
- **Which job a line belongs to:** jobs.py writes `----- <job> step: <args>` before each step and
  `----- <job> step end (exit N)` after it; lines between them belong to that job even when another job starts
  meanwhile (an hourly job during the evening scan or its retry pause, or during the afternoon settle). jobs.py's own
  lines (network waits, JOB LOCK, scan retries) are attributed by their text. Logs from before the markers fall back to
  the most recently started job.
- **The plain report is written first.** Then, only if you ticked the box on `.\run settings` (below), the AI wording
  is tried within this script's own budget: at most 3 model calls and 150 s, in a thread with a join timeout; the report
  is rewritten when that ends. The `Wording:` and `AI budget:` lines say what happened.
- **What goes to NVIDIA:** only the job's status lines (counts, Brier, clear margin, the stored gate verdict, the
  freshness line, problem lines), through `ops/backup_ai.py`'s own client and model picker (`check-summary`). Never sent:
  the Kalshi demo and prod lines, the real-money trial line, settled P&L, the LEARNING profit line, any line with a dollar
  figure (an account problem is sent only as "A Kalshi account problem"), and anything that looks like a key, token or
  e-mail address. Those stay in the report's facts on the PC.
- **The AI text is checked.** It is used only if every number in it, with its sign, appears in what was sent (dates,
  times, exit codes, tickers and version tags do not count), it does not call the day clear while there are problems,
  and it names every problem. Otherwise, with no key, or on an API failure or timeout, the plain summary is used. The
  deterministic problem list always comes first, above any AI text, and every fact follows below it.
- **Telling you:** every report shows in the dashboard's "Latest report" panel (under the header). When it shows a
  problem, Windows shows a toast (PowerShell's built-in notifications; never waited for, failures ignored). Jobs that run
  while you are signed out (Task Scheduler's S4U logon) cannot show a toast: the dashboard still has the report.
- **Never in the way:** the step runs in its own process after the job's done line, outside the job lock, stopped after
  4 minutes; whatever happens is one `PC REPORT:` line in the log. It never changes the job's exit code, its lock or a
  scan.
- **The phone page is not updated.** It is a claude.ai page that only Claude can refresh; when Claude is back, its
  reports resume and it can read `logs\reports\` for the days it missed.

### Keeping the NVIDIA key on the PC (opt-in)
`.\run settings` has a checkbox, unticked by default, whose text says exactly what is sent. Unticked, nothing is kept on
the PC. Ticked, `ops/pc_key.py`:
- encrypts the key with Windows DPAPI in **machine scope** (CryptProtectData with CRYPTPROTECT_LOCAL_MACHINE and a fixed
  extra input). User scope usually fails in the signed-out (S4U) scheduled runs, which have no loaded user profile;
- writes it to `%USERPROFILE%\.tradebot\nvidia.key`, outside the project folder (a path inside it, also through a
  link, is refused);
- cuts the file's NTFS permissions to your account only (`icacls <file> /inheritance:r /grant:r <you>:(F)`, a fixed
  argument list), reads them back, and deletes the file if anything else is listed. They are checked again before every
  use.

**Trade-off:** in machine scope, any process running as an administrator (or SYSTEM) on this PC could decrypt the file.
The file permissions keep other, non-administrator users out. A missing file, a file that cannot be decrypted and a
file whose permissions are wrong each show their own reason on the report's `Wording:` line. "Remove the key from this
PC" deletes the file. The key is never written to the project folder, a log, a report or a page.

**To confirm on the PC:** this was tested only with a fake DPAPI and a fake icacls. After ticking the box, check that
one real scheduled run (the afternoon settle or the evening job, signed out) writes `Wording: AI` in
`logs\report_latest.md`; if it shows a key reason instead, the PC reports still work in plain text.

## Limits
- It sees GitHub only. The PC (its scheduled tasks, paper.db, live.py, the Kalshi account) is not reachable from here.
- GitHub starts scheduled runs late or not at all, this job included.
- The action versions are pinned by commit; check the pins of `actions/upload-artifact` (v4.6.2) and
  `actions/download-artifact` (v4.3.0) against GitHub before switching the workflow on.
