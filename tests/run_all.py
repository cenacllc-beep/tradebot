"""Run every automated test:  .\\run test   (or python tests\\run_all.py)
Each test uses fake data in its own temporary folder, never the real paper.db, the backup folders or the network.
Prints PASS/FAIL per test and exits 1 if anything failed."""
import os, sys, subprocess, tempfile, time
HERE=os.path.dirname(os.path.abspath(__file__)); WORK=os.path.dirname(HERE)
TESTS=[("test_fix.py",[],"daily loss stop, migration, clear margin, single-look gate"),
       ("test_started.py",[],"markets whose day has begun are skipped"),
       ("test_rainonly.py",[],"temperature logged but not traded"),
       ("test_end_to_end.py",[],"scan, settle, report and dashboard with fake markets"),
       ("test_shadow.py",[],"shadow tests: limit orders, price moves"),
       ("test_forward.py",[],"forward-test quote window and statistic"),
       ("test_export.py",[],"off-laptop backup export and restore"),
       ("test_fetch.py",[],"past-data collector against a fake Kalshi"),
       ("test_backtest2.py",["edge"],"plan-2 scorer finds a planted edge"),
       ("test_backtest2.py",["null"],"plan-2 scorer finds none when there is none"),
       ("test_plan3.py",["edge"],"PLAN3 tests A and B find planted edges"),
       ("test_plan3.py",["null"],"PLAN3 tests A and B find none when there is none"),
       ("test_plan4.py",["edge"],"PLAN4 copy tests find planted skill"),
       ("test_plan4.py",["null"],"PLAN4 copy tests find none when there is none"),
       ("test_live.py",[],"Kalshi orders against a fake exchange: locks, $25 cap"),
       ("test_kill.py",[],"kill switch: KILL or KILL.txt halts every trading step"),
       ("test_structure.py",[],"market-structure scanner: ladders, bucket sums, fees, order-book confirmation"),
       ("test_longshot.py",[],"favorite/longshot calibration finds a planted bias (exploratory)"),
       ("test_lip.py",[],"PLAN5 test L: liquidity-reward quotes, queue-aware fills, adverse selection, single score"),
       ("test_engines.py",[],"fees and incentives, resolution states, research-only enforcement, convergence view, post-mortems, metrics"),
       ("test_discover.py",[],"market discovery: pagination, combos, deduplication, lifecycle, caches, rate limit"),
       ("test_micro.py",[],"order flow: queue-aware join/improve/cross, planted imbalance signal, planted lead-lag (exploratory)"),
       ("test_combo.py",[],"combos: copula against the exact two-leg formula, implied correlation, out-of-sample report"),
       ("test_tbcommon.py",[],"shared helpers: HTTP retries and rate limit, parsing, statistics, crash-safe JSON files"),
       ("test_audit.py",[],"decision audit ledger, strategy registry, calibration, shadow selector"),
       ("test_marks.py",[],"live prices of open paper trades on the account chart (read-only)"),
       ("test_freshness.py",[],"data freshness checks, scheduled-job results, clock skew, one time zone for reports"),
       ("test_ohlc.py",[],"historical candle checks: anomaly codes, the OHLC audit, PLAN5 L's descriptive candle record"),
       ("test_schedule.py",[],"scheduled runs: evening scan window, job lock, battery and missed-run settings in the installer"),
       ("test_settle.py",[],"settle survives network errors: one unreachable market never loses the others' results"),
       ("test_veto.py",[],"no rain trade when forecast and market are 30+ points apart; Detroit and West Palm Beach priced"),
       ("test_gatelook.py",[],"stop date: the gate judged once and stored; no v3 paper trades after a failed look"),
       ("test_moves.py",[],"renamed temperature series; PLAN5 L sampling moved to GitHub, the PC's copy stops"),
       ("test_learn.py",[],"learning report: pattern screen, read-only"),
       ("test_markets.py",[],"Kalshi vs Polymarket research: retries, fees, prices"),
       ("test_ui.py",[],"every dashboard button and tab (needs Playwright)")]
def main():
    sys.path.insert(0,WORK)
    import core
    if core.kill_file():   # the tests that scan would stop (correctly) and report false failures
        print("The kill switch is ON (%s), so the tests would stop. Run them after .\\run unkill."%core.kill_file().encode("ascii","replace").decode("ascii")); sys.exit(2)
    root=tempfile.mkdtemp(prefix="tradebot_tests_"); fails=0
    for i,(f,extra,what) in enumerate(TESTS):
        out=os.path.join(root,"t%02d"%i)
        env=dict(os.environ,PAPER_DB=os.path.join(out,"paper.db"),TRADEBOT_OFFSITE_BACKUPS=os.path.join(out,"offsite"),PYTHONIOENCODING="utf-8")
        t=time.time(); r=subprocess.run([sys.executable,os.path.join(HERE,f),WORK,out]+extra,capture_output=True,text=True,encoding="utf-8",errors="replace",env=env)
        skipped="SKIPPED" in r.stdout
        st="SKIP" if skipped and r.returncode==0 else ("PASS" if r.returncode==0 else "FAIL")
        print("%s  %-22s %-50s %4.1fs"%(st,f+(" "+extra[0] if extra else ""),what,time.time()-t))
        if st=="FAIL": fails+=1; print("      "+(r.stdout[-800:]+r.stderr[-1500:]).replace("\n","\n      "))
    print("%d of %d tests failed. Temporary files: %s"%(fails,len(TESTS),root) if fails else "All tests passed (temporary files: %s)."%root)
    sys.exit(1 if fails else 0)
if __name__=="__main__": main()
