"""Squish-KeyLoK idea (13 Oct 2026): mixed-width beads, seams moved sideways on alternate layers, and a
deliberate small sideways gap (0.05-0.1 mm) left at each inner seam. The bead in the next layer sits centred
over that gap and is over-extruded by the gap's volume, so it pushes a 'key' down into the slot, across the
layer line. All layers stay 0.2 mm. Widths in units of one normal bead pitch.
A MODEL, not a measurement.   Run: python3 keylok.py results/keylok.jsonl 2
"""
from __future__ import print_function
import json, math, os, sys, time
from multiprocessing import Pool
import model as M
import explore as E

H, W = E.H, E.W
A_, B_ = [1, 2, 2, 1], [1, 1, 2, 1, 1]          # seams 1,3,5 and 1,2,4,5: each inner seam sits under a bead centre


def seams(L):
    out, x = [], 0
    for u in L[:-1]:
        x += u
        out.append(x)
    return out


def build(layouts, gap=0.0, fill=1.0, total=1.8, corner=0.22):
    s = W - H * (1.0 - math.pi / 4.0)
    units = sum(layouts[0])
    sec = M.Section(0.3 + s * units, total + H, 0.005)
    sec.spacing, sec.h = s, H
    r = corner * H
    n = int(round(total / H))
    x0 = 0.15
    keyed = lambda L: [k for k in seams(L) if 1 < k < units - 1]     # leave the outer shell seams closed
    for j in range(1, n + 1):
        L = layouts[(j - 1) % len(layouts)]
        below = layouts[(j - 2) % len(layouts)] if j > 1 else None
        gaps = keyed(L) if gap > 0 and j < n else []
        open_below = keyed(below) if (below and gap > 0) else []
        left = 0
        beads = []
        for d, u in enumerate(L):
            a, b = left, left + u
            xa = x0 + s * a + (gap / 2.0 if a in gaps else 0.0)
            xb = x0 + s * b - (gap / 2.0 if b in gaps else 0.0)
            area = (xb - xa) * H
            n_slots = sum(1 for k in open_below if a < k < b)              # slots this bead sits over
            area += fill * n_slots * gap * H
            beads.append(((xa + xb) / 2.0, area, d, n_slots))
            left = b
        beads.sort(key=lambda t: t[3])            # beads that key into slots last, so neighbours are in place
        for xc, area, d, k in beads:
            sec.deposit(xc, j * H, area, r, layer=j, depth=d, shifted=False, flow=1.0)
    return sec

P = {
    "stock_6":          dict(layouts=[[1] * 6]),
    "xy_nogap":         dict(layouts=[A_, B_]),
    "key_0.05":         dict(layouts=[A_, B_], gap=0.05),
    "key_0.10":         dict(layouts=[A_, B_], gap=0.10),
    "key_0.10_nofill":  dict(layouts=[A_, B_], gap=0.10, fill=0.0),
    "key_0.10_fill150": dict(layouts=[A_, B_], gap=0.10, fill=1.5),
}


def run(job):
    t = time.time()
    sec = build(corner=job["corner"], **P[job["name"]])
    lat = M.Lattice(sec, a=E.A, weld=0.5, seed=1, scatter=0.0)
    v = lat.limit_load(job["mode"])
    tot = sum(b["area"] for b in sec.beads[1:])
    return dict(job, value=float(v), lost=float(sec.lost / (tot + sec.lost)),
                void=M.void_fraction(sec, 2 * H, sec.top.max() * sec.px - 2 * H), seconds=round(time.time() - t, 1))


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "results/keylok.jsonl"
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
