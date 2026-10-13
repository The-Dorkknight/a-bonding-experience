"""Pinned sparse infill ("sparse squish", 13 Oct 2026).

2-D vertical section through the middle of a row of grid-infill cells. Grid infill prints lines both ways
on every layer, so the cells stack into open vertical channels; in this section the lines that run across
the section show up as one bead per cell pitch, and the channels are the gaps between them.
Every `every` layers, the nozzle stops over one set of channels (A and B alternate, as ORNL did) and
extrudes a pin: plastic that pools at the bottom of the channel and fills it from below.
`fill` is the share of the open channel under the nozzle that each pin fills.
Infill core only: no walls or skins. A MODEL, not a measurement.
Run: python3 sparse.py results/sparse.jsonl 2
"""
from __future__ import print_function
import json, math, os, sys, time
from multiprocessing import Pool
import numpy as np
import model as M

H, W = 0.2, 0.45
S = W - H * (1.0 - math.pi / 4.0)


def build(density, pins=False, fill=0.8, every=4, layers=16, cells=2, corner=0.22, px=0.01,
          keep=None, cap=None):
    """keep=None: each pin fills `fill` of the open channel (ORNL-style). keep=k: each pin tops the
    channel up to k layers below the nozzle, like the PinLoK engine; cap = most mm3 per pin (the
    channel is taken as square in 3-D, so a pin rises at most cap / width**2)."""
    p = 2.0 * S / density                                  # grid: two line sets per layer
    pad = 0.3
    sec = M.Section(2 * pad + p * cells, layers * H + 0.4, px)
    sec.spacing, sec.h = S, H
    r = corner * H
    lines = [pad + p * (k + 0.5) for k in range(cells + 1)][:cells]
    lines = [pad + S / 2.0 + p * k for k in range(cells + 1)]
    chans = [(lines[k] + S / 2.0, lines[k + 1] - S / 2.0) for k in range(cells)]
    n = 0
    for j in range(1, layers + 1):
        for x in lines:
            sec.deposit(x, j * H, S * H, r, layer=j, depth=n % 7, shifted=False, flow=1.0)
            n += 1
        last = (j == layers)
        if pins and (j % every == 0 or last):
            group = (j // every) % 2
            for k, (ca, cb) in enumerate(chans):
                if k % 2 != group and not last:
                    continue
                cx = 0.5 * (ca + cb)
                width = cb - ca
                floor = sec.top[int(round(cx / px))] * px
                # the pin fills `fill` of the open channel under the nozzle (steady state: a few layers
                # stay open at the top after each pin). On the last layer every channel is capped full,
                # as if the part went on, so the test measures the middle of the infill.
                if last:
                    zt = j * H
                elif keep is not None:
                    zt = j * H - keep * H
                    if cap is not None:
                        zt = min(zt, floor + cap / (width * width))
                else:
                    zt = floor + fill * (j * H - floor)
                if zt <= floor + px:
                    continue
                sec.deposit(cx, zt, (zt - floor) * width, r, layer=j, depth=100 + k, shifted=False, flow=1.0)
                n += 1
    return sec, p


def mass(sec):
    return float((sec.ids > 0).sum()) * sec.px ** 2


CASES = {
    # same file, same settings, same baseline: results/pinlok_modes.jsonl
    "solid":            dict(density=2.0 * S / (S + 0.002), cells=10),
    "d35":              dict(density=0.35),
    "d40":              dict(density=0.40),
    "d35_ornl_f80":     dict(density=0.35, pins=True, fill=0.8, every=4),
    "d35_potato":       dict(density=0.35, pins=True, every=2, keep=1, cap=3.0),
    "d35_balanced":     dict(density=0.35, pins=True, every=4, keep=2, cap=8.0),
    "d35_performance":  dict(density=0.35, pins=True, every=4, keep=1, cap=12.0),
    "d40_potato":       dict(density=0.40, pins=True, every=2, keep=1, cap=3.0),
    "d40_balanced":     dict(density=0.40, pins=True, every=4, keep=2, cap=8.0),
    "d40_performance":  dict(density=0.40, pins=True, every=4, keep=1, cap=12.0),
    # pin tops half-way through a layer, so a pin's joint never lines up with an infill layer line
    "d35_potato_half":  dict(density=0.35, pins=True, every=2, keep=1.5, cap=3.0),
    "d35_balanced_half": dict(density=0.35, pins=True, every=4, keep=2.5, cap=8.0),
    "d35_perf_half":    dict(density=0.35, pins=True, every=4, keep=1.5, cap=12.0),
}


def run(job):
    t = time.time()
    sec, p = build(corner=job["corner"], **CASES[job["name"]])
    lat = M.Lattice(sec, a=0.03, weld=0.5, seed=job.get("seed", 1), scatter=0.08 if job["mode"] == "brittle" else 0.0)
    if job["mode"] == "brittle":
        v = lat.pull("z")["strength"]
    else:
        v = lat.limit_load(job["mode"])
    m = mass(sec)
    return dict(job, value=float(v), mass=m, pitch=p, seconds=round(time.time() - t, 1))


def density(sec):
    ids = sec.ids > 0
    cols = np.where(ids.any(axis=0))[0]
    rows = np.where(ids.any(axis=1))[0]
    return float(ids[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1].mean())


def run2(job):
    t = time.time()
    sec, p = build(**CASES[job["name"]])
    lat = M.Lattice(sec, a=0.03, weld=0.5, seed=job["seed"], scatter=0.08 if job["mode"] == "brittle" else 0.0)
    v = lat.pull("z")["strength"] if job["mode"] == "brittle" else lat.limit_load("z")
    return dict(job, value=float(v), density=density(sec), seconds=round(time.time() - t, 1))


def main():
    """Every case: the tough limit in Z (seed 1) and the brittle pull in Z (seeds 1-3), corner 0.22,
    all against the solid case in the same file."""
    out = sys.argv[1] if len(sys.argv) > 1 else "results/pinlok_modes.jsonl"
    procs = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    done = set()
    if os.path.isfile(out):
        for l in open(out):
            r = json.loads(l); done.add((r["name"], r["mode"], r["seed"]))
    todo = [dict(name=n, mode=m, seed=s) for n in CASES for (m, s) in (("z", 1), ("brittle", 1), ("brittle", 2), ("brittle", 3))
            if (n, m, s) not in done]
    print(len(todo), "to do", flush=True)
    with Pool(procs) as pool, open(out, "a") as fh:
        for r in pool.imap_unordered(run2, todo, chunksize=1):
            fh.write(json.dumps(r) + "\n"); fh.flush()
            print(r["name"], r["mode"], r["seed"], round(r["value"], 2), r["seconds"], "s", flush=True)
    summary(out)


def summary(out="results/pinlok_modes.jsonl"):
    import statistics as st
    R = {}
    for l in open(out):
        r = json.loads(l)
        R.setdefault((r["name"], r["mode"]), []).append(r)
    base_z = st.mean(r["value"] for r in R[("solid", "z")])
    base_b = st.mean(r["value"] for r in R[("solid", "brittle")])
    print("%-17s %8s %10s %10s" % ("case", "density", "tough Z", "brittle Z"))
    for n in CASES:
        if (n, "z") not in R or (n, "brittle") not in R:
            continue
        z = st.mean(r["value"] for r in R[(n, "z")])
        b = st.mean(r["value"] for r in R[(n, "brittle")])
        print("%-17s %7.0f%% %+9.0f%% %+9.0f%%" % (n, 100 * R[(n, "z")][0]["density"], 100 * (z / base_z - 1), 100 * (b / base_b - 1)))


if __name__ == "__main__":
    main()
