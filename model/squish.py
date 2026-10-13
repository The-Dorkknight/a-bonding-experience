"""Squish-LoK idea (13 Oct 2026): some beads are laid last in their layer with extra flow, at the SAME
layer height, so the extra plastic is pushed sideways into the notches left by neighbouring rounded beads.
A MODEL, not a measurement. Nothing here was printed.   Run: python3 squish.py results/squish.jsonl 2
"""
from __future__ import print_function
import json, math, os, sys, time
from multiprocessing import Pool
import model as M
import explore as E

H, W = E.H, E.W


def build(flow, total=1.8, corner=0.22, walls=5, offsets=None):
    """flow(d, j) -> flow multiplier of wall d, layer j (1-based). Beads with flow > 1 are laid last in their layer."""
    s = W - H * (1.0 - math.pi / 4.0)
    sec = M.Section(0.3 + s * walls, total + H, 0.005)
    sec.spacing, sec.h = s, H
    r = corner * H
    cs = [0.15 + s * (k + 0.5) for k in range(walls)]
    n = int(round(total / H))
    beads = []
    for d in range(walls):
        off = (offsets[d] if offsets else 0)
        for j in range(1, n + 1):
            f = flow(d, j)
            if off > 0 and j == 1:
                beads.append((H + off * H, d, s * H * (1 + off) * f, f))
            elif off > 0 and j == n:
                beads.append((total, d, s * H * (1 - off) * f, f))
            else:
                beads.append((j * H + off * H, d, s * H * f, f))
    beads.sort(key=lambda b: (round(b[0], 6), b[3] > 1.0, b[1]))
    for zt, d, a, f in beads:
        sec.deposit(cs[d], zt, a, r, layer=0, depth=d, shifted=False, flow=f)
    return sec, sum(b[2] for b in beads) / sum(b[2] / b[3] for b in beads)

P = {
 "stock":          dict(flow=lambda d, j: 1.0),
 "mid_f115":       dict(flow=lambda d, j: 1.15 if d == 2 else 1.0),
 "mid_f130":       dict(flow=lambda d, j: 1.30 if d == 2 else 1.0),
 "pair_f115":      dict(flow=lambda d, j: 1.15 if d in (1, 3) else 1.0),
 "pair_f130":      dict(flow=lambda d, j: 1.30 if d in (1, 3) else 1.0),
 "layer2_f130":    dict(flow=lambda d, j: 1.30 if j % 2 == 0 else 1.0),
 "layer3_f130":    dict(flow=lambda d, j: 1.30 if j % 3 == 0 else 1.0),
 "stagger3_f130":  dict(flow=lambda d, j: 1.30 if (j + d) % 3 == 0 else 1.0),
 "shell_l2_f130":  dict(flow=lambda d, j: 1.30 if (d in (0, 1, 3, 4) and j % 2 == 0) else 1.0),
 "brick_pair_f115": dict(flow=lambda d, j: 1.15 if d in (1, 3) else 1.0, offsets=[0, .5, 0, .5, 0]),
}


def run(job):
    t = time.time()
    sec, extra = build(corner=job["corner"], **P[job["name"]])
    lat = M.Lattice(sec, a=E.A, weld=0.5, seed=1, scatter=0.0)
    v = lat.limit_load(job["mode"])
    tot = sum(b["area"] for b in sec.beads[1:])
    return dict(job, value=float(v), extra_plastic=extra, lost=float(sec.lost / (tot + sec.lost)),
                void=M.void_fraction(sec, 2 * H, sec.top.max() * sec.px - 2 * H), seconds=round(time.time() - t, 1))


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "results/squish.jsonl"
    procs = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    done = set()
    if os.path.isfile(out):
        for l in open(out):
            r = json.loads(l); done.add((r["name"], r["mode"], r["corner"]))
    todo = [dict(name=n, mode=m, corner=c) for c in (0.22, 0.10) for m in ("z", "x", "shear") for n in P
            if (n, m, c) not in done]
    print(len(todo), "to do", flush=True)
    with Pool(procs) as pool, open(out, "a") as fh:
        for r in pool.imap_unordered(run, todo, chunksize=1):
            fh.write(json.dumps(r) + "\n"); fh.flush()
            print(r["name"], r["mode"], r["corner"], round(r["value"], 2), "void", round(r["void"], 3), flush=True)

if __name__ == "__main__":
    main()
