# Always-on runner (prepared 2026-10-14; set up on 2026-10-28 in the public repository cenacllc-beep/tradebot)

Why: the scheduled scans need this PC awake with the Claude app open. A free GitHub Actions runner can run the same
paper bot on a schedule in the cloud. Claude's own cloud sessions cannot reach Kalshi, NWS or IEM, so they cannot run the
bot; GitHub's runners can.

What it is: the same code, run by GitHub on a schedule, on its OWN database (`trial/paper.db`). It never touches this
PC's `paper.db`. Paper trading only; no keys or secrets are needed (all data sources are public).

## Setup (needs the user; about 10 minutes)
1. On github.com, create an EMPTY PRIVATE repository named `tradebot` (no README).
2. In a Claude session, attach it (Claude's add_repo, with push access) and ask Claude to push this folder's code to it
   WITHOUT `paper.db`, `backups/` or `research/data/` (add them to `.gitignore`), plus an empty `trial/.gitkeep`.
3. Copy `cloud/workflows/tradebot-scan.yml` and `tradebot-settle.yml` to `.github/workflows/` in the repository.
4. Run "tradebot evening scan (trial)" once by hand (Actions tab, Run workflow) and check `trial/` gets a database.
5. Let it run next to the PC for two weeks. Compare `trial/paper.db` with the PC's logs. Only then decide whether the
   PC can stop scanning (the user's decision).

## Updated 2026-10-28
- The scan runs at 8:55 PM La Paz (00:55 UTC), as on the PC, and only inside the 8:50 PM to 1:00 AM window (scan_window.py). A test run started by hand at another time checks the setup and does not scan.
- The scan tries up to 3 times, 5 minutes apart, as jobs.py does on the PC. A failed run still commits whatever it wrote.
- `trial/.gitignore` keeps the run's own backup copies out of the repository; git history already keeps every version of `trial/paper.db`.
- Actions versions: checkout v5 and setup-python v6.
- The trial runs the same code as the PC, including the 30-point veto and the Detroit and West Palm Beach markets.
- It never runs live.py. The Kalshi key stays on the PC.

## Notes
- GitHub's schedules can start 5-30 minutes late. The bot skips any market whose day has begun (strategy.started), so a
  late start costs markets, never a wrong trade. 8:40 PM La Paz leaves four hours before the first markets start.
- The repository's commit history is the off-machine backup of `trial/paper.db`.
- Private repositories get a limited number of free Actions minutes a month (2,000 on GitHub Free in 2025); these two
  jobs use roughly 5-10 minutes a day. Check GitHub's current limits before relying on it.
- Optional phone page from the cloud: a Claude scheduled task (no PC needed) with this prompt, run after the settle:
  "Read trial/dashboard.html from the private GitHub repository tradebot (attached), remove its doctype/html/head/body
  wrapper and the two meta tags (keep the title, style, page content and scripts), read the artifact
  https://claude.ai/artifact/KNt9PdDMnipsfXZQwzWNWe with the Artifact tool, then publish the new file to that same URL
  without changing its capabilities. Paper trading only; never place orders."
  Use it only if the PC is retired from the routine, so the two do not overwrite each other.

## Updated 2026-10-28, afternoon
- The repository is public (the user's choice, so Actions run free). Never commit keys, account details or the PC's
  databases and logs. `cloud/repo.gitignore` is the repository's `.gitignore`.
- **PLAN5 L moved here:** `cloud/workflows/plan5-lip.yml` samples once an hour (it starts at :05, :20, :35 and :50, because GitHub starts scheduled runs late or not at all; the first run in an hour samples), settles, and scores once from
  2026-11-25. Its data (public Kalshi order books and reward programs) lives in `research/data/lip/` in the repository.
  The PC's copy holds `research/data/lip/MOVED.txt`, so the PC no longer samples (that file is never committed).
- The sample runs in its own concurrency group: GitHub keeps one pending run per group, so a queued sample could
  otherwise cancel a pending scan or settle.
- Every workflow's save step replays its commit on top of the latest one and retries the push, because the jobs commit
  to different folders (trial/ and research/data/lip/) at different times.
- Before the phone page moves to `trial/dashboard.html`, the two runners are compared for a few days (Claude's
  scheduled follow-up).

## Updated 2026-10-29
- On the first evening GitHub's scheduler started almost no scheduled run. The 00:55 UTC trial scan had not started by
  03:56 UTC, when it was started by hand; 1 of 16 PLAN5 L runs started.
- **Trial scan:** `tradebot-scan.yml` now starts at 00:55 UTC and then every half hour until 04:25 UTC. The first run that
  gets going scans. Later ones stop when `check.py` says tonight's markets are already logged, so it is still one scan an
  evening. A run started by hand does the same.
- **Trial settle:** `tradebot-settle.yml` starts hourly from 18:40 to 22:40 UTC. Settling again is safe.
- **PLAN5 L:** the PC samples again as well as GitHub (research/PLAN5.md, logistics of 2026-10-29). The workflow no longer
  scores. The score runs once, by hand, after `python research/lip.py merge <PC copy>`.
