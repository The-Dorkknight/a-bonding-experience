# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
import math
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import gen_pinlok as G                      # noqa: E402
from pinlok import engine as P              # noqa: E402

PIN = re.compile(r"PinLoK pin ([\d.]+) mm3")


def simulate(lines):
    """Runs the moves like a printer would. Returns (list of extruding moves as
    (line index, layer, x0, y0, x1, y1, de), pins as (layer, x, y, z, de), final filament position,
    lowest filament position relative to the last extrusion)."""
    x = y = z = 0.0
    e = 0.0          # logical E (what the G-code says)
    fil = 0.0        # filament actually pushed (relative sum)
    absolute = True
    layer = -1
    moves, pins = [], []
    for i, raw in enumerate(lines):
        s = raw.strip()
        if s.startswith(";LAYER:") or s == ";LAYER_CHANGE" or s.startswith("; CHANGE_LAYER"):
            layer += 1
            continue
        code = s.split(";", 1)[0].strip()
        if not code:
            continue
        parts = code.split()
        head = parts[0].upper()
        w = dict((p[0].upper(), float(p[1:])) for p in parts[1:] if len(p) > 1 and p[0].isalpha())
        if head == "M82":
            absolute = True
        elif head == "M83":
            absolute = False
        elif head == "G92":
            if "E" in w:
                e = w["E"]
        elif head in ("G0", "G1"):
            nx, ny, nz = w.get("X", x), w.get("Y", y), w.get("Z", z)
            de = 0.0
            if "E" in w:
                de = (w["E"] - e) if absolute else w["E"]
                e = w["E"] if absolute else e + w["E"]
                fil += de
            if de > 0 and (nx != x or ny != y):
                moves.append((i, layer, x, y, nx, ny, de))
            if de > 0 and nx == x and ny == y and "PinLoK pin" in raw:
                pins.append((layer, x, y, z, de))
            x, y, z = nx, ny, nz
    return moves, pins, fil


def dist_seg(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / L2))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def run(**kw):
    text = G.box(**kw)
    lines = text.splitlines(True)
    out, stats = P.process_lines(lines)
    return lines, out, stats


class Basics(unittest.TestCase):
    def test_grid_gets_pins_and_original_lines_are_kept(self):
        lines, out, st = run()
        self.assertGreater(st.pins, 100)
        # every original line is still there, in order
        it = iter(out)
        for line in lines:
            for o in it:
                if o == line:
                    break
            else:
                self.fail("original line lost: %r" % line)
        self.assertIn("; PinLoK", "".join(out[-3:]))

    def test_extrusion_of_original_moves_unchanged(self):
        for kw in (dict(), dict(flavour="prusa", relative=True), dict(flavour="bambu", relative=True),
                   dict(flavour="orca")):
            lines, out, st = run(**kw)
            a, _, fa = simulate(lines)
            b, pins, fb = simulate(out)
            self.assertEqual(len(a), len(b), kw)
            for m1, m2 in zip(a, b):
                self.assertAlmostEqual(m1[6], m2[6], places=4, msg=kw)
                self.assertEqual(m1[2:6], m2[2:6])
            pinned = sum(p[4] for p in pins)
            self.assertGreater(pinned, 0)
            # all extra filament goes into pins; retracts and unretracts cancel out
            self.assertAlmostEqual(fb - fa, pinned, places=3, msg=kw)

    def test_pins_are_inside_channels(self):
        for kw in (dict(), dict(angle=45), dict(pattern="rectilinear"), dict(hole=8)):
            lines, out, st = run(**kw)
            moves, pins, _ = simulate(out)
            self.assertTrue(pins, kw)
            by_layer = {}
            for m in moves:
                by_layer.setdefault(m[1], []).append(m)
            for (layer, x, y, z, de) in pins:
                near = min(dist_seg(x, y, *m[2:6]) for m in by_layer[layer])
                self.assertGreater(near, 0.4, "pin on a line at layer %d %s" % (layer, kw))
                self.assertLess(abs(x - 100) , 15.0)
                if kw.get("hole"):
                    self.assertFalse(abs(x - 100) < 4.5 and abs(y - 100) < 4.5, "pin in the hole")

    def test_pin_layers_alternate(self):
        lines, out, st = run(layers=40)
        _, pins, _ = simulate(out)
        layers = sorted(set(p[0] for p in pins))
        self.assertGreaterEqual(len(layers), 4)
        sets = [set((round(p[1], 1), round(p[2], 1)) for p in pins if p[0] == L) for L in layers]
        for s1, s2 in zip(sets, sets[1:]):
            self.assertFalse(s1 & s2, "the same channel was pinned on two pin layers in a row")
        for s1, s3 in zip(sets, sets[2:]):
            self.assertTrue(len(s1 & s3) > 0.6 * len(s1), "A and B should come back every other pin layer")

    def test_no_pins_in_skins_or_first_layers(self):
        lines, out, st = run(skins=4, layers=30)
        _, pins, _ = simulate(out)
        self.assertTrue(all(4 <= p[0] < 26 for p in pins), sorted(set(p[0] for p in pins)))

    def test_too_sparse_and_no_channels_explained(self):
        lines, out, st = run(density=0.12)
        self.assertGreater(st.too_wide, 0)
        if not st.pins:
            self.assertIn("too wide", st.human())
        lines, out, st = run(pattern="shifting", density=0.2)
        self.assertIn("PinLoK", st.human())

    def test_retraction_follows_the_file(self):
        lines, out, st = run(retract=5.0)
        self.assertAlmostEqual(st.retract, 5.0)
        text = "".join(out)
        self.assertIn("G1 E-5 F2400", text)

    def test_runs_once(self):
        lines, out, st = run()
        out2, st2 = P.process_lines(out)
        self.assertTrue(st2.already)
        self.assertEqual(out2, out)

    def test_chunks_like_cura(self):
        text = G.box()
        chunks = []
        cur = []
        for line in text.splitlines(True):
            if line.startswith(";LAYER:") and cur:
                chunks.append("".join(cur))
                cur = []
            cur.append(line)
        chunks.append("".join(cur))
        new, st = P.process_chunks(chunks)
        self.assertEqual(len(new), len(chunks))
        lines, out, st2 = run()
        self.assertEqual(st.pins, st2.pins)
        self.assertEqual("".join(new), "".join(out))

    def test_file_in_place_and_absolute_e_restored(self):
        text = G.box(relative=False)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.gcode")
            with open(path, "w") as fh:
                fh.write(text)
            st = P.process_file(path)
            self.assertGreater(st.pins, 0)
            out = open(path).read()
        blocks = out.split("; PinLoK: end of pins")
        self.assertGreater(len(blocks), 1)
        self.assertIn("M83 ; PinLoK", out)
        self.assertIn("M82 ; PinLoK", out)
        self.assertEqual(out.count("M83 ; PinLoK"), out.count("M82 ; PinLoK"))

    def test_volume_and_flow_limits(self):
        lines, out, st = run()
        text = "".join(out)
        vols = [float(v) for v in PIN.findall(text)]
        self.assertTrue(vols)
        self.assertLessEqual(max(vols), P.Settings().max_pin_volume + 1e-6)
        area = math.pi * 1.75 ** 2 / 4.0
        feeds = [float(m) for m in re.findall(r"G1 E[\d.]+ F([\d.]+) ; PinLoK pin", text)]
        self.assertTrue(all(abs(f / 60.0 * area - P.Settings().flow_rate) < 0.05 for f in feeds))

    def test_modes(self):
        text = G.box(layers=40).splitlines(True)
        res = {}
        for mode in ("potato", "balanced", "performance"):
            out, st = P.process_lines(text, P.Settings(mode))
            _, pins, _ = simulate(out)
            vols = [float(v) for v in PIN.findall("".join(out))]
            res[mode] = (st, pins, vols)
            self.assertLessEqual(max(vols), P.MODES[mode]["max_pin_volume"] + 1e-6)
            layers = sorted(set(p[0] for p in pins))
            gaps = set(b - a for a, b in zip(layers, layers[1:]))
            self.assertEqual(gaps, {P.MODES[mode]["every"]}, mode)
        # potato: more, smaller pins, each pushed in about a second or less
        self.assertGreater(res["potato"][0].pins, res["balanced"][0].pins)
        self.assertLess(max(res["potato"][2]), max(res["balanced"][2]))
        self.assertLess(max(res["potato"][2]) / P.MODES["potato"]["flow_rate"], 1.05)
        # performance pushes faster
        self.assertLess(res["performance"][0].extra_time, res["balanced"][0].extra_time)
        with self.assertRaises(P.PinLokError):
            P.Settings("turbo")

    def test_pins_keep_up_with_the_part(self):
        """Each pin tops its gap up to a fixed depth, so pins never fall further and further
        behind on a tall part: the pin volume settles to the same value."""
        for mode in ("potato", "balanced"):
            out, st = P.process_lines(G.box(layers=80).splitlines(True), P.Settings(mode))
            _, pins, _ = simulate(out)
            by = {}
            for p in pins:
                by.setdefault(p[0], []).append(p[4])
            layers = sorted(by)
            mean = [sum(by[L]) / len(by[L]) for L in layers]
            late = mean[len(mean) // 2:-1]
            self.assertLess(max(late) - min(late), 0.05 * max(late), (mode, mean))

    def test_ini_mode_then_overrides(self):
        with tempfile.TemporaryDirectory() as d:
            ini = os.path.join(d, "pinlok.ini")
            with open(ini, "w") as fh:
                fh.write("flow_rate = 5\nmode = performance\n")
            s = P.load_settings(ini)
            self.assertEqual(s.mode, "performance")
            self.assertEqual(s.every, 4)
            self.assertEqual(s.flow_rate, 5.0)

    def _two_objects(self, style):
        def split(text):
            head, lays = [], []
            for line in text.splitlines(True):
                if line.startswith(";LAYER_CHANGE"):
                    lays.append([])
                (lays[-1] if lays else head).append(line)
            return head, lays
        ha, la = split(G.box("prusa", centre=60, relative=True))
        _hb, lb = split(G.box("prusa", centre=140, relative=True))
        out = list(ha)
        for a, b in zip(la, lb):
            out += a[:2]
            if style == "klipper":
                out += ["EXCLUDE_OBJECT_START NAME=A\n"] + a[2:] + ["EXCLUDE_OBJECT_END NAME=A\n"]
                out += ["EXCLUDE_OBJECT_START NAME=B\n"] + b[2:] + ["EXCLUDE_OBJECT_END NAME=B\n"]
            else:
                out += ["M486 S0\n"] + a[2:] + ["M486 S-1\n"]
                out += ["M486 S1\n"] + b[2:] + ["M486 S-1\n"]
        return out

    def test_object_labels_wrap_each_objects_pins(self):
        for style in ("klipper", "m486"):
            lines = self._two_objects(style)
            out, st = P.process_lines(lines)
            self.assertGreater(st.pins, 50, style)
            current = None
            x = 0.0
            seen = {"A": 0, "B": 0}
            for line in out:
                s = line.strip()
                if s.startswith("EXCLUDE_OBJECT_START"):
                    current = s.split("NAME=")[1]
                elif s.startswith("EXCLUDE_OBJECT_END") or s == "M486 S-1":
                    current = None
                elif s.startswith("M486 S"):
                    current = "A" if s == "M486 S0" else "B"
                m = re.search(r"X([\d.]+)", s)
                if m and s.startswith("G1"):
                    x = float(m.group(1))
                if "PinLoK pin" in s:
                    self.assertIsNotNone(current, "pin outside any object label (%s)" % style)
                    self.assertEqual(current, "A" if x < 100 else "B", style)
                    seen[current] += 1
            self.assertTrue(seen["A"] and seen["B"], seen)
            # the block never sits inside the slicer's own label block
            depth = 0
            for line in out:
                s = line.strip()
                if s.startswith("; PinLoK: ") and "end" not in s:
                    self.assertIsNone(None if depth == 0 else depth)
                if s.startswith("EXCLUDE_OBJECT_START") or (s.startswith("M486 S") and s != "M486 S-1"):
                    depth += 1
                elif s.startswith("EXCLUDE_OBJECT_END") or s == "M486 S-1":
                    depth -= 1

    def test_firmware_retraction_uses_g10_g11(self):
        text = G.box(flavour="prusa", relative=True)
        text = re.sub(r"G1 F2400 E-0\.80000", "G10", text)
        text = re.sub(r"G1 F2400 E0\.80000", "G11", text)
        out, st = P.process_lines(text.splitlines(True))
        self.assertGreater(st.pins, 0)
        block = "".join(out)
        blocks = re.findall(r"; PinLoK: \d+ pins\n(.*?); PinLoK: end of pins", block, re.S)
        self.assertTrue(blocks)
        for b in blocks:
            self.assertNotRegex(b, r"G1 E-")
            self.assertIn("G11", b)

    def test_relative_xyz_layers_skipped_and_multitool_refused(self):
        text = G.box()
        lines = text.splitlines(True)
        out, st = P.process_lines(lines)
        self.assertGreater(st.pins, 0)
        # a G91 left on at the end of every layer
        bad = []
        for line in lines:
            if line.startswith(";LAYER:"):
                bad.append("G91\n")
            bad.append(line)
            if line.startswith(";LAYER:"):
                bad.append("G90\n")
        out, st = P.process_lines(bad)
        self.assertEqual(st.pins, 0)
        self.assertIn("G91", st.human())
        two = lines[:]
        k = next(i for i, l in enumerate(two) if l.startswith(";LAYER:10"))
        two[k:k] = ["T1\n"]
        two.insert(4, "T0\n")
        out, st = P.process_lines(two)
        self.assertEqual(st.pins, 0)
        self.assertIn("extruder", st.human())

    def test_retraction_measured_with_wipe(self):
        text = G.box(flavour="prusa", relative=True, retract=0.8)
        # slicer that does part of the retraction while wiping: 0.6 while moving, 0.2 standing
        text = text.replace("G1 F2400 E-0.80000", "G1 X100.5 Y100.5 E-0.6\nG1 F2400 E-0.20000")
        out, st = P.process_lines(text.splitlines(True))
        self.assertAlmostEqual(st.retract, 0.8)

    def test_binary_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.bgcode")
            with open(path, "wb") as fh:
                fh.write(b"GCDE\x01\x00")
            with self.assertRaises(P.PinLokError):
                P.process_file(path)

    def test_cli_version(self):
        with self.assertRaises(SystemExit):
            P.main(["--version"])


if __name__ == "__main__":
    unittest.main()
