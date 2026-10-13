#!/usr/bin/env python3
# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Draw where the model says each wall pattern parts when pulled across its layers.

    python3 tools/strength_sim/parting.py out.png

Takes a few minutes. Needs numpy, scipy and matplotlib.
A model, not a measurement: read tools/strength_sim/README.md first.
"""
import os
import sys

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import model as M  # noqa: E402

INK, SECOND, MUTED, SURFACE = "#0b0b0b", "#52514e", "#898781", "#fcfcfb"
STAYS, MOVES, WELD, PART = "#e6e5df", "#b7d3f6", "#898781", "#eb6834"
PANELS = (("stock", "Normal walls"), ("flatlock", "Flat fat/thin walls (FlatLock)"),
          ("brick", "Staggered half a layer (Shift-LoK)"))
H = 0.2
GRIP = 4 * H


def rgb(colour):
    return np.array([int(colour[i:i + 2], 16) for i in (1, 3, 5)]) / 255.0


def panel(pattern):
    sec = M.build(pattern, corner=0.22, layers=13, h=H)
    lat = M.Lattice(sec, a=0.015, weld=0.5, seed=1, scatter=0.0)
    load = lat.limit_load("z", grip=GRIP)
    ids = sec.ids
    solid = ids > 0
    weld = np.zeros_like(solid)
    weld[:, 1:] |= (ids[:, 1:] != ids[:, :-1]) & solid[:, 1:] & solid[:, :-1]
    weld[1:, :] |= (ids[1:, :] != ids[:-1, :]) & solid[1:, :] & solid[:-1, :]
    weld = ndimage.binary_dilation(weld, iterations=1)
    # which part moves away: the LP's dual values are the motion at collapse
    nj, ni = lat.shape
    moved = np.nan_to_num(lat.limit_motion[1::2].reshape(nj, ni), nan=0.0) < -0.5
    zz = (np.arange(sec.nz) + 0.5) * sec.px
    xx = (np.arange(sec.nx) + 0.5) * sec.px
    dz = lat.a * np.sqrt(3) / 2
    jj = np.clip((zz / dz - 0.5).round().astype(int), 0, nj - 1)
    ii = np.clip((xx / lat.a - 0.5).round().astype(int), 0, ni - 1)
    mv = moved[np.ix_(jj, ii)]
    # voids and outside air take the value of the nearest plastic
    idx = ndimage.distance_transform_edt(~solid, return_distances=False, return_indices=True)
    mv = mv[idx[0], idx[1]]
    used = np.zeros(lat.n, bool)
    used[lat.bi] = True
    used[lat.bj] = True
    top = lat.z[used].max() - GRIP
    mv |= zz[:, None] > top            # the gripped top moves as well
    mv = ndimage.binary_closing(mv, iterations=4) | mv
    img = np.ones(ids.shape + (3,))
    img[solid] = rgb(STAYS)
    img[solid & mv] = rgb(MOVES)
    img[weld] = rgb(WELD)
    cut = np.zeros_like(solid)
    cut[1:, :] |= mv[1:, :] != mv[:-1, :]
    cut[:, 1:] |= mv[:, 1:] != mv[:, :-1]
    cut &= zz[:, None] < top - 0.02
    # only inside the wall: the ragged free edges are not a parting surface
    inside = ndimage.binary_erosion(ndimage.binary_closing(solid, iterations=10), iterations=6)
    cut = ndimage.binary_dilation(cut & inside, iterations=3) & ndimage.binary_dilation(solid, iterations=2)
    img[cut] = rgb(PART)
    return img, [0, sec.nx * sec.px, 0, sec.nz * sec.px], load


def main():
    png = sys.argv[1] if len(sys.argv) > 1 else "parting.png"
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    fig, axes = plt.subplots(1, 3, figsize=(12.6, 4.1), facecolor=SURFACE)
    loads = {}
    for ax, (pattern, label) in zip(axes, PANELS):
        img, extent, loads[pattern] = panel(pattern)
        ax.imshow(img, origin="lower", extent=extent, interpolation="nearest")
        ax.set_xlim(0.05, 2.3)
        ax.set_ylim(0.75, 1.95)
        ax.set_title(label, loc="left", color=INK, fontsize=12, pad=8)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        print("%-9s limit load %.2f  (%+.1f %% against normal walls)"
              % (pattern, loads[pattern], 100 * (loads[pattern] / loads["stock"] - 1)), flush=True)
    axes[0].text(0.06, 0.72, "outside of the part on the left", color=MUTED, fontsize=8.5, va="top")
    fig.legend(handles=[Patch(facecolor=MOVES, label="the part that pulls away"),
                        Patch(facecolor=STAYS, label="the part that stays"),
                        Line2D([0], [0], color=PART, lw=3, label="where the model says it parts"),
                        Line2D([0], [0], color=WELD, lw=2, label="weld between two beads")],
               loc="lower center", ncol=4, frameon=False, fontsize=9.5, labelcolor=SECOND,
               bbox_to_anchor=(0.5, 0.02))
    fig.suptitle("Pulling a wall apart across its layers: where the weakest surface runs  (a model, not a measurement)",
                 x=0.012, ha="left", color=INK, fontsize=13)
    fig.tight_layout(rect=(0, 0.09, 1, 0.95))
    fig.savefig(png, dpi=170, facecolor=SURFACE)
    print("wrote", png)


if __name__ == "__main__":
    main()
