---
title: "I tried 12 ways to make 3D prints stronger between layers without stepping on a patent. One worked."
published: false
tags: 3dprinting, python, opensource, engineering
---

Printed parts snap along their layer lines like a KitKat. The well-known fix, staggering walls by half a layer ("brick layers"), is patented in the US. So I did what any reasonable person does when told "no": I spent a week finding every other way.

Dangling a design challenge in front of an engineer is like dangling catnip in front of a cat. Here's what came out of it.

**The short version**

- The "loopholes" aren't. Any half-layer stagger needs beads of different heights at the bottom and top of the part, and that's the patented bit. Geometry doesn't care about wording.
- Fat/thin walls, over-extruded "squish" beads and keyed gaps all did nothing or made things worse in my strength model. One of them made the crack *easier*.
- Wide inner walls (about 1.5 × the nozzle) helped a bit, and it's just a slicer setting.
- **Pinned infill (PinLoK)** won. Every few layers the nozzle stops over the gaps in Grid infill and pushes a blob of plastic down into each one, taking turns so the joints never line up. In my simulation it's 16 to 27 % stronger across the layers than solid infill of the same weight (theoretical; not printed yet). The trick that made the difference: end each pin half-way through a layer, never on a layer line. It builds on Oak Ridge National Laboratory's published Z-pinning, and it has a **potato mode** for stock Ender 3s.

**Why publish?** Once a method is published, nobody can patent it afterwards. The paper includes a full defensive disclosure, so PinLoK stays free for hobbyists. Also, more cool techniques come back to me, and I'm now 22.713333…% more employable. High-efficiency synergy.

**The honest bit:** every strength number here is theoretical, from a simulation, not from printed parts. If you have a printer and a bucket of weights, the test plan is in section 10. Please tell me who wins.

📄 Paper, code and data: https://github.com/The-Dorkknight/a-bonding-experience
🔖 DOI: *(add after Zenodo)*
