"""Probability calibration (added 2026-10-22, platform upgrade phase 5). Read-only measurements, no retraining.

A model that says 70% should be right about 70% of the time. For any list of (predicted probability, outcome) this
gives:
- Brier score and log loss;
- expected calibration error (ECE, by tenths);
- a reliability table: per bin the count, mean prediction, observed frequency and its 95% Wilson interval.
`Calib` turns a strategy's settled history into a conservative win probability for a new candidate. It uses the lower
95% bound of the observed frequency in the candidate's bin, and only with at least min_n settled cases in that bin;
otherwise it says the history is insufficient. Python 3.8+, no dependencies."""
import math
def wilson(k,n,z=1.96):
    """95% Wilson score interval for k successes in n trials: (low, high); (0, 1) when n is 0."""
    if n<=0: return 0.0,1.0
    p=k/n; d=1+z*z/n; c=p+z*z/(2*n); r=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))
    return max(0.0,(c-r)/d),min(1.0,(c+r)/d)
def brier(rows): return sum((p-y)**2 for p,y in rows)/len(rows) if rows else None
def logloss(rows,eps=1e-6):
    return -sum(y*math.log(min(max(p,eps),1-eps))+(1-y)*math.log(1-min(max(p,eps),1-eps)) for p,y in rows)/len(rows) if rows else None
def bin_of(p,k=10): return min(k-1,max(0,int(p*k)))
def reliability(rows,k=10):
    """[(bin, n, mean prediction, observed frequency, low, high)] for non-empty bins."""
    b={}
    for p,y in rows: b.setdefault(bin_of(p,k),[]).append((p,y))
    out=[]
    for i in sorted(b):
        v=b[i]; n=len(v); s=sum(y for _,y in v); lo,hi=wilson(s,n)
        out.append((i,n,sum(p for p,_ in v)/n,s/n,lo,hi))
    return out
def ece(rows,k=10):
    if not rows: return None
    return sum(n*abs(mp-of) for _,n,mp,of,_,_ in reliability(rows,k))/len(rows)
def summary(rows,k=10):
    return dict(n=len(rows),brier=brier(rows),logloss=logloss(rows),ece=ece(rows,k),table=reliability(rows,k))
class Calib:
    """Calibration of a strategy's YES probabilities from its settled history [(p_yes, 1 if YES won else 0)]."""
    def __init__(self,rows,k=10,min_n=30):
        self.rows=list(rows); self.k=k; self.min_n=min_n; self.bins={}
        for p,y in self.rows: self.bins.setdefault(bin_of(p,k),[0,0]); self.bins[bin_of(p,k)][0]+=1; self.bins[bin_of(p,k)][1]+=y
    def conservative(self,p_yes,side):
        """(conservative chance that `side` wins, n in the bin) or (None, n) when the bin has fewer than min_n cases."""
        n,s=self.bins.get(bin_of(p_yes,self.k),(0,0))
        if n<self.min_n: return None,n
        lo,hi=wilson(s,n)
        return (lo if side=="yes" else 1-hi),n
    def interval(self,p_yes,side):
        """(lower, upper, n): the 95% range of how often `side` won in this bin, or (None, None, n) below min_n."""
        n,s=self.bins.get(bin_of(p_yes,self.k),(0,0))
        if n<self.min_n: return None,None,n
        lo,hi=wilson(s,n)
        return (lo,hi,n) if side=="yes" else (1-hi,1-lo,n)
def v3_rain_rows(c):
    """Settled v3 rain markets from obs: (blended YES probability 0.5 x forecast + 0.5 x mid, outcome), one per market."""
    out=[]
    for fc,mid,r in c.execute("select fc,mid,result from obs where version='v3' and market_type='rain' and result in ('yes','no') and fc is not null and mid is not null"):
        out.append((0.5*fc+0.5*mid,1 if r=="yes" else 0))
    return out
