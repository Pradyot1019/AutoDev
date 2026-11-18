import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams.update({"font.family": "serif",
    "font.serif": ["Times New Roman", "Liberation Serif", "Nimbus Roman", "TeX Gyre Termes", "DejaVu Serif"],
    "font.size": 8, "axes.spines.top": False, "axes.spines.right": False})
NAVY, PURPLE, RED, GREY = "#00487F", "#7030A0", "#C00000", "#999999"

d = json.load(open("results_rq1_rq2.json"))["rq1"]["by_operator"]
names = {"syntax_error": "Syntax\nerror", "undefined_name": "Undefined\nname", "missing_import": "Missing\nimport",
         "invalid_json": "Invalid\nJSON", "arith_swap": "Arith.\nswap", "compare_swap": "Compare\nswap", "return_none": "Return\nNone"}
ops = list(names)
fig, ax = plt.subplots(figsize=(3.5, 2.3))
w = 0.26
for i, (key, col, lab) in enumerate([("static", PURPLE, "Static gate"), ("tests", NAVY, "Test runner"), ("either", RED, "Combined")]):
    xs = [j + (i - 1) * w for j in range(len(ops))]
    ys = [100 * d[o][key] / d[o]["n"] for o in ops]
    ax.bar(xs, ys, w, color=col, label=lab)
for j, o in enumerate(ops):
    ax.text(j, 106, f"n={d[o]['n']}", ha="center", fontsize=6.5, color="#555")
ax.set_xticks(range(len(ops)))
ax.set_xticklabels([names[o] for o in ops], fontsize=6.5)
ax.set_ylim(0, 118); ax.set_yticks([0, 20, 40, 60, 80, 100])
ax.set_ylabel("Faults detected (%)")
ax.yaxis.grid(True, color="#ddd", lw=0.5); ax.set_axisbelow(True)
ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.2), ncol=3, frameon=False, fontsize=7)
fig.tight_layout()
fig.savefig("/home/claude/paper/figs/fig4_fault_detection.png", dpi=300)

b = json.load(open("results_rq3.json"))["token_budget"]
order = [("none", "None", GREY), ("static", "Static\n12k", PURPLE), ("autodev", "AutoDev", RED), ("oracle", "Oracle\n8k", NAVY)]
fig, (a1, a2) = plt.subplots(1, 2, figsize=(3.5, 1.9))
for ax, key, title, fmt in [(a1, "rejections", "HTTP 429 rejections", "{:d}"), (a2, "makespan_min", "Makespan (min)", "{:.1f}")]:
    vals = [b[k][key] for k, _, _ in order]
    ax.bar(range(4), vals, color=[c for _, _, c in order])
    for j, v in enumerate(vals):
        ax.text(j, v + max(vals) * 0.02, fmt.format(v), ha="center", fontsize=7)
    ax.set_xticks(range(4)); ax.set_xticklabels([l for _, l, _ in order], fontsize=6)
    ax.set_title(title, fontsize=8); ax.set_ylim(0, max(vals) * 1.18)
fig.tight_layout()
fig.savefig("/home/claude/paper/figs/fig5_rate_limit.png", dpi=300)
print("ok")
