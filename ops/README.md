# Backup AI operator

Approved by the user on 2026-11-26 (CLAUDE.md section 3): a backup for when Claude is not around. It runs on GitHub
Actions (`.github/workflows/backup-ai.yml`, identical copy in `cloud/workflows/`) every 3 hours at minute 37, and by
hand from the Actions tab ("Backup AI operator", Run workflow, mode `all | check | report | rerun | fix`).

Same permissions as Claude, minus anything to do with real money. It never imports or runs live.py, never opens
paper.db or live.db, never reads keys, and changes no rule, limit or lock. Its output is advice only.

## What each step does
| Step | AI? | What it does |
|---|---|---|
| `check` | no | Latest runs of every workflow in `.github/workflows` (status, result, age against the schedule in its cron lines plus a grace for GitHub's late starts), and the age of the newest commit in `research/data/live20`, `research/data/plan19` (only Nov 28 - Dec 28, until scored), `research/data/plan20`, `research/results` and `trial/`. Writes `ops/status/status.json` and `status.md`. |
| `report` | yes | Sends the status (and the last 200 lines of failed runs' logs, with anything that looks like a key, token or e-mail address removed) to the model for a plain-English report. Opens or updates ONE issue labelled `backup-ai` ("Backup AI: <date> <n> problems") while anything is failed or stale, so GitHub e-mails you; closes it when all is green. |
| `rerun` | no | Re-runs a failed run once (`gh run rerun <id> --failed`), only for live20, plan19, plan5-lip, probe18/19 and the trial scan and settle; only the newest run, first attempt, under 12 hours old; recorded in `ops/status/reruns.json` so never twice. Never plan10, plan15-18, plan20 (one-time stages), the backstop or itself. |
| `fix` | yes | Only when no commit with `Co-Authored-By: Claude` reached main in the last 24 hours (if git cannot tell, it does nothing). One failing workflow at a time: the model gets the failure log and up to 6 related files and proposes a minimal diff. A diff touching a protected path is refused (live.py, the bot's databases, config/strategy/weather/nws/gate/core, CLAUDE.md, .claude/, workflows, agents/, tasks/, run.bat and scripts, research/PLAN*.md, research/results/, frozen research code, backups/, trial/, this tool and its test). Otherwise it is applied in a separate worktree on branch `backup-ai/fix-<run id>`, the tests run (`tests/run_all.py`, with no token or key in their environment), and a pull request "Backup AI fix proposal: ..." is opened saying **Do not merge without review**. It never merges; one open proposal per workflow; never twice for a run (`ops/status/fixes.json`). |

On main it commits only `ops/status/**` (the workflow refuses anything else).

## Models (NVIDIA hosted API, OpenAI-compatible)
`pick(task)` reads `GET /v1/models` at run time and takes the first preferred id that is listed, else the first listed
id of the same family, else reports "no model" and falls back to the non-AI text. The ids below are a best guess and
are only trusted once the API lists them; the model used is recorded in `status.json`, the issue and the pull request.
- check-summary: meta/llama-3.1-8b-instruct, meta/llama-3.2-3b-instruct, mistral-7b, gemma-2-9b, phi-3-mini, nemotron-nano
- diagnose: deepseek-ai/deepseek-r1, nvidia llama-3.3-nemotron-super-49b, nemotron-ultra-253b, qwen/qwq-32b, llama-3.3-70b, llama-3.1-405b
- code-fix: qwen/qwen3-coder-480b-a35b-instruct, qwen2.5-coder-32b, codestral-22b, deepseek-coder-6.7b, codellama-70b

At most 6 model calls a run, temperature 0.2, limited retries on 429 and 5xx.

## What you need to do
1. Repository Settings > Secrets and variables > Actions > New repository secret: `NVIDIA_API_KEY` (your key from
   build.nvidia.com). Never paste it into chat or a file. Without it the job runs the non-AI check and the issue only.
2. Repository Settings > Actions > General > Workflow permissions: tick "Allow GitHub Actions to create and approve pull
   requests" (needed for `fix`). The workflow never approves or merges.
3. To get the e-mails, watch the repository (or at least Issues).

## Limits
- It sees GitHub only. The PC (its scheduled tasks, paper.db, live.py, the Kalshi account) is not reachable from here.
- GitHub starts scheduled runs late or not at all, this job included.
- A fix proposal is a suggestion from a model; read the diff and the test result before merging, or ask Claude.
