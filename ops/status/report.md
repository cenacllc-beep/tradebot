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
