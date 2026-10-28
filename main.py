import argparse
import core, strategy
# wallets / memecoin / sentiment commands from the original project were NOT rebuilt (files lost 2026-10-13).
ap=argparse.ArgumentParser(); ap.add_argument("cmd",choices=["scan","settle","report"])
a=ap.parse_args(); c=core.db()
getattr(strategy,a.cmd)(c)
