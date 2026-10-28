# Review agents (from agency-agents)

Two role prompts copied unchanged from https://github.com/msitarzewski/agency-agents (MIT license, see
LICENSE-agency-agents.txt; commit bd956db, 2026-10-13):
- statistician.md (academic/academic-statistician.md): pressure-tests research results and test designs.
- code-reviewer.md (engineering/engineering-code-reviewer.md): reviews code changes (blocker / suggestion / nit).

How this project uses them (CLAUDE.md section 6): before acting on a research result or shipping a change to the bot,
a fresh agent that has not seen the work reviews it with one of these prompts. Its findings, and what was fixed or
deliberately left, go into CHANGELOG.md. The reviewers only read and report; they never trade or edit files.

Not used for trading decisions. The repository has no trading agents, and AI agents debating trades would not create an
edge: the market already prices the public forecasts, and an AI's opinion cannot be tested honestly on past markets
(it may already know what happened).

Optional: to use them in Claude Code on this PC, copy the two .md files to %USERPROFILE%\.claude\agents\ (outside this
folder, so only with the user's go-ahead). The other ~300 agents in the repository were not installed.
