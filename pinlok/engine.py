#!/usr/bin/env python3
# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
#
# WORK IN PROGRESS: MANY FEATURES MAY BE BROKEN. Not yet proven on a real printer.
"""PinLoK engine: pinned infill ("sparse squish") for sliced G-code.

Sparse infill such as Grid or Rectilinear leaves open vertical channels between its lines.
Every few layers PinLoK stops the nozzle over half of those channels and pushes a measured
blob of plastic into each one (a "pin"). The plastic pools at the bottom of the channel and
fills it from below, so it crosses several layer lines and grips the channel walls. The two
halves (A and B, like a chess board) take turns, so the joints between pins never line up.
The idea comes from Oak Ridge National Laboratory's published "Z-pinning" work (see RESEARCH.md).

What it does to the file:
  * adds short blocks of G-code (lift, travel, extrude in place, lift) after the last
    extrusion of a pin layer, and puts the nozzle back where it was;
  * never changes, moves or deletes any line the slicer wrote.

Where it puts pins: only in channels that are open for at least `every` layers, between
`min_width` and `max_width` across (narrower ones would block before they fill, wider
ones are too big for one blob to grip), and that are surrounded mostly by infill, so a
hole through the part is never filled.

This file is deliberately self-contained (Python 3.8+, standard library only) so one copy
can run as a slicer post-processing script and another can live inside the Cura plug-in.
"""
from __future__ import annotations

import math
import os
import re
import sys
import time
from array import array

__version__ = "0.2.0-wip"
__build_date__ = "2026-10-13 13:00"

MARKER = "; PinLoK"

INFILL_TYPES = ("fill", "internal infill", "sparse infill", "infill")


class PinLokError(Exception):
    pass


MODES = {
    # small, quick pins every 2 layers: each push is short, so a slow stock hot end never
    # leaves plastic sitting half-way down a gap long enough to harden there
    "potato": dict(every=2, keep_open=1.5, flow_rate=3.0, max_pin_volume=3.0, dwell=0.1,
                   travel_speed=100.0),
    # the ORNL-style rhythm: bigger pins every 4 layers
    "balanced": dict(every=4, keep_open=2.5, flow_rate=3.0, max_pin_volume=8.0, dwell=0.2,
                     travel_speed=100.0),
    # for hot ends that melt plastic quickly (Bambu, Revo, Volcano...): same pins, pushed faster
    "performance": dict(every=4, keep_open=1.5, flow_rate=8.0, max_pin_volume=12.0, dwell=0.1,
                        travel_speed=200.0),
}
MODE_TEXT = {"potato": "Potato (small quick pins, stock printers)",
             "balanced": "Balanced",
             "performance": "Performance (fast hot ends)"}


class Settings(object):
    def __init__(self, mode="potato"):
        self.enabled = True
        self.mode = mode
        self.every = 2                 # a pin layer every N layers (A and B alternate)
        # each pin tops its gap up to this many layers below the nozzle. A half layer on purpose: the
        # top of a pin then lies half-way through an infill layer, not on a layer line, so pin joints
        # and infill layer lines never share one plane (in the model this tripled the gain in a
        # crack-running pull, +3-5 % -> +16-18 %).
        self.keep_open = 1.5
        self.min_width = 0.8           # mm: narrower gaps would block before they fill
        self.max_width = 2.6           # mm: wider ones are too big for one blob
        self.flow_rate = 3.0           # mm3/s while pushing a pin
        self.dwell = 0.1               # s to wait after a pin so it can settle
        self.retract_over = 5.0        # mm: only retract between pins for travels longer than this
        self.hop = 0.6                 # mm to lift for travel between pins
        self.travel_speed = 100.0      # mm/s
        self.max_pin_volume = 3.0      # mm3 per pin; a deeper gap is topped up over several pins
        self.start_layer = 3           # first layer (1-based) that may get pins
        self.filament_diameter = 0.0   # 0 = read from the file, else 1.75
        self.retract = -1.0            # mm; -1 = use what the slicer uses
        self.retract_speed = -1.0      # mm/s; -1 = use what the slicer uses
        self.px = 0.2                  # mm: size of the map pixels
        self.apply_mode(mode)

    def apply_mode(self, mode):
        if mode not in MODES:
            raise PinLokError("PinLoK: unknown mode '%s' (use potato, balanced or performance)" % mode)
        self.mode = mode
        for key, value in MODES[mode].items():
            setattr(self, key, value)
        return self

    def validate(self):
        self.every = max(2, min(20, int(self.every)))
        self.keep_open = max(0.0, min(float(self.every), float(self.keep_open)))
        self.min_width = max(0.5, min(3.0, float(self.min_width)))
        self.max_width = max(self.min_width + 0.2, min(6.0, float(self.max_width)))
        self.flow_rate = max(0.5, min(30.0, float(self.flow_rate)))
        self.dwell = max(0.0, min(5.0, float(self.dwell)))
        self.hop = max(0.2, min(3.0, float(self.hop)))
        self.travel_speed = max(10.0, min(500.0, float(self.travel_speed)))
        self.max_pin_volume = max(0.5, min(100.0, float(self.max_pin_volume)))
        self.retract_over = max(0.0, float(self.retract_over))
        self.start_layer = max(2, int(self.start_layer))
        self.px = max(0.1, min(0.5, float(self.px)))
        return self

    def describe(self):
        return ("%s mode: pins every %d layers, gap kept %g layers, channels %.1f-%.1f mm, "
                "up to %.1f mm3 per pin at %.1f mm3/s"
                % (self.mode, self.every, self.keep_open, self.min_width, self.max_width,
                   self.max_pin_volume, self.flow_rate))


class Stats(object):
    def __init__(self):
        self.pins = 0
        self.pin_layers = 0
        self.volume = 0.0
        self.too_wide = 0
        self.too_narrow = 0
        self.layers = 0
        self.seconds = 0.0
        self.already = False
        self.extra_time = 0.0
        self.retract = 0.0
        self.notes = []

    def human(self):
        if self.already:
            return "PinLoK: this file already has pins; nothing changed."
        if not self.pins:
            why = ""
            if self.too_wide and self.too_wide >= self.too_narrow:
                why = (" The gaps in the infill are too wide for pins: use Grid infill at about 35% "
                       "(or Rectilinear at about 20%).")
            elif self.too_narrow:
                why = (" The gaps in the infill are too narrow for pins: use Grid infill at about 35% "
                       "(or Rectilinear at about 20%). Gyroid, Cubic and similar patterns have no "
                       "straight gaps.")
            else:
                why = (" No open gaps were found: pins need Grid infill at about 35% (or Rectilinear "
                       "at about 20%), not Gyroid or Cubic, and parts at least a few mm across inside.")
            if self.notes:
                return "PinLoK: no pins added: %s." % "; ".join(self.notes)
            return "PinLoK: no pins added." + why
        text = ("PinLoK: %d pins on %d layers, %.0f mm3 of plastic, about %.0f s extra."
                % (self.pins, self.pin_layers, self.volume, self.extra_time))
        if self.notes:
            text += " (%s)" % "; ".join(self.notes)
        return text

    def summary_lines(self, settings):
        return ["%s %s applied (%s)" % (MARKER, __version__, settings.describe()),
                "%s: %d pins on %d layers, %.1f mm3" % (MARKER, self.pins, self.pin_layers, self.volume)]


# --------------------------------------------------------------------------
# Reading the G-code
# --------------------------------------------------------------------------

_WORD = re.compile(r"([A-Za-z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")


def _code(line):
    k = line.find(";")
    return line if k < 0 else line[:k]


def _words(code):
    return dict((w.upper(), float(v)) for w, v in _WORD.findall(code))


def _feature(line):
    """The feature name a slicer comment announces, lower case, or None."""
    s = line.strip()
    low = s.lower()
    for head in (";type:", "; feature:", ";feature:"):
        if low.startswith(head):
            return low[len(head):].strip()
    return None


def _is_layer_mark(line):
    s = line.strip()
    return (s.startswith(";LAYER:") or s == ";LAYER_CHANGE" or s.startswith("; CHANGE_LAYER")
            or s.startswith(";LAYER_CHANGE"))


class _State(object):
    """What the printer is doing at one point of the file."""
    __slots__ = ("x", "y", "z", "e", "abs_e", "abs_xyz", "owed", "fw", "f", "label", "tool")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))


class _Layer(object):
    __slots__ = ("start", "end", "z", "segs", "last_extrude", "ins", "state")

    def __init__(self, start):
        self.start = start
        self.end = start
        self.z = None
        self.segs = []             # (x0, y0, x1, y1, area, is_infill, object index)
        self.last_extrude = -1     # line index of the last extrusion
        self.ins = -1              # pins go in after this line: the end of the layer
        self.state = None          # printer state right after `ins`


def _arc_points(x0, y0, x1, y1, i, j, clockwise):
    """Points along a G2/G3 arc (about every 0.5 mm)."""
    cx, cy = x0 + i, y0 + j
    r = math.hypot(i, j)
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    if clockwise:
        while a1 >= a0:
            a1 -= 2 * math.pi
    else:
        while a1 <= a0:
            a1 += 2 * math.pi
    n = max(2, int(abs(a1 - a0) * r / 0.5) + 1)
    pts = [(cx + r * math.cos(a0 + (a1 - a0) * k / n), cy + r * math.sin(a0 + (a1 - a0) * k / n))
           for k in range(n)]
    pts.append((x1, y1))
    return pts


_LABEL_KLIPPER = re.compile(r"^EXCLUDE_OBJECT_(START|END)\b(?:.*?\bNAME=(\S+))?", re.I)


class Scan(object):
    def __init__(self):
        self.layers = []
        self.retract = None         # (mm, feed) the slicer uses most, or None
        self.firmware_retract = False
        self.tools = set()
        self.labels = None          # None, "klipper" or "m486"
        self.objects = []           # object names / ids, in order of first use
        self.bambu_labels = False


def scan(lines, filament_area):
    """One pass over the lines: layers, extrusion segments, retraction habits, and the
    printer's state at the end of every layer."""
    res = Scan()
    layers = res.layers
    cur = _Layer(0)
    x = y = z = e = 0.0
    abs_e = True
    abs_xyz = True
    feature = None
    events = {}
    run = 0.0                      # filament pulled back since the last push forward
    run_f = None
    owed = 0.0                     # pulled back and not yet pushed forward again
    fw = False                     # firmware retraction active (G10 without G11)
    g10 = 0
    last_f = None
    label = None                   # object whose label block is open
    obj_index = {}
    tool = None

    def state():
        return _State(x=x, y=y, z=z, e=e, abs_e=abs_e, abs_xyz=abs_xyz, owed=owed, fw=fw, f=last_f,
                      label=label, tool=tool)

    def close(i):
        cur.ins = i - 1
        cur.state = state()
        cur.end = i
        layers.append(cur)

    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith(";"):
            if _is_layer_mark(line):
                if cur.segs or cur.last_extrude >= 0:
                    close(i)
                    cur = _Layer(i)
                else:
                    cur.start = i
            else:
                f = _feature(line)
                if f is not None:
                    feature = f
            continue
        code = _code(line).strip()
        if not code:
            continue
        head = code.split(None, 1)[0].upper()
        if head in ("G0", "G1", "G00", "G01", "G2", "G3", "G02", "G03"):
            w = _words(code)
            if "F" in w:
                last_f = w["F"]
            nx = w.get("X", x) if abs_xyz else x + w.get("X", 0.0)
            ny = w.get("Y", y) if abs_xyz else y + w.get("Y", 0.0)
            nz = w.get("Z", z) if abs_xyz else z + w.get("Z", 0.0)
            de = 0.0
            if "E" in w:
                if abs_e and abs_xyz:
                    de = w["E"] - e
                    e = w["E"]
                else:
                    de = w["E"]
                    e += de
            moved = math.hypot(nx - x, ny - y)
            if de < 0:
                run -= de
                owed -= de
                if moved < 1e-6:
                    run_f = w.get("F", last_f)
            elif de > 0:
                if run > 0:
                    key = (round(run, 2), run_f)
                    events[key] = events.get(key, 0) + 1
                    run = 0.0
                owed = max(0.0, owed - de) if moved < 1e-6 else 0.0
            if de > 0 and moved > 1e-6:
                if cur.z is None or nz > cur.z + 1e-6:
                    cur.z = nz
                pts = [(x, y), (nx, ny)]
                if head in ("G2", "G3", "G02", "G03") and ("I" in w or "J" in w):
                    pts = _arc_points(x, y, nx, ny, w.get("I", 0.0), w.get("J", 0.0), head in ("G2", "G02"))
                length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])) or moved
                area = de * filament_area / length
                is_infill = feature in INFILL_TYPES if feature else False
                ob = obj_index.get(label, -1) if label is not None else -1
                for a, b in zip(pts, pts[1:]):
                    cur.segs.append((a[0], a[1], b[0], b[1], area, is_infill, ob))
                cur.last_extrude = i
                if tool is not None:
                    res.tools.add(tool)
            x, y, z = nx, ny, nz
        elif head == "G90":
            abs_xyz = True
        elif head == "G91":
            abs_xyz = False
        elif head == "M82":
            abs_e = True
        elif head == "M83":
            abs_e = False
        elif head == "G92":
            w = _words(code)
            if "E" in w:
                e = w["E"]
            if not w:
                e = 0.0
        elif head == "G10" and "P" not in code.upper() and "L" not in code.upper():
            fw = True
            g10 += 1
        elif head == "G11":
            fw = False
        elif head.startswith("T") and head[1:].isdigit():
            tool = int(head[1:])
        elif head == "EXCLUDE_OBJECT_START" or head == "EXCLUDE_OBJECT_END":
            m = _LABEL_KLIPPER.match(code)
            res.labels = "klipper"
            if m and m.group(1).upper() == "START":
                label = m.group(2) or "?"
                if label not in obj_index:
                    obj_index[label] = len(res.objects)
                    res.objects.append(label)
            else:
                label = None
        elif head == "M486":
            w = _words(code)
            if "S" in w:
                res.labels = res.labels or "m486"
                if w["S"] < 0:
                    label = None
                else:
                    label = int(w["S"])
                    if label not in obj_index:
                        obj_index[label] = len(res.objects)
                        res.objects.append(label)
        elif head in ("M624", "M625"):
            res.bambu_labels = True
    if cur.segs:
        close(len(lines))
    if events:
        res.retract = max(events.items(), key=lambda kv: kv[1])[0]
    res.firmware_retract = not events and g10 > 0
    return res


# --------------------------------------------------------------------------
# The map: for every pixel, the last layer that put plastic there
# --------------------------------------------------------------------------

class _Map(object):
    def __init__(self, x0, y0, x1, y1, px):
        self.px = px
        self.x0 = x0
        self.y0 = y0
        self.nx = int(math.ceil((x1 - x0) / px)) + 1
        self.ny = int(math.ceil((y1 - y0) / px)) + 1
        n = self.nx * self.ny
        self.last = array("i", [-1000]) * n      # layer index of the last plastic
        self.kind = bytearray(n)                  # 1 = wall/other, 2 = infill, 3 = pin
        self.obj = bytearray(n)                   # labelled object (index + 1), 0 = none

    def stamp(self, x0, y0, x1, y1, width, layer, kind, obj=0):
        px = self.px
        half = max(0.5 * width, 0.5 * px)
        length = math.hypot(x1 - x0, y1 - y0)
        steps = max(1, int(length / (0.5 * px)))
        r = int(math.ceil(half / px - 0.5))
        nx = self.nx
        last = self.last
        kd = self.kind
        ob = self.obj
        for k in range(steps + 1):
            t = k / float(steps)
            cx = int(round((x0 + (x1 - x0) * t - self.x0) / px))
            cy = int(round((y0 + (y1 - y0) * t - self.y0) / px))
            for iy in range(max(0, cy - r), min(self.ny, cy + r + 1)):
                row = iy * nx
                for ix in range(max(0, cx - r), min(nx, cx + r + 1)):
                    p = row + ix
                    last[p] = layer
                    kd[p] = kind
                    ob[p] = obj

    def index(self, x, y):
        ix = int(round((x - self.x0) / self.px))
        iy = int(round((y - self.y0) / self.px))
        if 0 <= ix < self.nx and 0 <= iy < self.ny:
            return iy * self.nx + ix
        return -1


def _channel(m, p0, layer, need, max_cells):
    """Flood the open prism (no plastic for `need` layers) around pixel p0.
    Returns (status, pixels, infill_border, other_border, pick, clearance):
    status "ok", "edge" (reached the edge of the map: outside the part) or "big" (more than
    max_cells pixels). `pick` is the pixel furthest from the channel's sides, `clearance` its
    distance to them in pixels."""
    nx, ny = m.nx, m.ny
    last = m.last
    kind = m.kind
    stack = [p0]
    seen = {p0}
    cells = []
    border = set()
    b_inf = b_other = 0
    owners = {}
    while stack:
        p = stack.pop()
        cells.append(p)
        if len(cells) > max_cells:
            return "big", cells + stack, 0, 0, None, 0, 0
        ix = p % nx
        iy = p // nx
        for q, ok in ((p - 1, ix > 0), (p + 1, ix < nx - 1), (p - nx, iy > 0), (p + nx, iy < ny - 1)):
            if not ok:
                return "edge", cells + stack, 0, 0, None, 0, 0
            if q in seen:
                continue
            seen.add(q)
            if layer - last[q] >= need:
                stack.append(q)
            else:
                border.add(p)
                owners[m.obj[q]] = owners.get(m.obj[q], 0) + 1
                if kind[q] == 2 or kind[q] == 3:
                    b_inf += 1
                else:
                    b_other += 1
    # distance from the sides, by layers peeled inwards (4-connected)
    inside = set(cells)
    dist = dict.fromkeys(border, 1)
    front = list(border)
    d = 1
    while front:
        d += 1
        nxt = []
        for p in front:
            for q in (p - 1, p + 1, p - nx, p + nx):
                if q in inside and q not in dist:
                    dist[q] = d
                    nxt.append(q)
        front = nxt
    best = max(dist.values()) if dist else 0
    tops = [p for p, v in dist.items() if v == best]
    # of the deepest pixels take the one nearest their middle
    mx = sum(p % nx for p in tops) / float(len(tops))
    my = sum(p // nx for p in tops) / float(len(tops))
    pick = min(tops, key=lambda p: (p % nx - mx) ** 2 + (p // nx - my) ** 2)
    owner = max((k for k in owners if k), key=lambda k: owners[k], default=0)
    return "ok", cells, b_inf, b_other, pick, best, owner


# --------------------------------------------------------------------------
# The engine
# --------------------------------------------------------------------------

def _fmt(v, nd=3):
    s = ("%." + str(nd) + "f") % v
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s not in ("-0", "") else "0"


def _order(pins, x, y):
    """Nearest pin next (short hops, little oozing)."""
    if len(pins) > 3000:
        return sorted(pins, key=lambda q: (round(q[1] / 2.0), q[0]))
    left = list(pins)
    out = []
    while left:
        k = min(range(len(left)), key=lambda j: (left[j][0] - x) ** 2 + (left[j][1] - y) ** 2)
        q = left.pop(k)
        out.append(q)
        x, y = q[0], q[1]
    return out


class Engine(object):
    def __init__(self, settings=None):
        self.s = (settings or Settings()).validate()
        self.stats = Stats()
        self.fw = False
        self.labels = None
        self.objects = []

    def plan(self, lines):
        """Returns {line index: block of new lines to insert after it}."""
        s = self.s
        t0 = time.time()
        dia = s.filament_diameter if s.filament_diameter > 0 else 1.75
        area_f = math.pi * dia * dia / 4.0
        sc = scan(lines, area_f)
        layers = sc.layers
        self.stats.layers = len(layers)
        if len(sc.tools) > 1:
            self.stats.notes.append("more than one extruder prints in this file; PinLoK does single-extruder "
                                    "prints only")
            return {}
        if sc.bambu_labels:
            self.stats.notes.append("this file uses Bambu object labels (M624), which PinLoK cannot "
                                    "label its pins with; switch off 'exclude objects' or label objects off")
            return {}
        self.fw = sc.firmware_retract and s.retract < 0
        if sc.retract and s.retract < 0:
            r_amount, r_feed = sc.retract
        else:
            r_amount, r_feed = (s.retract if s.retract >= 0 else 1.0), None
        r_speed = s.retract_speed * 60.0 if s.retract_speed > 0 else (r_feed or 2400.0)
        r_amount = max(0.0, min(8.0, r_amount))
        self.stats.retract = r_amount
        self.labels = sc.labels
        self.objects = sc.objects
        segs_all = [sg for L in layers for sg in L.segs]
        if not segs_all:
            return {}
        # Cura does not write the filament diameter into the G-code. If the lines come out
        # implausibly thin for 1.75 mm filament, the file was made for 2.85 mm filament.
        scale = 1.0
        if s.filament_diameter <= 0:
            hs = sorted(round(b.z - a.z, 3) for a, b in zip(layers, layers[1:])
                        if a.z is not None and b.z is not None and b.z > a.z)
            h_typ = hs[len(hs) // 2] if hs else 0.2
            ws = sorted(sg[4] / max(0.04, h_typ) for sg in segs_all[:20000])
            if ws and ws[len(ws) // 2] < 0.28:
                scale = (2.85 / 1.75) ** 2
                area_f *= scale
                self.stats.notes.append("lines looked too thin for 1.75 mm filament: assumed 2.85 mm")
        xs = [v for sg in segs_all for v in (sg[0], sg[2])]
        ys = [v for sg in segs_all for v in (sg[1], sg[3])]
        m = _Map(min(xs) - 2, min(ys) - 2, max(xs) + 2, max(ys) + 2, s.px)
        channels = []              # [x, y, parity]
        inserts = {}
        prev_z = 0.0
        max_cells = int((s.max_width * 1.6 / s.px) ** 2)
        skipped = set()
        for li, L in enumerate(layers):
            z = L.z if L.z is not None else prev_z
            h = max(0.04, min(1.0, z - prev_z)) if z > prev_z else 0.2
            prev_z = z
            for (x0, y0, x1, y1, a, inf, ob) in L.segs:
                width = a * scale / h + h * (1.0 - math.pi / 4.0)
                width = max(0.2, min(2.0, width))
                m.stamp(x0, y0, x1, y1, width, li, 2 if inf else 1, ob + 1 if 0 <= ob < 255 else 0)
            n_layer = li + 1
            if n_layer < s.start_layer or n_layer % s.every != 0 or L.last_extrude < 0 or L.state is None:
                continue
            if not any(sg[5] for sg in L.segs):
                continue
            st = L.state
            if not st.abs_xyz:
                skipped.add("relative moves (G91)")
                continue
            if st.label is not None:
                skipped.add("an object label still open at the end of the layer")
                continue
            phase = (n_layer // s.every) % 2
            pins = self._find(m, li, L, channels, phase, max_cells, h)
            if not pins:
                continue
            block = self._gcode(pins, L, z, r_amount, r_speed, area_f)
            inserts[L.ins] = block
            self.stats.pin_layers += 1
        for why in sorted(skipped):
            self.stats.notes.append("some layers skipped because of %s" % why)
        self.stats.seconds = time.time() - t0
        return inserts

    def _find(self, m, li, L, channels, phase, max_cells, h):
        s = self.s
        px = m.px
        need = s.every
        # look only where this layer has infill
        xs = [v for sg in L.segs if sg[5] for v in (sg[0], sg[2])]
        ys = [v for sg in L.segs if sg[5] for v in (sg[1], sg[3])]
        if not xs:
            return []
        i0 = max(1, int((min(xs) - m.x0) / px))
        i1 = min(m.nx - 2, int((max(xs) - m.x0) / px))
        j0 = max(1, int((min(ys) - m.y0) / px))
        j1 = min(m.ny - 2, int((max(ys) - m.y0) / px))
        step = max(1, int(round(s.min_width / px / 2.0)))
        done = set()
        found = []
        last = m.last
        for iy in range(j0, j1 + 1, step):
            row = iy * m.nx
            for ix in range(i0, i1 + 1, step):
                p = row + ix
                if p in done or li - last[p] < need:
                    continue
                status, cells, b_inf, b_other, pick, clear, owner = _channel(m, p, li, need, max_cells)
                done.update(cells)
                if status == "big":
                    self.stats.too_wide += 1
                    continue
                if status != "ok":
                    continue
                if b_inf < b_other:
                    continue                     # a hole or a gap beside walls, not infill
                area = len(cells) * px * px
                eq = math.sqrt(area)                 # side of a square of the same area
                # clearance is counted in whole pixels from the sides (the first ring is 1)
                if (clear - 0.5) * px < 0.5 * s.min_width or eq < s.min_width:
                    self.stats.too_narrow += 1
                    continue
                if eq > s.max_width:
                    self.stats.too_wide += 1
                    continue
                cx = m.x0 + px * (pick % m.nx)
                cy = m.y0 + px * (pick // m.nx)
                if self.labels and not owner:
                    continue                         # labelled objects: a pin must belong to one
                found.append((cx, cy, cells, area, owner))
        pins = []
        radius = s.max_width * 1.2
        for cx, cy, cells, area, owner in found:
            par = None
            best = None
            chan = None
            for ch in channels:
                d = math.hypot(ch[0] - cx, ch[1] - cy)
                if d < 0.6 * s.min_width:
                    par = ch[2]
                    best = None
                    ch[0], ch[1] = cx, cy
                    chan = ch
                    break
                if d < radius + math.sqrt(area) and (best is None or d < best[0]):
                    best = (d, ch[2])
            if par is None:
                par = (1 - best[1]) if best else 0
                chan = [cx, cy, par, None]          # x, y, set, top of its last pin (layer units)
                channels.append(chan)
            if par != phase:
                continue
            c = m.index(cx, cy)
            # heights in layer units: the top of layer li is li + 1. The floor is the top of the
            # plastic under the nozzle: the map knows whole layers, the channel remembers the
            # exact top of its last pin (which can end part-way through a layer).
            floor = last[c] + 1.0
            if chan[3] is not None and chan[3] > floor:
                floor = chan[3]
            want = (li + 1.0 - s.keep_open) - floor        # top the gap up to keep_open below
            if want < 0.5:
                continue
            volume = min(s.max_pin_volume, area * want * h)
            if volume < 0.3:
                continue
            top_exact = floor + volume / (area * h)
            chan[3] = top_exact
            top = int(math.floor(top_exact + 1e-6)) - 1    # last layer completely filled
            for p in cells:
                if top > last[p]:
                    last[p] = top
                    m.kind[p] = 3
            pins.append((cx, cy, volume, owner))
            self.stats.pins += 1
            self.stats.volume += volume
        return pins

    def _gcode(self, pins, L, z, r_amount, r_speed, area_f):
        """The block that goes in at the end of a layer, where the slicer has finished the layer.
        Lift, visit each pin, push it, come back to exactly where the slicer left the nozzle
        (same X, Y, Z, E, extruder mode, feed rate, and the filament pulled back by the same
        amount), so the slicer's next line runs as if nothing had happened. Retracts for the first
        hop, the way back, and any hop longer than `retract_over`; short hops between
        neighbouring pins only lift. With labelled objects (Klipper EXCLUDE_OBJECT, M486) each
        object's pins get their own label block, so cancelling an object skips its pins."""
        s = self.s
        st = L.state
        travel = s.travel_speed * 60.0
        zhop = max(z, st.z) + s.hop
        feed = s.flow_rate / area_f * 60.0
        fw = self.fw
        target = 0.0 if fw else max(r_amount, st.owed or 0.0)   # pulled back while travelling
        pre = 0.0 if fw else max(0.0, target - (st.owed or 0.0))
        out = ["%s: %d pins\n" % (MARKER, len(pins))]
        if st.abs_e:
            out.append("M83 %s relative E for the pins\n" % MARKER)

        def pull(amount):
            if fw:
                out.append("G10\n")
            elif amount > 0:
                out.append("G1 E-%s F%s\n" % (_fmt(amount, 4), _fmt(r_speed, 0)))

        def push(amount):
            if fw:
                out.append("G11\n")
            elif amount > 0:
                out.append("G1 E%s F%s\n" % (_fmt(amount, 4), _fmt(r_speed, 0)))

        # start: pulled back by `target` (the slicer may already have done part of it)
        if fw:
            if not st.fw:
                pull(0)
        else:
            pull(pre)
        out.append("G1 Z%s F600\n" % _fmt(zhop))
        retracted = True
        seconds = 0.0
        x0, y0 = st.x, st.y
        groups = []
        for pin in pins:
            if groups and groups[-1][0] == pin[3]:
                groups[-1][1].append(pin)
            else:
                groups.append((pin[3], [pin]))
        if self.labels:                       # one label block per object
            merged = {}
            for owner, group in groups:
                merged.setdefault(owner, []).extend(group)
            groups = sorted(merged.items())
        for owner, group in groups:
            group = _order(group, x0, y0)
            name = self.objects[owner - 1] if self.labels and owner else None
            if name is not None:
                out.append("EXCLUDE_OBJECT_START NAME=%s\n" % name if self.labels == "klipper"
                           else "M486 S%d\n" % name)
            for n, (x, y, volume, _o) in enumerate(group):
                hop = math.hypot(x - x0, y - y0)
                if not retracted and hop > s.retract_over:
                    pull(target)
                    retracted = True
                out.append("G1 X%s Y%s F%s\n" % (_fmt(x), _fmt(y), _fmt(travel, 0)))
                out.append("G1 Z%s F600\n" % _fmt(z))
                if retracted:
                    push(target)
                    retracted = False
                out.append("G1 E%s F%s %s pin %.1f mm3\n" % (_fmt(volume / area_f, 5), _fmt(feed, 1), MARKER, volume))
                if s.dwell > 0:
                    out.append("G4 P%d\n" % int(round(s.dwell * 1000)))
                out.append("G1 Z%s F600\n" % _fmt(zhop))
                seconds += volume / s.flow_rate + s.dwell + hop / s.travel_speed + 0.2 * s.hop + 0.3
                x0, y0 = x, y
            if name is not None:
                if not retracted:              # never leave a label block with the nozzle primed
                    pull(target)
                    retracted = True
                out.append("EXCLUDE_OBJECT_END NAME=%s\n" % name if self.labels == "klipper"
                           else "M486 S-1\n")
        if not retracted:
            pull(target)
        out.append("G1 X%s Y%s F%s\n" % (_fmt(st.x), _fmt(st.y), _fmt(travel, 0)))
        out.append("G1 Z%s F600\n" % _fmt(st.z))     # exactly where the slicer left the nozzle
        # back to the slicer's own pulled-back state
        if fw:
            if not st.fw:
                push(0)
        else:
            push(pre)
        if st.abs_e:
            out.append("M82 %s back to absolute E\n" % MARKER)
            out.append("G92 E%s\n" % _fmt(st.e, 5))
        if st.f:
            out.append("G1 F%s\n" % _fmt(st.f, 0))
        out.append("%s: end of pins\n" % MARKER)
        self.stats.extra_time += seconds
        return out


def _apply(lines, inserts):
    out = []
    for i, line in enumerate(lines):
        out.append(line)
        if i in inserts:
            if not line.endswith("\n"):
                out[-1] = line + "\n"
            out.extend(inserts[i])
    return out


def _notes_diameter(text):
    m = re.search(r"^; ?filament_diameter\s*=\s*([\d.]+)", text, re.M)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return 0.0
    return 0.0


def process_lines(lines, settings=None):
    """Returns (new lines, Stats)."""
    settings = (settings or Settings()).validate()
    engine = Engine(settings)
    tail = "".join(lines[-200:])
    if MARKER in tail or any(MARKER in ln for ln in lines[:200]):
        engine.stats.already = True
        return list(lines), engine.stats
    if settings.filament_diameter <= 0:
        d = _notes_diameter(tail + "".join(lines[:400]))
        if d > 0:
            settings.filament_diameter = d
    inserts = engine.plan(lines)
    out = _apply(lines, inserts)
    if engine.stats.pins:
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        out.extend(t + "\n" for t in engine.stats.summary_lines(settings))
    return out, engine.stats


def process_chunks(chunks, settings=None):
    """Cura hands G-code over as a list of text chunks. Returns (new chunks, Stats)."""
    lines = []
    owner = []
    for n, chunk in enumerate(chunks):
        for part in chunk.splitlines(True):
            lines.append(part)
            owner.append(n)
    settings = (settings or Settings()).validate()
    engine = Engine(settings)
    for chunk in list(chunks[:2]) + list(chunks[-3:]):
        if MARKER in chunk:
            engine.stats.already = True
            return list(chunks), engine.stats
    if settings.filament_diameter <= 0:
        settings.filament_diameter = _notes_diameter("".join(chunks[:1]) + "".join(chunks[-1:]))
    inserts = engine.plan(lines)
    parts = [[] for _ in chunks]
    for i, line in enumerate(lines):
        parts[owner[i]].append(line)
        if i in inserts:
            if not line.endswith("\n"):
                parts[owner[i]][-1] = line + "\n"
            parts[owner[i]].extend(inserts[i])
    result = ["".join(p) for p in parts]
    if engine.stats.pins and result:
        tail = result[-1]
        nl = "" if (not tail or tail.endswith("\n")) else "\n"
        result[-1] = tail + nl + "\n".join(engine.stats.summary_lines(settings)) + "\n"
    return result, engine.stats


def process_file(path, out_path=None, settings=None):
    with open(path, "rb") as fh:
        head = fh.read(4)
    if head == b"GCDE":
        raise PinLokError(
            "PinLoK cannot read binary G-code (.bgcode). In PrusaSlicer switch off binary G-code "
            "(Printer Settings > General) and slice again.")
    with open(path, "r", encoding="utf-8", errors="surrogateescape", newline="") as fh:
        lines = fh.readlines()
    out, stats = process_lines(lines, settings)
    if stats.already or (not stats.pins and not out_path):
        return stats
    target = out_path or path
    tmp = target + ".pinlok.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
            fh.writelines(out)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return stats


def _data_dir():
    return os.path.join(os.path.expanduser("~"), ".lokwalls")


def load_settings(path=None, settings=None):
    """Reads pinlok.ini (key = value lines) if there is one."""
    settings = settings or Settings()
    path = path or os.path.join(_data_dir(), "pinlok.ini")
    if not os.path.isfile(path):
        return settings
    with open(path, "r", encoding="utf-8") as fh:
        raws = fh.readlines()
    for raw in raws:                       # the mode first, so single settings can override it
        line = raw.split("#", 1)[0].strip()
        if "=" in line and line.split("=", 1)[0].strip() == "mode":
            value = line.split("=", 1)[1].strip().lower()
            if value in MODES:
                settings.apply_mode(value)
    for raw in raws:
        line = raw.split("#", 1)[0].strip()
        if "=" not in line:
            continue
        key, value = [t.strip() for t in line.split("=", 1)]
        if not hasattr(settings, key) or key == "mode":
            continue
        current = getattr(settings, key)
        try:
            if isinstance(current, bool):
                setattr(settings, key, value.lower() in ("1", "true", "yes", "on"))
            elif isinstance(current, int):
                setattr(settings, key, int(value))
            else:
                setattr(settings, key, float(value))
        except ValueError:
            pass
    return settings


def _log(message):
    try:
        folder = _data_dir()
        if not os.path.isdir(folder):
            return
        path = os.path.join(folder, "pinlok.log")
        if os.path.isfile(path) and os.path.getsize(path) > 200000:
            os.replace(path, path + ".old")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), message))
    except OSError:
        pass


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        prog="pinlok",
        description="PinLoK %s (WORK IN PROGRESS) - pinned infill. Give it a G-code file sliced "
                    "with Grid or Rectilinear infill (about 35%%); it is changed in place." % __version__)
    parser.add_argument("gcode", nargs="?")
    parser.add_argument("-o", "--output")
    parser.add_argument("--mode", choices=sorted(MODES),
                        help="potato (default: small quick pins for stock printers), balanced, "
                             "or performance (fast hot ends)")
    parser.add_argument("--every", type=int, help="a pin layer every N layers")
    parser.add_argument("--flow", type=float, help="mm3/s while pushing a pin")
    parser.add_argument("--config", help="path to pinlok.ini")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--version", action="version",
                        version="PinLoK %s (Built %s) WORK IN PROGRESS" % (__version__, __build_date__))
    args = parser.parse_args(argv)
    if not args.gcode:
        parser.print_help()
        return 2
    try:
        s = load_settings(args.config)
        if args.mode:
            s.apply_mode(args.mode)
        if args.every:
            s.every = args.every
        if args.flow:
            s.flow_rate = args.flow
        s.validate()
        if not s.enabled:
            return 0
        stats = process_file(args.gcode, args.output, s)
    except PinLokError as exc:
        sys.stderr.write("%s\n" % exc)
        _log("%s: ERROR %s" % (args.gcode, exc))
        return 1
    except Exception as exc:
        import traceback
        sys.stderr.write("PinLoK failed and left the G-code untouched: %r\n" % (exc,))
        traceback.print_exc()
        _log("%s: CRASH %r" % (args.gcode, exc))
        return 1
    message = stats.human() + " (%.1f s)" % stats.seconds
    _log("%s: %s" % (os.environ.get("SLIC3R_PP_OUTPUT_NAME") or args.gcode, message))
    if not args.quiet:
        print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
