#!/usr/bin/env python3
# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Turn results.jsonl from run_all.py into a table (and, with matplotlib, a chart).

    python3 tools/strength_sim/summarise.py results-folder [chart.png]
"""
import json
import os
import sys
from collections import defaultdict

MODES = (("z", "Pulled apart across the layers"), ("shear", "Layers slid over each other"),
         ("x", "Walls pulled apart sideways"))


def load(folder):
    rows = [json.loads(line) for line in open(os.path.join(folder, "results.jsonl"))]
    table = defaultdict(list)
    for r in rows:
        table[(r["tag"], r["kind"], r["mode"], r["name"])].append(r["value"])
    mean = dict((k, sum(v) / len(v)) for k, v in table.items())
    return rows, mean


def change(mean, tag, kind, mode, name):
    """Percent change against the normal wall in the same calculation, or None."""
    a = mean.get((tag, kind, mode, name))
    b = mean.get((tag, kind, mode, "stock"))
    if a is None or b is None:
        return None
    return 100.0 * (a / b - 1.0)


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    rows, mean = load(folder)
    tags = sorted(set(r["tag"] for r in rows), key=lambda t: (t != "base", t))
    names = []
    for r in rows:
        if r["name"] not in names and r["name"] != "stock":
            names.append(r["name"])
    print("Change against the normal wall, percent. 'limit' = tough welds, 'brittle' = glass-like welds.\n")
    for tag in tags:
        for kind in ("limit", "tough8", "brittle"):
            for mode, _label in MODES:
                cells = [(n, change(mean, tag, kind, mode, n)) for n in names]
                cells = [(n, c) for n, c in cells if c is not None]
                if cells:
                    print("%-13s %-8s %-6s " % (tag, kind, mode) + "  ".join("%s %+6.1f" % (n, c) for n, c in cells))
    voids = {}
    for r in rows:
        if r["tag"] == "base":
            voids[r["name"]] = (r["void"], r["lost"])
    print("\nEmpty space inside the wall (base case): " + ", ".join("%s %.1f%%" % (n, 100 * v[0]) for n, v in voids.items()))
    print("Plastic that found no room: " + ", ".join("%s %.1f%%" % (n, 100 * v[1]) for n, v in voids.items()))
    if len(sys.argv) > 2:
        chart(mean, tags, sys.argv[2])


def chart(mean, tags, png):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    INK, SECOND, MUTED, SURFACE, GRID = "#0b0b0b", "#52514e", "#898781", "#fcfcfb", "#e1e0d9"
    series = (("flat25", "Flat fat/thin walls (sister project FlatLock)", "#2a78d6"),
              ("brick", "Staggered half a layer (what Shift-LoK does)", "#eb6834"))
    fig, ax = plt.subplots(figsize=(9.6, 5.0), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    width = 0.34
    for si, (name, label, colour) in enumerate(series):
        for mi, (mode, _label) in enumerate(MODES):
            base = change(mean, "base", "limit", mode, name)
            if base is None:
                continue
            # spread across every other assumption that was tried
            spread = [change(mean, t, k, mode, name) for t in tags for k in ("limit", "tough8", "brittle")]
            spread = [v for v in spread if v is not None]
            x = mi + (si - 0.5) * (width + 0.04)
            ax.bar(x, base, width=width, color=colour, label=label if mi == 0 else None, zorder=3)
            ax.plot([x, x], [min(spread), max(spread)], color=INK, lw=1.4, zorder=4)
            for end in (min(spread), max(spread)):
                ax.plot([x - 0.05, x + 0.05], [end, end], color=INK, lw=1.4, zorder=4)
            ax.text(x + 0.07, max(base, 0) + 1.2, "%+.0f%%" % base, ha="left", va="bottom", color=INK, fontsize=10)
    ax.axhline(0, color=MUTED, lw=1.0, zorder=2)
    ax.axhspan(10, 14, xmin=0.0, xmax=1.0 / len(MODES), color="#eb6834", alpha=0.13, zorder=1)
    ax.text(-0.46, 15.0, "measured on real prints, staggered:\n+10 to +14 % (CNC Kitchen)", color=SECOND, fontsize=8.5, va="bottom")
    ax.set_xticks(range(len(MODES)))
    ax.set_xticklabels([label for _m, label in MODES], color=INK, fontsize=10.5)
    ax.set_ylabel("strength compared with normal walls", color=SECOND, fontsize=10)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _p: "%+d%%" % v if v else "same"))
    ax.grid(axis="y", color=GRID, lw=0.8, zorder=0)
    ax.tick_params(colors=MUTED, length=0)
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.legend(loc="upper left", bbox_to_anchor=(0.36, 1.0), frameon=False, fontsize=10, labelcolor=INK)
    ax.set_title("Strength model: change compared with normal walls",
                 loc="left", color=INK, fontsize=13, pad=14)
    fig.text(0.012, 0.012, "Bars: base assumptions (welds half as strong as solid plastic, tough welds). "
             "Black lines: range over every other assumption tried. A model, not a measurement.",
             color=MUTED, fontsize=8.2)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(png, dpi=170, facecolor=SURFACE)
    print("wrote", png)


if __name__ == "__main__":
    main()
