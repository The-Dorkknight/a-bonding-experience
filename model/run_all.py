#!/usr/bin/env python3
# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Run every comparison of the wall-pattern strength model and write results.jsonl.

    python3 tools/strength_sim/run_all.py [output-folder] [processes]

Takes roughly an hour on two cores (it carries on where it stopped if run again). Each line of results.jsonl is one calculation.
Read tools/strength_sim/README.md before trusting any number that comes out.
"""
import json
import os
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model as M  # noqa: E402

BASE = dict(walls=5, layers=9, h=0.2, w=0.45, corner=0.22)
A = 0.015            # spring length, mm


def patterns():
    return {
        "stock": dict(pattern="stock"),
        "flat25": dict(pattern="flatlock", amplitude=0.25, first_scale=0.5),
        "flat25full": dict(pattern="flatlock", amplitude=0.25, first_scale=1.0),
        "flat40full": dict(pattern="flatlock", amplitude=0.40, first_scale=1.0),
        "brick": dict(pattern="brick"),
        "brick105": dict(pattern="brick", brick_flow=1.05),
        "brickflat": dict(pattern="brickflat", amplitude=0.25, first_scale=0.5),
    }


def jobs():
    P = patterns()
    out = []

    def add(tag, names, modes, weld=0.5, side_weld=None, kind="limit", seeds=(1,), grip=None, **geo):
        for name in names:
            for mode in modes:
                for seed in seeds:
                    out.append(dict(tag=tag, name=name, mode=mode, weld=weld, side_weld=side_weld,
                                    kind=kind, seed=seed, grip=grip, geo=dict(BASE, **dict(P[name], **geo))))

    three = ("stock", "flat25", "brick")
    add("base", list(P), ("z", "x", "shear"))
    add("corner0.10", three, ("z", "x", "shear"), corner=0.10)
    add("corner0.16", three, ("z", "x", "shear"), corner=0.16)
    add("weld0.35", three, ("z", "x", "shear"), weld=0.35)
    add("weld0.70", three, ("z", "x", "shear"), weld=0.70)
    add("sideweld0.30", three, ("z", "x"), side_weld=0.30)
    for h in (0.16, 0.25, 0.28):
        add("h%.2f" % h, three, ("z", "x"), h=h)
    # a taller wall held further from the break, the one parting.py draws
    add("tall13", three, ("z",), grip=0.8, layers=13)
    add("base", three, ("z",), kind="brittle", seeds=(1, 2, 3))
    add("base", three, ("z",), kind="tough8", seeds=(1, 2, 3))
    return out


_cache = {}


def run(job):
    t = time.time()
    key = json.dumps(job["geo"], sort_keys=True)
    if key not in _cache:
        _cache.clear()
        _cache[key] = M.build(**job["geo"])
    sec = _cache[key]
    lat = M.Lattice(sec, a=A, weld=job["weld"], side_weld=job["side_weld"], seed=job["seed"],
                    scatter=0.0 if job["kind"] == "limit" else 0.08)
    if job["kind"] == "limit":
        value = lat.limit_load(job["mode"], grip=job.get("grip"))
    elif job["kind"] == "brittle":
        value = lat.pull(job["mode"])["strength"]
    else:
        value = lat.pull(job["mode"], ductility=8.0)["strength"]
    h = job["geo"]["h"]
    total = sum(b["area"] for b in sec.beads[1:])
    res = dict(job, value=value, seconds=round(time.time() - t, 1),
               void=M.void_fraction(sec, 2 * h, sec.top.max() * sec.px - 2 * h),
               lost=sec.lost / (total + sec.lost))
    return res


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    procs = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "results.jsonl")
    done = set()
    if os.path.isfile(path):
        for line in open(path):
            r = json.loads(line)
            done.add(json.dumps([r["tag"], r["name"], r["mode"], r["kind"], r["seed"]]))
    todo = [j for j in jobs() if json.dumps([j["tag"], j["name"], j["mode"], j["kind"], j["seed"]]) not in done]
    # group by geometry so each worker builds each wall once
    todo.sort(key=lambda j: json.dumps(j["geo"], sort_keys=True))
    print("%d calculations to do" % len(todo), flush=True)
    with Pool(procs) as pool, open(path, "a") as fh:
        for res in pool.imap_unordered(run, todo, chunksize=1):
            fh.write(json.dumps(res) + "\n")
            fh.flush()
            print("%-12s %-10s %-5s %-7s seed %d -> %.3f  (%.0fs)" % (
                res["tag"], res["name"], res["mode"], res["kind"], res["seed"], res["value"], res["seconds"]), flush=True)


if __name__ == "__main__":
    main()
