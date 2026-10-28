"""Meta selector, accuracy first (added 2026-10-22, platform upgrade phases 3-4, 19, 27-28). SHADOW ONLY: it never
opens, changes or blocks a trade. Beside every v3 candidate it records what an accuracy-first selector would do and why,
so its rule can be judged forward on the same markets.

A candidate must pass all of these, with thresholds frozen per experiment in EXPERIMENTS:
- data fresh enough;
- spread acceptable;
- model and market not wildly apart (a big gap means "investigate", not "bet more");
- enough settled history in the candidate's probability bin to calibrate it;
- the conservative chance that the chosen side wins (lower 95% bound from that history) above a floor;
- positive expected value after fees when computed with that conservative chance.
Otherwise it ABSTAINs, with the first failed check as the reason. Sizing (research): quarter Kelly on the conservative
chance, never on the point estimate. Python 3.8+."""
EXPERIMENTS={
 "accuracy_first.v1":dict(frozen="2026-10-22",min_q_cons=0.60,min_net_ev_cons=0.01,max_spread=0.06,max_gap=0.30,
                          max_data_age_s=3*3600,min_bin_n=30,kelly=0.25,max_pos_pct=0.06,max_cluster_pct=0.06),
}
DEFAULT="accuracy_first.v1"
def evaluate(cand,calib,exp=DEFAULT):
    """cand: side, p_win (the strategy's blended chance for its side), p_yes (blended YES chance), p_model_yes (raw),
    mid, price (what the side costs), fee_pc (fee per contract), spread, data_age_s (None if unknown), and optionally
    cluster_open (dollars already at risk in the market's risk cluster) with bankroll.
    Returns a dict with action TRADE_YES / TRADE_NO / ABSTAIN, reason, and the numbers behind it."""
    E=EXPERIMENTS[exp]; out=dict(experiment=exp,action="ABSTAIN",reason=None,q_cons=None,net_ev_cons=None,bin_n=None,stake_frac=None)
    def no(r): out["reason"]=r; return out
    if cand.get("price") is None or not 0<cand["price"]<1: return no("NO_QUOTE")
    age=cand.get("data_age_s")
    if age is not None and age>E["max_data_age_s"]: return no("STALE_DATA")
    if cand.get("spread") is not None and cand["spread"]>E["max_spread"]+1e-9: return no("WIDE_SPREAD")
    if cand.get("p_model_yes") is not None and cand.get("mid") is not None and abs(cand["p_model_yes"]-cand["mid"])>E["max_gap"]:
        return no("ANOMALOUS_MODEL_MARKET_GAP")
    if cand.get("cluster_open") is not None and cand.get("bankroll") and cand["cluster_open"]>=E["max_cluster_pct"]*cand["bankroll"]-1e-9:
        return no("CORRELATION_LIMIT")
    q,n=calib.conservative(cand["p_yes"],cand["side"]) if calib else (None,0)
    out["bin_n"]=n
    if q is None: return no("INSUFFICIENT_HISTORY")
    out["q_cons"]=q
    if q<E["min_q_cons"]: return no("LOW_WIN_PROBABILITY")
    ev=q-cand["price"]-(cand.get("fee_pc") or 0); out["net_ev_cons"]=ev
    if ev<E["min_net_ev_cons"]: return no("NEGATIVE_NET_EV")
    out["stake_frac"]=min((q-cand["price"])/(1-cand["price"])*E["kelly"],E["max_pos_pct"])
    out["action"]="TRADE_YES" if cand["side"]=="yes" else "TRADE_NO"; out["reason"]="TRADE"
    return out
