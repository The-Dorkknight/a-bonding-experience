# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Synthetic G-code for the PinLoK tests: a square box with walls, solid bottom/top skins and
sparse infill (grid = both directions every layer, rectilinear = alternating, gyroidish = lines
that move every layer so no channel stays open). Optional square hole through the middle."""
import math

FLAVOURS = {
    "cura": (";LAYER:%d", ";TYPE:WALL-OUTER", ";TYPE:FILL", ";TYPE:SKIN"),
    "prusa": (";LAYER_CHANGE", ";TYPE:External perimeter", ";TYPE:Internal infill", ";TYPE:Solid infill"),
    "orca": (";LAYER_CHANGE", ";TYPE:Outer wall", ";TYPE:Sparse infill", ";TYPE:Internal solid infill"),
    "bambu": ("; CHANGE_LAYER", "; FEATURE: Outer wall", "; FEATURE: Sparse infill", "; FEATURE: Internal solid infill"),
}


def box(flavour="cura", size=30.0, layers=30, h=0.2, w=0.45, density=0.35, pattern="grid",
        angle=0.0, relative=False, hole=0.0, skins=3, walls=2, filament=1.75, centre=100.0,
        retract=0.8):
    marker, t_wall, t_fill, t_skin = FLAVOURS[flavour]
    area = math.pi * filament * filament / 4.0
    e_mm = (w - h * (1 - math.pi / 4)) * h / area
    out = []
    add = out.append
    add("; synthetic %s box for PinLoK" % flavour)
    add("G90")
    add("M83" if relative else "M82")
    add("G92 E0")
    st = dict(x=0.0, y=0.0, e=0.0)

    def move(x, y):
        add("G0 F6000 X%.3f Y%.3f" % (x, y))
        st["x"], st["y"] = x, y

    def ext(x, y):
        d = math.hypot(x - st["x"], y - st["y"])
        a = d * e_mm
        if relative:
            add("G1 F1800 X%.3f Y%.3f E%.5f" % (x, y, a))
        else:
            st["e"] += a
            add("G1 F1800 X%.3f Y%.3f E%.5f" % (x, y, st["e"]))
        st["x"], st["y"] = x, y

    def retr(sign):
        if relative:
            add("G1 F2400 E%.5f" % (sign * retract))
        else:
            st["e"] += sign * retract
            add("G1 F2400 E%.5f" % st["e"])

    def square(c, half):
        move(c - half, c - half)
        for (x, y) in ((c + half, c - half), (c + half, c + half), (c - half, c + half), (c - half, c - half)):
            ext(x, y)

    half = size / 2.0
    inner = half - walls * w
    hh = hole / 2.0
    ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))

    def clip_line(off, direction):
        """Points along a line in the infill area (square inner, minus the hole), as pieces."""
        # line: p = centre + off*n + t*d, d = direction unit, n = normal
        dx, dy = direction
        nx, ny = -dy, dx
        pieces = []
        ts = [k * 0.05 for k in range(int(-size * 20), int(size * 20) + 1)]
        cur = []
        for t in ts:
            x = centre + off * nx + t * dx
            y = centre + off * ny + t * dy
            inside = abs(x - centre) <= inner - 0.05 and abs(y - centre) <= inner - 0.05
            if hole > 0 and abs(x - centre) <= hh + w and abs(y - centre) <= hh + w:
                inside = False
            if inside:
                cur.append((x, y))
            elif cur:
                pieces.append((cur[0], cur[-1]))
                cur = []
        if cur:
            pieces.append((cur[0], cur[-1]))
        return pieces

    for n in range(1, layers + 1):
        add(marker % (n - 1) if "%d" in marker else marker)
        z = n * h
        add("G0 Z%.3f" % z)
        add(t_wall)
        for k in range(walls):
            square(centre, half - w / 2.0 - k * w)
            if hole > 0:
                square(centre, hh + w / 2.0 + k * w)
        retr(-1)
        solid = n <= skins or n > layers - skins
        add(t_skin if solid else t_fill)
        spacing = w if solid else 2.0 * w / density
        if pattern == "rectilinear" or solid:
            dirs = [(ca, sa)] if n % 2 else [(-sa, ca)]
            if solid:
                spacing = w
        elif pattern == "grid":
            dirs = [(ca, sa), (-sa, ca)]
        else:                         # lines that shift every layer: no straight channels
            dirs = [(math.cos(math.radians(angle + 23 * n)), math.sin(math.radians(angle + 23 * n)))]
        first = True
        for d in dirs:
            shift = 0.0 if pattern != "shifting" else (n * 0.37) % spacing
            k = 0
            off = -size
            offs = []
            while off <= size:
                offs.append(off + shift)
                off += spacing
            flip = False
            for off in offs:
                for (a, b) in clip_line(off, d):
                    if flip:
                        a, b = b, a
                    flip = not flip
                    move(*a)
                    if first:
                        retr(+1)
                        first = False
                    ext(*b)
        retr(-1)
    add("M107")
    add("; end")
    return "\n".join(out) + "\n"
