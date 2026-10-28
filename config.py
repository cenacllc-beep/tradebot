import os
BANKROLL=float(os.getenv("BANKROLL","25"))
KELLY_FRACTION=0.25      # quarter Kelly
MAX_POS_PCT=0.06         # per-trade cap
MAX_OPEN_PCT=0.15        # total open cost+fees (all versions) <= BANKROLL * this
MIN_EDGE=0.08            # flag mispricing > 8 pts
DAILY_LOSS_LIMIT=0.10    # of bankroll
MAX_HOURS_TO_CLOSE=36
MAX_SPREAD=0.06
KALSHI_BASE=os.getenv("KALSHI_BASE","https://api.elections.kalshi.com/trade-api/v2")  # public market data (paper bot); live.py has its own demo/prod addresses
DB=os.getenv("PAPER_DB","paper.db")
LIVE_ENABLED=False       # not used: orders come only from live.py, whose own locks are described in CLAUDE.md section 3a
BLEND=0.5             # fair = BLEND*forecast + (1-BLEND)*market mid (shrinks noisy signals)
WEATHER_SIGMA_F=3.0    # assumed high-temp forecast error (deg F); calibrate from the shadow log
