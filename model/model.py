# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""A small model of a printed wall's cross-section, for comparing wall patterns.

THIS IS A MODEL, NOT A MEASUREMENT. It answers "given these assumptions, which
pattern makes the crack work harder?" It cannot replace printing and breaking
test bars. The assumptions are listed in tools/strength_sim/README.md.

Two parts:

1. deposit(): lays beads down one at a time on a fine pixel grid. Each bead has a
   fixed amount of plastic, is flattened on top by the nozzle, spreads sideways
   into whatever room there is, and cannot fill corners sharper than a given
   radius. Voids and weld lines come out of that by themselves.

2. Lattice: a triangular network of springs laid over the picture. Springs inside
   one bead are full strength; springs that cross from one bead to another (a
   weld) are weaker; there are none in voids. It can be loaded in two ways:
   limit_load() finds the largest load the network can carry when no spring may
   pull harder than its strength (solved exactly as a linear programme);
   pull() stretches it and removes the most overloaded spring, again and again,
   until it comes apart. The highest load on the way is the strength.

Needs numpy and scipy.
"""
import math

import numpy as np
from scipy import ndimage, sparse
from scipy.sparse.linalg import spsolve


# ---------------------------------------------------------------------------
# Part 1: geometry
# ---------------------------------------------------------------------------

class Section(object):
    def __init__(self, width_mm, height_mm, px):
        self.px = px
        self.nx = int(round(width_mm / px))
        self.nz = int(round(height_mm / px))
        self.ids = np.zeros((self.nz, self.nx), dtype=np.int32)      # 0 = empty
        self.top = np.zeros(self.nx, dtype=np.int64)                 # first free pixel in each column
        self.beads = [None]                                          # id -> dict
        self.lost = 0.0                                              # plastic that found no room (mm2)

    def deposit(self, xc_mm, ztop_mm, area_mm2, corner_mm, **info):
        px = self.px
        cx = int(round(xc_mm / px))
        zt = int(round(ztop_mm / px))
        target = area_mm2 / (px * px)
        gap = np.clip(zt - self.top, 0, None)
        radius = max(1, int(round(corner_mm / px)))
        yy, xx = np.ogrid[-radius:radius + 1, -radius:radius + 1]
        disk = (xx * xx + yy * yy) <= radius * radius
        bead_id = len(self.beads)
        want = target
        best = None
        for _ in range(6):
            # spread sideways from the nozzle centre, nearest columns first
            left = right = cx
            filled = float(gap[cx])
            lo_open = hi_open = True
            if gap[cx] <= 0:
                break
            while filled < want and (lo_open or hi_open):
                grew = False
                for side in (-1, 1):
                    if filled >= want:
                        break
                    if side < 0 and lo_open:
                        nxt = left - 1
                        if nxt < 0 or gap[nxt] <= 0:
                            lo_open = False
                        else:
                            left = nxt
                            filled += gap[nxt]
                            grew = True
                    elif side > 0 and hi_open:
                        nxt = right + 1
                        if nxt >= self.nx or gap[nxt] <= 0:
                            hi_open = False
                        else:
                            right = nxt
                            filled += gap[nxt]
                            grew = True
                if not grew:
                    break
            raw = np.zeros_like(self.ids, dtype=bool)
            for x in range(left, right + 1):
                raw[self.top[x]:zt, x] = True
            raw &= self.ids == 0
            # molten plastic cannot fill corners sharper than `corner_mm`
            shape = ndimage.binary_opening(raw, structure=disk)
            got = float(shape.sum())
            best = shape
            if got <= 0 or abs(got - target) / target < 0.004 or not (lo_open or hi_open):
                break
            want *= target / got
        if best is None or not best.any():
            self.lost += area_mm2
            self.beads.append(dict(info, area=0.0))
            return bead_id
        self.ids[best] = bead_id
        self.lost += max(0.0, (target - best.sum())) * px * px
        cols = np.where(best.any(axis=0))[0]
        for x in cols:
            self.top[x] = max(self.top[x], np.max(np.where(best[:, x])[0]) + 1)
        self.beads.append(dict(info, area=float(best.sum()) * px * px))
        return bead_id


def build(pattern="stock", walls=5, layers=9, h=0.2, w=0.45, px=0.005, corner=0.3,
          amplitude=0.25, first_scale=0.5, brick_flow=1.0, order="inner_first"):
    """Lay down a wall: one outer wall (left) and walls-1 inner walls.

    pattern  "stock"     every bead the same
             "flatlock"  inner walls alternately fat/thin, swapping every layer
             "brick"     every other inner wall printed half a layer higher
             "brickflat" brick, and the fat/thin alternation as well
    corner   sharpest corner the plastic can fill, as a fraction of layer height
    """
    s = w - h * (1.0 - math.pi / 4.0)            # wall spacing (Slic3r bead model)
    a0 = s * h                                   # plastic per bead
    pad = 0.15
    width = pad * 2 + s * walls
    sec = Section(width, h * (layers + 1), px)
    sec.spacing = s
    sec.h = h
    sec.pattern = pattern
    r = corner * h
    centres = [pad + s * (k + 0.5) for k in range(walls)]
    for layer in range(1, layers + 1):
        seq = list(range(walls - 1, -1, -1)) if order == "inner_first" else list(range(walls))
        jobs = []
        for depth in seq:
            flow = 1.0
            shifted = False
            if depth >= 1 and pattern in ("flatlock", "brickflat") and 1 < layer < layers:
                amp = amplitude * (first_scale if depth == 1 else 1.0)
                flow *= 1.0 + (amp if (depth + layer) % 2 == 0 else -amp)
            if depth >= 1 and pattern in ("brick", "brickflat") and depth % 2 == 1:
                shifted = True
            jobs.append((depth, flow, shifted))
        # a nozzle cannot print beside a bead that already stands half a layer taller,
        # so the raised walls are printed last
        for depth, flow, shifted in [j for j in jobs if not j[2]] + [j for j in jobs if j[2]]:
            ztop = layer * h
            area = a0 * flow
            if shifted:
                if layer == 1:
                    ztop, area = 1.5 * h, 1.5 * a0 * flow
                elif layer == layers:
                    ztop, area = layers * h, 0.5 * a0 * flow
                else:
                    ztop, area = (layer + 0.5) * h, a0 * flow * brick_flow
            sec.deposit(centres[depth], ztop, area, r, layer=layer, depth=depth, shifted=shifted, flow=flow)
    return sec


def void_fraction(sec, z0, z1):
    """Share of empty space inside the wall between two heights (mm), outer skin excluded."""
    a = int(round(z0 / sec.px))
    b = int(round(z1 / sec.px))
    block = sec.ids[a:b]
    cols = np.where((block > 0).mean(axis=0) > 0.5)[0]
    core = block[:, cols[0] + int(0.5 * sec.spacing / sec.px):cols[-1] - int(0.5 * sec.spacing / sec.px)]
    return float((core == 0).mean())


# ---------------------------------------------------------------------------
# Part 2: strength
# ---------------------------------------------------------------------------

class Lattice(object):
    def __init__(self, sec, a=0.0125, weld=0.5, side_weld=None, seed=0, scatter=0.08):
        self.sec = sec
        self.a = a
        dz = a * math.sqrt(3.0) / 2.0
        width = sec.nx * sec.px
        height = (sec.top.max()) * sec.px
        ni = int(width / a) - 1
        nj = int(height / dz) - 1
        jj, ii = np.mgrid[0:nj, 0:ni]
        x = (ii + 0.5 * (jj % 2) + 0.5) * a
        z = (jj + 0.5) * dz
        px_i = np.clip((x / sec.px).astype(int), 0, sec.nx - 1)
        pz_i = np.clip((z / sec.px).astype(int), 0, sec.nz - 1)
        ids = sec.ids[pz_i, px_i]
        self.x = x.ravel()
        self.z = z.ravel()
        self.ids = ids.ravel()
        self.shape = (nj, ni)
        index = np.arange(nj * ni).reshape(nj, ni)
        pairs = []
        pairs.append((index[:, :-1].ravel(), index[:, 1:].ravel()))                    # along the row
        even = index[0:nj - 1:2]
        up_even = index[1:nj:2]
        m = min(len(even), len(up_even))
        pairs.append((even[:m].ravel(), up_even[:m].ravel()))                          # even row: up-right is same column index
        pairs.append((even[:m, 1:].ravel(), up_even[:m, :-1].ravel()))                 # even row: up-left
        odd = index[1:nj - 1:2]
        up_odd = index[2:nj:2]
        m = min(len(odd), len(up_odd))
        pairs.append((odd[:m].ravel(), up_odd[:m].ravel()))                            # odd row: up-left is same column index
        pairs.append((odd[:m, :-1].ravel(), up_odd[:m, 1:].ravel()))                   # odd row: up-right
        i = np.concatenate([p[0] for p in pairs])
        j = np.concatenate([p[1] for p in pairs])
        keep = (self.ids[i] > 0) & (self.ids[j] > 0)
        self.bi = i[keep]
        self.bj = j[keep]
        dxv = self.x[self.bj] - self.x[self.bi]
        dzv = self.z[self.bj] - self.z[self.bi]
        length = np.hypot(dxv, dzv)
        self.cx = dxv / length
        self.cz = dzv / length
        self.len = length
        # strength of each spring
        ia = self.ids[self.bi]
        ib = self.ids[self.bj]
        depth = np.array([0] + [b["depth"] for b in sec.beads[1:]])
        layer = np.array([0] + [b["layer"] for b in sec.beads[1:]])
        strength = np.ones(len(self.bi))
        cross = ia != ib
        strength[cross] = weld
        if side_weld is not None:
            side = cross & (depth[ia] != depth[ib]) & (layer[ia] == layer[ib])
            strength[side] = side_weld
        rng = np.random.RandomState(seed)
        self.strength = strength * (1.0 + scatter * (rng.rand(len(strength)) * 2.0 - 1.0))
        self.cross = cross
        self.alive = np.ones(len(self.bi), dtype=bool)
        self.level = np.zeros(len(self.bi), dtype=np.int16)     # how far each spring has softened
        self.n = nj * ni

    def _grips(self, mode, grip=None):
        x, z = self.x, self.z
        used = np.zeros(self.n, dtype=bool)
        used[self.bi] = True
        used[self.bj] = True
        zmin, zmax = z[used].min(), z[used].max()
        xmin, xmax = x[used].min(), x[used].max()
        h = self.sec.h
        s = self.sec.spacing
        if mode in ("z", "shear"):
            g = grip if grip is not None else 2.0 * h
            lo = used & (z < zmin + g)
            hi = used & (z > zmax - g)
            section = xmax - xmin
            direction = (0.0, 1.0) if mode == "z" else (1.0, 0.0)
        else:                                   # "x": pull the walls apart sideways
            g = grip if grip is not None else 0.75 * s
            lo = used & (x < xmin + g)
            hi = used & (x > xmax - g)
            section = zmax - zmin
            direction = (1.0, 0.0)
        return used, lo, hi, section, direction

    def _stiffness(self, kappa):
        bi, bj = self.bi[self.alive], self.bj[self.alive]
        cx, cz = self.cx[self.alive], self.cz[self.alive]
        k = kappa[self.alive] / self.len[self.alive]
        rows = []
        cols = []
        vals = []
        for (da, ca) in ((0, cx), (1, cz)):
            for (db, cb) in ((0, cx), (1, cz)):
                v = k * ca * cb
                rows += [2 * bi + da, 2 * bj + da, 2 * bi + da, 2 * bj + da]
                cols += [2 * bi + db, 2 * bj + db, 2 * bj + db, 2 * bi + db]
                vals += [v, v, -v, -v]
        return sparse.coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                                 shape=(2 * self.n, 2 * self.n)).tocsr()

    def pull(self, mode="z", grip=None, ductility=1.0, teeth=None, max_steps=6000, batch=0.97, stop_drop=0.25):
        """Pull until broken and return the highest load reached.

        ductility 1 = glass-brittle springs (snap at their strength).
        ductility m > 1 = springs keep carrying a falling load until they have
        stretched m times as far (a tougher weld). Done as a 'saw-tooth' series
        of purely elastic steps, so no iteration is needed.
        """
        if teeth is None:
            teeth = 1 if ductility <= 1.0 else 5
        used, lo, hi, section, direction = self._grips(mode, grip)
        pulled = 1 if direction[1] else 0
        fixed = np.zeros(2 * self.n, dtype=bool)
        value = np.zeros(2 * self.n)
        if mode == "shear":
            fixed[0::2] |= lo | hi              # sliding one face over the other: hold both directions
            fixed[1::2] |= lo | hi
        else:
            # straight pull: the grips only hold the pulling direction (like rollers), so
            # there is no artificial stress peak where a clamp would meet the free edge
            fixed[pulled::2] |= lo | hi
            fixed[2 * np.where(lo)[0][0] + (1 - pulled)] = True
        value[2 * np.where(hi)[0] + pulled] = 1.0
        fixed[np.repeat(~used, 2)] = True
        gripped = lo[self.bi] | hi[self.bi] | lo[self.bj] | hi[self.bj]
        free = ~fixed
        step_frac = np.arange(teeth + 1) / float(teeth)
        strain_at = 1.0 + (ductility - 1.0) * step_frac                   # strain where each tooth gives way
        kappa_at = np.where(step_frac < 1.0, (1.0 - step_frac) / strain_at, 0.0)
        history = []
        peak = 0.0
        broken_order = []
        hi_idx = 2 * np.where(hi)[0] + pulled
        ident = sparse.identity(int(free.sum()), format="csr") * 1e-9
        for step in range(max_steps):
            K = self._stiffness(kappa_at[self.level])
            Kfree = K[free]
            u = np.array(value)
            u[free] = spsolve((Kfree[:, free] + ident).tocsc(), -(Kfree[:, fixed] @ value[fixed]))
            alive = np.where(self.alive)[0]
            stretch = ((u[2 * self.bj[alive]] - u[2 * self.bi[alive]]) * self.cx[alive]
                       + (u[2 * self.bj[alive] + 1] - u[2 * self.bi[alive] + 1]) * self.cz[alive]) / self.len[alive]
            ratio = stretch / (self.strength[alive] * strain_at[self.level[alive]])
            ratio[gripped[alive]] = -1.0
            top = ratio.max()
            if top <= 1e-12:
                break
            reaction = float((K[hi_idx] @ u).sum())
            load = reaction / top / section          # load per mm of section when the next spring gives
            history.append(load)
            peak = max(peak, load)
            hit = alive[ratio >= batch * top]
            self.level[hit] += 1
            dead = hit[self.level[hit] >= teeth]
            self.alive[dead] = False
            broken_order.append(dead)
            if load < stop_drop * peak and step > 10:
                break
        return dict(strength=peak, history=history,
                    broken=np.concatenate(broken_order) if broken_order else np.array([], int))

    def limit_load(self, mode="z", grip=None):
        """The 'tough' limit: the largest load the network can carry if every spring
        holds its full strength while its neighbours catch up (no spring can pull
        harder than its strength; pushing is unlimited). This is the exact plastic
        collapse load of the network, found as a linear programme (lower-bound
        theorem of limit analysis)."""
        from scipy.optimize import linprog
        used, lo, hi, section, direction = self._grips(mode, grip)
        pulled = 1 if direction[1] else 0
        alive = np.where(self.alive)[0]
        bi, bj = self.bi[alive], self.bj[alive]
        cx, cz = self.cx[alive], self.cz[alive]
        nb = len(alive)
        held = np.zeros(2 * self.n, dtype=bool)              # dofs where the grip supplies a reaction
        if mode == "shear":
            held[0::2] |= lo | hi
            held[1::2] |= lo | hi
        else:
            held[pulled::2] |= lo | hi
        # force of spring b (tension N) on node i is +N*c, on node j is -N*c
        rows = np.concatenate([2 * bi, 2 * bi + 1, 2 * bj, 2 * bj + 1])
        cols = np.concatenate([np.arange(nb)] * 4)
        vals = np.concatenate([cx, cz, -cx, -cz])
        A = sparse.csr_matrix((vals, (rows, cols)), shape=(2 * self.n, nb))
        free_rows = np.where(~held & np.repeat(used, 2))[0]
        A_eq = A[free_rows]
        if mode == "shear":
            # pure sliding: the grips may not also squeeze the layers together
            squeeze = sparse.csr_matrix(A[2 * np.where(hi)[0] + 1].sum(axis=0))
            A_eq = sparse.vstack([A_eq, squeeze]).tocsr()
        # the load is the total reaction on the pulled grip, in the pulling direction
        hi_dofs = 2 * np.where(hi)[0] + pulled
        cost = np.asarray(A[hi_dofs].sum(axis=0)).ravel()     # minimise this = maximise the reaction on the grip
        gripped = lo[bi] | hi[bi] | lo[bj] | hi[bj]
        upper = np.where(gripped, np.inf, self.strength[alive])
        res = linprog(cost, A_eq=A_eq, b_eq=np.zeros(A_eq.shape[0]),
                      bounds=np.column_stack([np.full(nb, -np.inf), upper]), method="highs-ipm",
                      options={"presolve": True})
        if res.status != 0:
            raise RuntimeError("limit analysis did not converge: %s" % res.message)
        # springs working at their full strength mark the surface where it would part
        self.limit_force = np.zeros(len(self.bi))
        self.limit_force[alive] = res.x
        self.limit_busy = alive[(res.x >= 0.98 * self.strength[alive]) & ~gripped]
        # the LP's dual values are how fast each free point moves as it comes apart
        self.limit_motion = np.full(2 * self.n, np.nan)
        self.limit_motion[free_rows] = np.asarray(res.eqlin.marginals)[:len(free_rows)]
        return float(-res.fun) / section
