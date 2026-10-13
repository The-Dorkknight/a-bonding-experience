"""Wide flat inner beads (13 Oct 2026): outer beads stay one nozzle width, inner beads are 2-4x wider,
all 0.2 mm high, optionally with the inner seams moved sideways on alternate layers (an XY brick bond,
no height differences). Widths are in units of one normal bead pitch. A MODEL, not a measurement.
Run: python3 wide.py results/wide.jsonl 2
"""
from __future__ import print_function
import json, math, os, sys, time
from multiprocessing import Pool
import model as M
import explore as E

H, W = E.H, E.W


def build(layouts, total=1.8, corner=0.22):
    """layouts: list of width lists; layer j uses layouts[(j-1) % len(layouts)]."""
    s = W - H * (1.0 - math.pi / 4.0)
    units = sum(layouts[0])
    assert all(abs(sum(L) - units) < 1e-9 for L in layouts)
    sec = M.Section(0.3 + s * units, total + H, 0.005)
    sec.spacing, sec.h = s, H
    r = corner * H
    n = int(round(total / H))
    for j in range(1, n + 1):
        L = layouts[(j - 1) % len(layouts)]
        x = 0.15
        for d, u in enumerate(L):
            sec.deposit(x + s * u / 2.0, j * H, s * u * H, r, layer=j, depth=d, shifted=False, flow=1.0)
            x += s * u
    return sec

P = {
    "stock_6":         [[1, 1, 1, 1, 1, 1]],
    "wide_1.33":       [[1, 4 / 3., 4 / 3., 4 / 3., 1]],
    "wide_1221":       [[1, 2, 2, 1]],
    "wide_1.5":        [[1, 1.5, 1.5, 1], [1, 1.5, 1.5, 1]],
    "wide_141":        [[1, 4, 1]],
    "xy_1221_11211":   [[1, 2, 2, 1], [1, 1, 2, 1, 1]],
    "xy_1311_1131":    [[1, 3, 1, 1], [1, 1, 3, 1]],
    "xy_111111_1221":  [[1, 1, 1, 1, 1, 1], [1, 2, 2, 1]],
}


def run(job):
    t = time.time()
    sec = build(P[job["name"]], corner=job["corner"])
    lat = M.Lattice(sec, a=E.A, weld=0.5, seed=1, scatter=0.0)
    v = lat.limit_load(job["mode"])
    tot = sum(b["area"] for b in sec.beads[1:])
    return dict(job, value=float(v), lost=float(sec.lost / (tot + sec.lost)),
                void=M.void_fraction(sec, 2 * H, sec.top.max() * sec.px - 2 * H), seconds=round(time.time() - t, 1))


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "results/wide.jsonl"
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
