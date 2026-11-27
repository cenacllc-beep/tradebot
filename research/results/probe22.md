# PROBE22: Deribit hourly DVOL history (counts only)

Run 2026-11-27T04:13:28Z. research/PLAN22.md section 7. No DVOL value is shown or saved: only counts, timestamps, ranges, SHA-256 hashes and field names. Nothing dated 2026-11-01 or later was requested.

## BTC
- (d) oldest hourly candle: 2021-03-24T00:00:00Z; newest before the cutoff: 2026-10-31T23:00:00Z; 49152 candles in all; stops before the request's start
- paging: 50 pages, page size first 1000 / largest 1000 / smallest 152; continuation moves earlier; stopped: continuation null
- candles not on the hour: 0; gaps over an hour: 0

| month | candles | hours | coverage |
|---|---|---|---|
| 2026-06 | 720 | 720 | 100.0% |
| 2026-07 | 744 | 744 | 100.0% |
| 2026-08 | 744 | 744 | 100.0% |
| 2026-09 | 720 | 720 | 100.0% |
| 2026-10 | 744 | 744 | 100.0% |

- (b) timestamp marks the **start** of the hour (14 of 14 hours judged; matches {'start/minute start': 14, 'start/minute end': 9, 'end/minute start': 0, 'end/minute end': 0})
- (c) revision week 2026-10-01T00:00:00Z to 2026-10-08T00:00:00Z: 168 candles, SHA-256 ae22d51c21e4ca091b02477eb89cd11d0b4ac25f3774b3df55ebbc2b5ea255a9; against earlier runs: **not yet** (needs a run 24+ hours after this one)
- oldest 1-minute candle in the (b) span: 2026-10-15T04:00:00Z (1080 minute candles)
- history rolling? not yet (needs a run 24+ hours later)

## ETH
- (d) oldest hourly candle: 2021-03-24T00:00:00Z; newest before the cutoff: 2026-10-31T23:00:00Z; 49152 candles in all; stops before the request's start
- paging: 50 pages, page size first 1000 / largest 1000 / smallest 152; continuation moves earlier; stopped: continuation null
- candles not on the hour: 0; gaps over an hour: 0

| month | candles | hours | coverage |
|---|---|---|---|
| 2026-06 | 720 | 720 | 100.0% |
| 2026-07 | 744 | 744 | 100.0% |
| 2026-08 | 744 | 744 | 100.0% |
| 2026-09 | 720 | 720 | 100.0% |
| 2026-10 | 744 | 744 | 100.0% |

- (b) timestamp marks the **start** of the hour (14 of 14 hours judged; matches {'start/minute start': 14, 'start/minute end': 6, 'end/minute start': 0, 'end/minute end': 0})
- (c) revision week 2026-10-01T00:00:00Z to 2026-10-08T00:00:00Z: 168 candles, SHA-256 784e0e83c0549a5e4bffb6a6e19c4b171f8cf3793a8293c255982f0bfd3ea79e; against earlier runs: **not yet** (needs a run 24+ hours after this one)
- oldest 1-minute candle in the (b) span: 2026-10-15T04:00:00Z (1080 minute candles)
- history rolling? not yet (needs a run 24+ hours later)

## Fields

Endpoint fields seen: {"candle_lengths": [5], "result": ["continuation", "data"], "top": ["jsonrpc", "result", "testnet", "usDiff", "usIn", "usOut"]}

## For the plan (section 7)
A live DVOL recorder is needed for stage 2 if history is rolling and would not reach back to 2027-01-01 when read on 2027-03-02 (60 days). If the revision check reads "different", the plan is amended before the freeze, or abandoned. The plan records the decision before the freeze.
