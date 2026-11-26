# Backup AI status

Generated 2026-11-26 19:19 La Paz (2026-11-26T23:19:03Z UTC). Reads GitHub only; the PC is not reachable from here.

Problems: 0

| Workflow | State | Age (h) | Limit (h) |
|---|---|---|---|
| backup-ai.yml | running | 0.0 | 6.0 |
| live20.yml | ok | 7.2 | 3.0 |
| plan10.yml | manual-only | 309.6 | - |
| plan15.yml | manual-only | 189.6 | - |
| plan16.yml | manual-only | 180.0 | - |
| plan17.yml | manual-only | 180.0 | - |
| plan18.yml | manual-only | 160.3 | - |
| plan19.yml | running | 3.9 | 3.0 |
| plan20.yml | manual-only | 7.2 | - |
| plan5-lip.yml | disabled | - | - |
| probe18.yml | manual-only | 190.7 | - |
| probe19.yml | manual-only | 21.2 | - |
| tradebot-scan.yml | ok | 9.3 | 26.5 |
| tradebot-settle.yml | ok | 21.4 | 26.0 |
| trial-scan-backstop.yml | ok | 9.5 | 27.0 |

| Data | State | Newest commit | Age (h) | Limit (h) |
|---|---|---|---|---|
| research/data/live20 | ok | 2026-11-26T21:30:45Z | 1.8 | 6 |
| research/data/plan19 | inactive | 2026-11-26T03:34:50Z | 19.7 | 3 |
| research/data/plan20 | info | 2026-11-26T19:32:10Z | 3.8 | - |
| research/results | info | 2026-11-26T19:32:10Z | 3.8 | - |
| trial | ok | 2026-11-26T02:04:37Z | 21.2 | 30 |

## Report (model: nvidia/nemotron-3.5-lightning-30b-a3b; advice only)

**Status Report**

**What works:**  
- `backup-ai.yml` just started (age 0 min, limit 360 min).  
- `live20.yml`, `tradebot-scan.yml`, `tradebot-settle.yml`, `trial-scan-backstop.yml` and `trial` data are all `ok` and within their time limits.  
- `research/data/live20` is fresh (1.8 h old, 6 h limit).  

**Stale or over limit:**  
- `live20.yml`: running 433 min vs 180 min limit → likely exceeded allocated time; may be stuck or auto‑cancel didn’t trigger. *Next step:* monitor the run to completion; no PC involvement.  
- `plan19.yml`: manual‑only for ~6.7 days → designed for manual trigger or forgotten. *Next step:* use the GitHub Actions UI to trigger manually if needed.  
- `research/data/plan19`: 19.7 h old, limit 3 h, state `inactive` → data window exceeded, marked inactive. *Next step:* refresh or re‑run the data pull when ready.  
- `plan5-lip.yml`: `disabled` → intentionally off. *Next step:* re‑enable via repository settings if required.  
- `plan10,15,16,17,18,probe18.yml`: manual‑only for 7–13 days → likely waiting for a manual start or paused. *Next step:* trigger manually via the GitHub UI or review the intended schedule.  

**Note:** All issues are within the GitHub repository/Actions; the user’s local PC is not involved.
