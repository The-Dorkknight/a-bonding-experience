"""Draws figures/every-idea.png from the simulation results quoted in PAPER.md."""
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
rows=[("Shift-LoK (half-layer stagger) *",-7,10,"w"),
("Other stagger sizes (¼, ⅓, 3- and 4-phase) *",-5,4,"w"),
("Different layer height per wall",-11,-1,"w"),
("FlatLock (fat / thin walls)",-17,-4,"w"),
("Squish-LoK (over-extruded squish bead)",-8,1,"w"),
("Squish-KeyLoK (gaps + keys)",-19,3,"w"),
("Sideways brick bond (mixed widths)",3,6,"w"),
("Wide inner walls 1.33x (0.6 mm)",2,4,"w"),
("Wide inner walls 2x",4,9,"w"),
("Wide inner walls 4x (too wide for a 0.4 nozzle)",5,13,"w"),
("PinLoK modes, Grid 35 %",16,27,"p")][::-1]
fig,ax=plt.subplots(figsize=(10,5.9))
fig.patch.set_facecolor("#fcfcfb"); ax.set_facecolor("#fcfcfb")
C={"w":"#2a78d6","p":"#eb6834"}
for k,(n,a,b,g) in enumerate(rows):
    ax.plot([a,b],[k,k],color=C[g],lw=6,solid_capstyle="round")
    ax.plot([a,b],[k,k],"o",color=C[g],ms=8,mec="#fcfcfb",mew=2)
    ax.text(max(a,b)+1.2,k,"%+d to %+d %%"%(a,b),va="center",fontsize=8.5,color="#52514e")
ax.axvline(0,color="#0b0b0b",lw=1)
ax.axvline(7,color="#52514e",lw=1,ls=(0,(3,3)))
ax.text(7.4,-0.75,"7 % target",fontsize=8.5,color="#52514e")
ax.set_ylim(-1,len(rows)-0.4)
ax.set_yticks(range(len(rows))); ax.set_yticklabels([r[0] for r in rows],fontsize=9,color="#0b0b0b")
ax.set_xlabel("Simulated change in strength pulling layers apart (Z), %",fontsize=9,color="#52514e")
ax.set_xlim(-22,36)
for s in ("top","right","left"): ax.spines[s].set_visible(False)
ax.tick_params(axis="y",length=0); ax.tick_params(axis="x",colors="#52514e",labelsize=8.5)
ax.grid(axis="x",color="#e6e5e1",lw=0.8); ax.set_axisbelow(True)
fig.legend(handles=[Line2D([0],[0],color=C["w"],lw=6,label="walls, compared with normal walls"),
                   Line2D([0],[0],color=C["p"],lw=6,label="infill, compared with solid infill of the same weight")],
          loc="upper left",bbox_to_anchor=(0.01,0.935),ncol=2,fontsize=8.5,frameon=False)
fig.suptitle("Every idea in one picture: THEORETICAL results from a 2-D simulation, not print tests",fontsize=11,x=0.01,ha="left",y=0.985)
fig.text(0.01,0.055,"Bars span the simulation's assumptions: Shift-LoK and FlatLock over every assumption tried; the others over rounder or sharper bead corners",fontsize=7.5,color="#52514e")
fig.text(0.01,0.032,"(Squish-KeyLoK and PinLoK also over the two ways of breaking: all welds holding together, or snapping one by one; PinLoK also over its three modes).",fontsize=7.5,color="#52514e")
fig.text(0.01,0.009,"* a stagger needs beads of different heights at the bottom and top of the wall. A Bonding Experience, M. Armstrong, 2026, CC BY-SA 4.0.",fontsize=7.5,color="#52514e")
plt.tight_layout(rect=(0,0.075,1,0.9)); plt.savefig("figures/every-idea.png",dpi=130)
