# Backup AI status

Generated 2026-11-26 15:22 La Paz (2026-11-26T19:22:55Z UTC). Reads GitHub only; the PC is not reachable from here.

**NVIDIA_API_KEY is missing:** non-AI status check and re-runs only (add it as a repository secret).

Problems: 3
- live20.yml: no run for 3.3 h (schedule allows 3.0 h)
- plan19.yml: no run for 6.2 h (schedule allows 2.3 h)
- plan5-lip.yml: no run for 20.6 h (schedule allows 2.2 h)

| Workflow | State | Age (h) | Limit (h) |
|---|---|---|---|
| backup-ai.yml | running | 0.0 | 6.0 |
| live20.yml | stale | 3.3 | 3.0 |
| plan10.yml | manual-only | 305.6 | - |
| plan15.yml | manual-only | 185.7 | - |
| plan16.yml | manual-only | 176.1 | - |
| plan17.yml | manual-only | 176.1 | - |
| plan18.yml | manual-only | 156.4 | - |
| plan19.yml | stale | 6.2 | 2.3 |
| plan20.yml | running | 3.3 | - |
| plan5-lip.yml | stale | 20.6 | 2.2 |
| probe18.yml | manual-only | 186.8 | - |
| probe19.yml | manual-only | 17.2 | - |
| tradebot-scan.yml | ok | 5.3 | 26.5 |
| tradebot-settle.yml | ok | 17.4 | 26.0 |
| trial-scan-backstop.yml | ok | 5.6 | 27.0 |

| Data | State | Newest commit | Age (h) | Limit (h) |
|---|---|---|---|---|
| research/data/live20 | ok | 2026-11-26T19:05:19Z | 0.3 | 6 |
| research/data/plan19 | inactive | 2026-11-26T03:34:50Z | 15.8 | 3 |
| research/data/plan20 | info | - | - | - |
| research/results | info | 2026-11-26T16:06:12Z | 3.3 | - |
| trial | ok | 2026-11-26T02:04:37Z | 17.3 | 30 |
