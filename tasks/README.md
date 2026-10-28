# Local scheduled runs (Windows Task Scheduler)

These three files let the PC run the bot on its own schedule, with no Claude session needed. The scans then cannot be
stopped by a usage limit or by Desktop Commander failing to start, which is what stopped the scans on Oct 15. Nothing
runs until install_schedules.cmd has been double-clicked once: that missing step is why no scan ran on Oct 22 or 23
either (docs/INCIDENT_2026-10-23.md).

| File | When | What |
|---|---|---|
| evening.cmd | daily 8:55 PM | `run.bat settle`, then `run.bat scan` (backups, scan, live.py mirror, shadow tests, dashboard); the scan only from 8:50 PM to 1 AM |
| settle.cmd | daily 2:51 PM | `run.bat settle` and `run.bat report` |
| hourly.cmd | every hour at :20 | `run.bat hourly` (read-only research and prices) |

Output is appended to logs\tasks.log. The kill switch (`run kill`) still stops every trading step. Real money stays
locked in live.py until Nov 11 and your own typed unlock; these files never unlock anything.

Create them once: double-click tasks\install_schedules.cmd. It creates the three schedules (schtasks), then runs
install_schedules.ps1, which changes three of Windows' defaults for them (2026-10-23):
- **Runs on battery.** By default Windows does not start a schedule while a laptop is unplugged, and stops it when
  the charger is pulled out.
- **Makes up a missed run.** By default a run missed while the PC was off or asleep is skipped. Now it starts as soon
  as the PC is available. The evening job then still scans only between 8:50 PM and 1:00 AM (scan_window.py). A run
  that starts the next morning only settles, so it cannot replace the evening snapshot of the next day's markets.
- **One copy at a time, with a time limit:** 6 hours for the evening job, 3 for the settle, 2 for the hourly job.
  jobs.py stops waiting (for the network or for another job) half an hour before the limit.

It writes logs\schedules.txt and shows the result; press a key to close the window. Run it again at any time: it
replaces the three schedules. If the settings step fails, the schedules still exist with Windows' defaults, and the
window says so.

Since 2026-10-24 the three files only call jobs.py. It writes logs\tasks.log itself, a line at a time, and runs the
steps:
- **Waits for the network.** The evening job waits as long as the 8:50 PM to 1:00 AM window is open, so waking the
  laptop before 1 AM is enough for that night's scan. The settle waits up to an hour, the hourly job up to 10 minutes.
- **Retries a failed scan** up to 3 times, 5 minutes apart.
- **Takes turns** with the other jobs through joblock.py.
- **Applies install_schedules.ps1's settings by itself**, from the hourly job: once, and again whenever the script
  changes (logs\schedules_applied.txt keeps the script's fingerprint).

Not changed:
- The PC must be on and you must be signed in.
- Only the 8:55 PM Evening scan may wake a sleeping PC (since 2026-10-25), and only if the power plan allows wake
  timers; logs\schedules_settings.txt says whether it does, and the first night's logs\tasks.log shows whether it
  worked (an evening start line at 8:55 PM while the laptop was asleep). This laptop never sleeps when plugged in, so
  the wake matters on battery, and on battery it can wake with the lid closed, even in a bag: it then runs a few
  minutes (the job keeps it awake at most an hour per step, and a few minutes while Wi-Fi reconnects) and may get warm.
  Shut it down or hibernate it before packing it, or set the power plan's Allow wake timers "On battery" to Disable.
  To stop the wake altogether: Task Scheduler, Tradebot, Evening scan, Conditions, clear "Wake the computer to run this
  task" (it comes back if install_schedules.cmd is run again or install_schedules.ps1 changes).
- Nothing needs a password or administrator rights. If schtasks answers "Access is denied", right-click the file and
  choose Run as administrator.

Remove them: `schtasks /Delete /F /TN "Tradebot\Evening scan"` (and the same for the other two).

## What the log shows (2026-10-23)
Each run writes `===== <time> <job>` when it starts and `===== <time> <job> done (exit N)` when it ends. The time
carries its UTC offset, for example `2026-10-23T20:55:01.1234567-04:00`. A start line with no done line means the run
was cut off: the PC slept, or the window was closed. Scan, settle and hourly runs end with one line from freshness.py:
`FRESHNESS: all current (...)`, or which datasets are out of date and what failed. `.\run freshness` shows the full table.
