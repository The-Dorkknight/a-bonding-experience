"""Brittle (crack-running) Z pull for the Squish-KeyLoK and wide-bead layouts (13 Oct 2026).
limit_load() is the 'tough' case where every weld holds until all give together; here welds snap one by one,
so a crack can run along a layer line. Three random weld-strength seeds per case (8 % scatter).
Also records how far up and down the broken welds are spread (a crack stuck to one layer line has a small spread).
A MODEL, not a measurement.   Run: python3 brittle.py results/brittle.jsonl 2
"""
from __future__ import print_function
import json, os, sys, time
from multiprocessing import Pool
import numpy as np
import model as M
import explore as E
import keylok as K
import wide as Wd

CASES = dict(K.P)
CASES["wide_1221"] = None


def section(name, corner):
    if name == "wide_1221":
        return Wd.build(Wd.P["wide_1221"], corner=corner)
    return K.build(corner=corner, **K.P[name])


def run(job):
    t = time.time()
    sec = section(job["name"], job["corner"])
    lat = M.Lattice(sec, a=E.A, weld=0.5, seed=job["seed"], scatter=0.08)
    r = lat.pull("z")
    br = r["broken"]
    z = lat.z[lat.bi[br]] if len(br) else np.array([0.0])
    layers_cut = len(set(np.round(z / E.H).astype(int).tolist()))
    return dict(job, value=float(r["strength"]), z_spread=float(np.std(z)), layer_lines_hit=layers_cut,
                seconds=round(time.time() - t, 1))


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "results/brittle.jsonl"
    procs = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    done = set()
    if os.path.isfile(out):
        for l in open(out):
            r = json.loads(l); done.add((r["name"], r["corner"], r["seed"]))
    todo = [dict(name=n, corner=c, seed=s) for c in (0.22, 0.10) for s in (1, 2, 3) for n in CASES
            if (n, c, s) not in done]
    print(len(todo), "to do", flush=True)
    with Pool(procs) as pool, open(out, "a") as fh:
        for r in pool.imap_unordered(run, todo, chunksize=1):
            fh.write(json.dumps(r) + "\n"); fh.flush()
            print(r["name"], r["corner"], r["seed"], round(r["value"], 2), r["layer_lines_hit"], flush=True)

if __name__ == "__main__":
    main()
