# Always-on runner (prepared 2026-10-14; the user approved setting it up on 2026-10-28)

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
