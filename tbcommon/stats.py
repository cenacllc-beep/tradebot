"""Small statistics used across research reports. Plain Python (the PC has no numpy or scipy)."""
import math


def wilson(k, n, z=1.96):
    """Wilson score interval for k successes in n trials: (low, high); (0, 1) when n is 0."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - r) / d), min(1.0, (c + r) / d)


def cl_mean_se(vals):
    """vals: [(value, cluster)] -> (mean over all values, SE clustered by cluster).
    (None, None) when empty; the SE is None with fewer than two clusters."""
    n = len(vals)
    if n == 0:
        return None, None
    m = sum(v for v, _ in vals) / n
    g = {}
    for v, c in vals:
        g[c] = g.get(c, 0.0) + (v - m)
    clusters = len(g)
    if clusters < 2:
        return m, None
    return m, math.sqrt(clusters / (clusters - 1) * sum(x * x for x in g.values())) / n
