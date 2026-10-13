#!/usr/bin/env python3
# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Other ways of staggering walls, run through the same strength model (see README.md).

    python3 tools/strength_sim/explore.py [output.jsonl] [processes]

Each wall can have its own z offset (a fraction of a layer) and its own layer pitch.
A MODEL, not a measurement. Nothing here was printed.
"""
import json
import math
import os
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model as M  # noqa: E402

A = 0.015
H = 0.2
W = 0.45


def build_walls(offsets, pitches, total, h=H, w=W, px=0.005, corner=0.22, walls=5):
    """offsets[d]: how far (fraction of that wall's layer) wall d starts above the bed;
    pitches[d]: layer height of wall d. Walls are laid in order of bead top height,
    lower first, so the nozzle never has to print beside a taller bead than it must."""
    s = w - h * (1.0 - math.pi / 4.0)
    pad = 0.15
    sec = M.Section(pad * 2 + s * walls, total + h, px)
    sec.spacing = s
    sec.h = h
    r = corner * h
    centres = [pad + s * (k + 0.5) for k in range(walls)]
    beads = []
    for d in range(walls):
        p = pitches[d]
        off = offsets[d] * p
        n = int(round(total / p))
        area0 = s * p
        for j in range(1, n + 1):
            if off > 0 and j == 1:
                beads.append((p + off, d, area0 * (1 + offsets[d])))      # fills the gap down to the bed
            elif off > 0 and j == n:
                beads.append((total, d, area0 * (1 - offsets[d])))        # ends level with the others
            else:
                beads.append((j * p + off, d, area0))
    beads.sort(key=lambda b: (round(b[0], 6), b[1] == 0 and 1 or 0, -b[1]))
    for ztop, d, area in beads:
        sec.deposit(centres[d], ztop, area, r, layer=0, depth=d, shifted=False, flow=1.0)
    return sec


PATTERNS = {
    "stock":        dict(offsets=[0, 0, 0, 0, 0], pitches=[H] * 5, total=1.8),
    "brick_half":   dict(offsets=[0, .5, 0, .5, 0], pitches=[H] * 5, total=1.8),
    "brick_quarter": dict(offsets=[0, .25, 0, .25, 0], pitches=[H] * 5, total=1.8),
    "brick_third":  dict(offsets=[0, 1 / 3., 0, 1 / 3., 0], pitches=[H] * 5, total=1.8),
    "three_phase":  dict(offsets=[0, 1 / 3., 2 / 3., 0, 1 / 3.], pitches=[H] * 5, total=1.8),
    "four_phase":   dict(offsets=[0, .25, .5, .75, 0], pitches=[H] * 5, total=1.8),
    "pitch_1.5_alt": dict(offsets=[0, 0, 0, 0, 0], pitches=[H, .3, H, .3, H], total=1.8),
    "pitch_1.5_inner": dict(offsets=[0, 0, 0, 0, 0], pitches=[H, .3, .3, .3, .3], total=1.8),
    "pitch_2_alt":  dict(offsets=[0, 0, 0, 0, 0], pitches=[H, .4, H, .4, H], total=1.8),
}


def run(job):
    t = time.time()
    sec = build_walls(corner=job["corner"], **PATTERNS[job["name"]])
    lat = M.Lattice(sec, a=A, weld=0.5, seed=1, scatter=0.0)
    v = lat.limit_load(job["mode"])
    tot = sum(b["area"] for b in sec.beads[1:])
    return dict(job, value=v, seconds=round(time.time() - t, 1), lost=sec.lost / (tot + sec.lost),
                void=M.void_fraction(sec, 2 * H, sec.top.max() * sec.px - 2 * H))


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "results/explore.jsonl"
    procs = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    done = set()
    if os.path.isfile(out):
        for line in open(out):
            r = json.loads(line)
            done.add((r["name"], r["mode"], r["corner"]))
    todo = [dict(name=n, mode=m, corner=c) for c in (0.22, 0.10) for m in ("z", "x", "shear") for n in PATTERNS
            if (n, m, c) not in done]
    print("%d to do" % len(todo), flush=True)
    with Pool(procs) as pool, open(out, "a") as fh:
        for res in pool.imap_unordered(run, todo, chunksize=1):
            fh.write(json.dumps(res) + "\n")
            fh.flush()
            print(res["name"], res["mode"], res["corner"], round(res["value"], 3), res["seconds"], "s", flush=True)


if __name__ == "__main__":
    main()
