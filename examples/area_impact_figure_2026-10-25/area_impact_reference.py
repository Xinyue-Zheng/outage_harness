"""Reference drawing of the area impact figure: ground truth against an agent run.

Input: one JSON file (see `--synthetic`, which writes a sample). Output: the
figures and the per-area paragraphs. No API call, no model; stored data only.

    python area_impact_reference.py --synthetic sample_dir   # writes sample input and draws it
    python area_impact_reference.py input.json out_dir       # draws a real input

Point rule, the same on both sides: a covered point is signal-degraded when at
least half of the backup cells that reach it are degraded (more than
SIGNAL_MARGIN_DB below the outage sector or below SERVICE_RSRP_DBM); congested
at hour h when at least half of its backups with a KPI row for h are above
LOAD_LIMIT_PERCENT. The input carries the counts per point; this script only
divides and draws.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from matplotlib.patches import Polygon

matplotlib.use("Agg")

SIGNAL_MARGIN_DB = 10
SERVICE_RSRP_DBM = -110
LOAD_LIMIT_PERCENT = 80
SPARSE_POINTS = 5
FRAME_KM = 30.0

Status = Literal["covered", "no_backup", "uncovered", "no_sample"]
Side = Literal["truth", "agent"]
Metric = Literal["signal", "capacity"]
SIDES: tuple[Side, ...] = ("truth", "agent")
METRICS: tuple[Metric, ...] = ("signal", "capacity")
CLASSES = ("total loss", "signal", "both", "capacity", "served", "unknown")
CLASS_COLORS = ("#7a2708", "#c9471c", "#9a3a12", "#ec835a", "#f8b893", "#d6d5cf")
TRUTH_COLOR = "#2a78d6"
AGENT_COLOR = "#1baf7a"
SEQ = LinearSegmentedColormap.from_list("share", ["#fde4d6", "#ec835a", "#7a2708"])
DIV = LinearSegmentedColormap.from_list("diff", ["#2a78d6", "#f0efec", "#e34948"])


class HourCounts(TypedDict):
    with_data: int
    congested: int


class PointRecord(TypedDict):
    x_km: float
    y_km: float
    area_ids: list[str]
    status: Status
    n_backups: int
    n_degraded: int
    hours: dict[str, HourCounts]


class AreaRecord(TypedDict, total=False):
    id: str
    name: str
    kind: str
    polygon_km: list[list[float]]
    extent_recall: (
        float | None
    )  # share of the truth's sampled points in the area that the run fetched; from score.json


class CaseInput(TypedDict):
    site: str
    outage_start: str
    hours: list[str]
    areas: list[AreaRecord]
    points: dict[str, list[PointRecord]]


@dataclass(frozen=True)
class AreaStats:
    n_points: int
    sampled: int
    covered: int
    no_backup: int
    sig_half: int
    sig_all: int
    cap_half: dict[str, int]
    cap_all: dict[str, int]
    cap_with_data: dict[str, int]
    classes: dict[str, list[int]]

    def share(self, count: int) -> float | None:
        return None if self.covered == 0 else count / self.covered


def area_stats(points: list[PointRecord], area_id: str, hours: list[str]) -> AreaStats:
    pts = [p for p in points if area_id in p["area_ids"]]
    sampled = [p for p in pts if p["status"] != "no_sample"]
    covered = [p for p in sampled if p["status"] in ("covered", "no_backup")]
    with_backup = [p for p in covered if p["status"] == "covered"]
    sig_half = sum(p["n_degraded"] * 2 >= p["n_backups"] for p in with_backup)
    sig_all = sum(p["n_degraded"] == p["n_backups"] for p in with_backup)
    cap_half: dict[str, int] = {}
    cap_all: dict[str, int] = {}
    cap_with_data: dict[str, int] = {}
    classes: dict[str, list[int]] = {}
    for h in hours:
        counts = [0] * len(CLASSES)
        half = every = withdata = 0
        for p in covered:
            if p["status"] == "no_backup":
                counts[0] += 1
                continue
            hc = p["hours"].get(h)
            sig = p["n_degraded"] * 2 >= p["n_backups"]
            if hc is None or hc["with_data"] == 0:
                counts[5] += 1
                continue
            withdata += 1
            cap = hc["congested"] * 2 >= hc["with_data"]
            half += cap
            every += hc["congested"] == hc["with_data"]
            counts[2 if sig and cap else 1 if sig else 3 if cap else 4] += 1
        cap_half[h], cap_all[h], cap_with_data[h], classes[h] = (
            half,
            every,
            withdata,
            counts,
        )
    return AreaStats(
        len(pts),
        len(sampled),
        len(covered),
        len(covered) - len(with_backup),
        sig_half,
        sig_all,
        cap_half,
        cap_all,
        cap_with_data,
        classes,
    )


def pct(v: float | None) -> str:
    return "–" if v is None else f"{round(v * 100)} %"


def signed(v: float) -> str:
    return f"{'+' if v >= 0 else ''}{round(v * 100)}"


# ---------------------------------------------------------------- drawing
def draw_map(
    ax: Axes,
    case: CaseInput,
    side: Side,
    metric: Metric,
    hour: str,
    stats: dict[str, dict[Side, AreaStats]],
) -> None:
    ax.set_xlim(-FRAME_KM / 2, FRAME_KM / 2)
    ax.set_ylim(FRAME_KM / 2, -FRAME_KM / 2)
    ax.set_aspect("equal")
    ax.set_xticks(range(-15, 16, 5))
    ax.set_yticks(range(-15, 16, 5))
    ax.grid(True, color="#ecebe6", linewidth=0.6)
    ax.tick_params(labelsize=6, colors="#52514e")
    points = case["points"][side]
    for area in case["areas"]:
        poly = np.array(area["polygon_km"])
        st = stats[area["id"]][side]
        present = st.n_points > 0
        ax.add_patch(
            Polygon(
                poly,
                closed=True,
                fill=not present,
                hatch="////" if not present else None,
                facecolor="#fcfcfb",
                edgecolor="#52514e",
                linewidth=0.7,
                linestyle="--" if st.n_points and st.sampled < SPARSE_POINTS else "-",
            )
        )
        if present:
            label = (
                f"{area['id']} · signal {pct(st.share(st.sig_half))} · no backup {pct(st.share(st.no_backup))}"
                if metric == "signal"
                else f"{area['id']} · congested {hour} {pct(st.share(st.cap_half[hour]))}"
            )
            ax.text(
                poly[:, 0].mean(),
                poly[:, 1].min() - 0.35,
                label,
                fontsize=5,
                ha="center",
                va="bottom",
                family="monospace",
                color="#0b0b0b",
                bbox={
                    "boxstyle": "round,pad=0.15",
                    "fc": "#fcfcfb",
                    "ec": "none",
                    "alpha": 0.85,
                },
            )
    for p in points:
        x, y = p["x_km"], p["y_km"]
        if p["status"] == "no_sample":
            ax.plot(x, y, "o", ms=2.2, mfc="none", mec="#52514e", mew=0.5)
        elif p["status"] == "uncovered":
            ax.plot(x, y, "o", ms=1.4, color="#52514e", alpha=0.55)
        elif p["status"] == "no_backup":
            ax.plot(x, y, "o", ms=2.6, color="#0b0b0b")
        else:
            if metric == "signal":
                v = p["n_degraded"] / p["n_backups"]
            else:
                hc = p["hours"].get(hour)
                if hc is None or hc["with_data"] == 0:
                    ax.plot(x, y, "s", ms=2.0, color="#d6d5cf")
                    continue
                v = hc["congested"] / hc["with_data"]
            ax.plot(x, y, "o", ms=2.8, color=SEQ(v), mec="#fcfcfb", mew=0.3)
    ax.plot(0, 0, "x", color="#0b0b0b", ms=7, mew=1.6)


def draw_diff(
    ax: Axes,
    case: CaseInput,
    metric: Metric,
    hour: str,
    stats: dict[str, dict[Side, AreaStats]],
) -> str:
    ax.set_xlim(-FRAME_KM / 2, FRAME_KM / 2)
    ax.set_ylim(FRAME_KM / 2, -FRAME_KM / 2)
    ax.set_aspect("equal")
    ax.set_xticks(range(-15, 16, 5))
    ax.set_yticks(range(-15, 16, 5))
    ax.grid(True, color="#ecebe6", linewidth=0.6)
    ax.tick_params(labelsize=6, colors="#52514e")
    norm = TwoSlopeNorm(vmin=-0.4, vcenter=0.0, vmax=0.4)
    compared: list[str] = []
    truth_only: list[str] = []
    run_only: list[str] = []
    num = bias = den = 0.0
    tv_num = 0.0
    sparse = 0
    largest: tuple[str, float] = ("", 0.0)
    for area in case["areas"]:
        poly = np.array(area["polygon_km"])
        t, r = stats[area["id"]]["truth"], stats[area["id"]]["agent"]
        both = t.covered > 0 and r.covered > 0
        if not both:
            (truth_only if t.n_points else run_only if r.n_points else []).append(
                area["id"]
            )
            ax.add_patch(
                Polygon(
                    poly,
                    closed=True,
                    fill=False,
                    hatch="////",
                    edgecolor="#52514e",
                    linewidth=0.7,
                )
            )
            continue
        compared.append(area["id"])

        def value(s: AreaStats) -> float:
            return (
                s.share(s.sig_half) if metric == "signal" else s.share(s.cap_half[hour])
            ) or 0.0

        d = value(r) - value(t)
        ax.add_patch(
            Polygon(
                poly,
                closed=True,
                facecolor=DIV(norm(d)),
                edgecolor="#52514e",
                linewidth=0.7,
            )
        )
        ax.text(
            poly[:, 0].mean(),
            poly[:, 1].mean(),
            f"{area['id']} {signed(d)}",
            fontsize=5.5,
            ha="center",
            va="center",
            family="monospace",
            color="#0b0b0b",
        )
        if t.sampled < SPARSE_POINTS:
            sparse += 1
            continue
        tv = (
            sum(
                abs(a - b)
                for a, b in zip(t.classes[hour], r.classes[hour], strict=True)
            )
            / (2 * t.covered)
            if t.covered
            else 0
        )
        num += t.sampled * abs(d)
        bias += t.sampled * d
        tv_num += t.sampled * tv
        den += t.sampled
        if abs(d) > abs(largest[1]):
            largest = (area["id"], d)
    ax.plot(0, 0, "x", color="#0b0b0b", ms=7, mew=1.6)
    all_t = sum(s["truth"].sampled for s in stats.values())
    cmp_t = sum(stats[a]["truth"].sampled for a in compared)
    name = "signal share" if metric == "signal" else f"congested {hour}"
    return (
        f"areas        {len(compared)} compared, {len(truth_only)} truth only ({', '.join(truth_only) or '-'}), "
        f"{len(run_only)} run only ({', '.join(run_only) or '-'})\n"
        f"area recall  {cmp_t / all_t if all_t else 0:.2f}  ({cmp_t} of {all_t} sampled truth points)\n"
        f"{name:<12} MAE {num / den if den else 0:.2f}, bias {bias / den if den else 0:+.2f}  "
        f"(weighted by {int(den)} truth points; {sparse} sparse left out)\n"
        f"class TV     {tv_num / den if den else 0:.2f} weighted, classes at {hour}\n"
        f"largest gap  {largest[0]} ({signed(largest[1])} points)"
    )


def draw_area_panel(
    ax: Axes, area: AreaRecord, t: AreaStats, r: AreaStats, hours: list[str], hour: str
) -> None:
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    sparse = 0 < t.sampled < SPARSE_POINTS
    tag = (
        " · truth only"
        if r.n_points == 0
        else " · run only"
        if t.n_points == 0
        else " · sparse"
        if sparse
        else ""
    )
    ax.text(
        0,
        0.98,
        f"{area['id']} {area['name']}{tag}",
        fontsize=7.5,
        weight="bold",
        va="top",
    )
    er = area.get("extent_recall")
    recall = f" · extent recall {er:.2f}" if isinstance(er, (int, float)) else ""
    ax.text(
        0,
        0.90,
        f"truth {t.sampled} sampled · agent {r.sampled} sampled{recall}",
        fontsize=5.5,
        family="monospace",
        color="#52514e",
        va="top",
    )
    rows = [
        ("signal ≥ half", t.share(t.sig_half), r.share(r.sig_half)),
        (f"congested {hour}", t.share(t.cap_half[hour]), r.share(r.cap_half[hour])),
        ("no backup", t.share(t.no_backup), r.share(r.no_backup)),
    ]
    y = 0.80
    for label, tv_, rv in rows:
        ax.text(0, y, label, fontsize=5.5, va="center", color="#52514e")
        for v, col, dy in ((tv_, TRUTH_COLOR, 0.02), (rv, AGENT_COLOR, -0.03)):
            if v is None:
                ax.text(
                    0.34,
                    y + dy,
                    "not queried",
                    fontsize=5,
                    family="monospace",
                    color="#52514e",
                    va="center",
                )
            else:
                ax.barh(y + dy, 0.5 * v, left=0.34, height=0.04, color=col)
                ax.text(
                    0.345 + 0.5 * v,
                    y + dy,
                    pct(v),
                    fontsize=5,
                    family="monospace",
                    va="center",
                )
        y -= 0.12
    for label, s, yy in (("class, truth", t, 0.40), ("class, agent", r, 0.33)):
        ax.text(0, yy, label, fontsize=5.5, va="center", color="#52514e")
        if s.covered == 0:
            ax.text(
                0.34,
                yy,
                "not queried",
                fontsize=5,
                family="monospace",
                color="#52514e",
                va="center",
            )
            continue
        left = 0.34
        for c, col in zip(s.classes[hour], CLASS_COLORS, strict=True):
            w = 0.6 * c / s.covered
            ax.barh(yy, w, left=left, height=0.045, color=col)
            left += w
    # hour line
    x0, x1, y0, y1 = 0.34, 0.94, 0.04, 0.24
    ax.text(
        0, 0.24, "congested ≥ half, by hour", fontsize=5.5, va="top", color="#52514e"
    )
    for g in (0.0, 0.5, 1.0):
        ax.plot([x0, x1], [y0 + (y1 - y0) * g] * 2, color="#ecebe6", lw=0.5)
        ax.text(
            x0 - 0.01,
            y0 + (y1 - y0) * g,
            f"{int(g * 100)}",
            fontsize=4.5,
            ha="right",
            va="center",
            family="monospace",
            color="#52514e",
        )
    for s, col in ((t, TRUTH_COLOR), (r, AGENT_COLOR)):
        if s.covered == 0:
            continue
        xs = [x0 + (x1 - x0) * i / (len(hours) - 1) for i in range(len(hours))]
        ys = [y0 + (y1 - y0) * (s.share(s.cap_half[h]) or 0.0) for h in hours]
        ax.plot(xs, ys, color=col, lw=1.1)
        i = hours.index(hour)
        ax.plot(xs[i], ys[i], "o", color=col, ms=3, mec="#fcfcfb")
    for i in (0, len(hours) // 2, len(hours) - 1):
        ax.text(
            x0 + (x1 - x0) * i / (len(hours) - 1),
            y0 - 0.02,
            hours[i],
            fontsize=4.5,
            ha="center",
            va="top",
            family="monospace",
            color="#52514e",
        )


def worst_hour(case: CaseInput, stats: dict[str, dict[Side, AreaStats]]) -> str:
    best, best_v = case["hours"][0], -1.0
    for h in case["hours"]:
        v = sum(s["truth"].cap_half[h] for s in stats.values())
        if v > best_v:
            best, best_v = h, v
    return best


def paragraph(area: AreaRecord, t: AreaStats, r: AreaStats, hour: str) -> str:
    if t.covered == 0:
        return (
            f"**{area['name']}** ({area['kind']}): no ground-truth points. The agent sampled {r.sampled} "
            f"points here; not compared.\n"
        )
    cls = ", ".join(
        f"{pct(c / t.covered)} {n}"
        for c, n in zip(t.classes[hour], CLASSES, strict=True)
        if c
    )
    text = (
        f"**{area['name']}** ({area['kind']}, {t.sampled} truth points sampled). {t.covered} are covered by an "
        f"outage sector. Of those: {t.no_backup} points ({pct(t.share(t.no_backup))}) have no backup cell at all. "
        f"Signal: at {t.sig_half} points ({pct(t.share(t.sig_half))}) at least half of the backup cells are "
        f"degraded; at {t.sig_all} ({pct(t.share(t.sig_all))}) every backup is. Capacity at {hour}: at "
        f"{t.cap_half[hour]} points ({pct(t.share(t.cap_half[hour]))}) at least half of the backups with KPI "
        f"data are above {LOAD_LIMIT_PERCENT} % PRB; at {t.cap_all[hour]} ({pct(t.share(t.cap_all[hour]))}) "
        f"every one is. Class mix at that hour: {cls}."
    )
    if r.covered == 0:
        return text + " The agent did not query this area.\n"
    tv = (
        sum(
            abs(a / t.covered - b / r.covered)
            for a, b in zip(t.classes[hour], r.classes[hour], strict=True)
        )
        / 2
    )
    ds = (r.share(r.sig_half) or 0) - (t.share(t.sig_half) or 0)
    dc = (r.share(r.cap_half[hour]) or 0) - (t.share(t.cap_half[hour]) or 0)
    return (
        text
        + f" The agent sampled {r.sampled} points of this area; on those it found {pct(r.share(r.no_backup))} "
        f"with no backup, {pct(r.share(r.sig_half))} signal-degraded, {pct(r.share(r.cap_half[hour]))} congested "
        f"at {hour}. Differences: signal {signed(ds)} points, capacity {signed(dc)} points, class TV {tv:.2f}.\n"
    )


def draw_all(case: CaseInput, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    hours = case["hours"]
    stats: dict[str, dict[Side, AreaStats]] = {
        a["id"]: {
            "truth": area_stats(case["points"]["truth"], a["id"], hours),
            "agent": area_stats(case["points"]["agent"], a["id"], hours),
        }
        for a in case["areas"]
    }
    hour = worst_hour(case, stats)
    order = sorted(case["areas"], key=lambda a: -stats[a["id"]]["truth"].sampled)
    ncol = 3
    nrow_areas = math.ceil(len(order) / ncol)

    fig = plt.figure(figsize=(13, 11.5 + 3.0 * nrow_areas), facecolor="#fcfcfb")
    grid = fig.add_gridspec(
        4 + nrow_areas,
        3,
        height_ratios=[4.4, 1.1, 4.4, 1.1] + [2.6] * nrow_areas,
        hspace=0.45,
        wspace=0.15,
    )
    fig.suptitle(
        f"{case['site']}, outage from {case['outage_start']}: area impact, ground truth against the agent run",
        fontsize=11,
        x=0.02,
        y=0.995,
        ha="left",
    )
    for metric_row, metric in enumerate(METRICS):
        row = 2 * metric_row
        title = (
            "Signal: share of points where at least half of the reachable backups are degraded"
            if metric == "signal"
            else f"Capacity at {hour} (worst truth hour): share of points where at least half of the backups are above "
            f"{LOAD_LIMIT_PERCENT} % PRB"
        )
        for col, side in enumerate(SIDES):
            ax = fig.add_subplot(grid[row, col])
            draw_map(ax, case, side, metric, hour, stats)
            ax.set_title(
                ("Ground truth" if side == "truth" else "Agent run"),
                fontsize=8,
                loc="left",
            )
            if col == 0:
                ax.text(
                    0,
                    1.10,
                    title,
                    transform=ax.transAxes,
                    fontsize=8.5,
                    weight="bold",
                    va="bottom",
                )
        ax = fig.add_subplot(grid[row, 2])
        box = draw_diff(ax, case, metric, hour, stats)
        ax.set_title("Agent minus truth, per area (points)", fontsize=8, loc="left")
        tx = fig.add_subplot(grid[row + 1, :])
        tx.axis("off")
        tx.text(
            0,
            1,
            box,
            transform=tx.transAxes,
            fontsize=6.4,
            family="monospace",
            va="top",
            bbox={"boxstyle": "square,pad=0.5", "fc": "#fcfcfb", "ec": "#e2e1dc"},
        )
    for i, area in enumerate(order):
        ax = fig.add_subplot(grid[4 + i // ncol, i % ncol])
        draw_area_panel(
            ax,
            area,
            stats[area["id"]]["truth"],
            stats[area["id"]]["agent"],
            hours,
            hour,
        )
    handles = [
        plt.Line2D([], [], marker="o", ls="", color=SEQ(0.1), label="share 0"),
        plt.Line2D([], [], marker="o", ls="", color=SEQ(0.9), label="share 1"),
        plt.Line2D([], [], marker="o", ls="", color="#0b0b0b", label="no backup"),
        plt.Line2D(
            [],
            [],
            marker="o",
            ls="",
            color="#52514e",
            ms=3,
            label="sampled, no outage coverage",
        ),
        plt.Line2D(
            [], [], marker="o", ls="", mfc="none", mec="#52514e", label="no sample"
        ),
        plt.Line2D([], [], color=TRUTH_COLOR, lw=4, label="truth"),
        plt.Line2D([], [], color=AGENT_COLOR, lw=4, label="agent"),
    ]
    handles += [
        plt.Line2D([], [], color=c, lw=4, label=n)
        for n, c in zip(CLASSES, CLASS_COLORS, strict=True)
    ]
    fig.legend(
        handles=handles,
        loc="lower center",
        ncol=7,
        fontsize=6,
        frameon=False,
        bbox_to_anchor=(0.5, 0.005),
    )
    fig.savefig(out / "area_impact.png", dpi=160, bbox_inches="tight")
    fig.savefig(out / "area_impact.svg", bbox_inches="tight")
    plt.close(fig)

    # one three-panel row per hour, and a strip of all hours
    for h in hours:
        fig, axes = plt.subplots(1, 3, figsize=(13, 4.6), facecolor="#fcfcfb")
        draw_map(axes[0], case, "truth", "capacity", h, stats)
        draw_map(axes[1], case, "agent", "capacity", h, stats)
        box = draw_diff(axes[2], case, "capacity", h, stats)
        axes[2].text(
            0,
            -0.1,
            box,
            transform=axes[2].transAxes,
            fontsize=5.6,
            family="monospace",
            va="top",
            bbox={"boxstyle": "square,pad=0.4", "fc": "#fcfcfb", "ec": "#e2e1dc"},
        )
        fig.suptitle(
            f"Capacity at {h}: share of points where at least half of the backups are above "
            f"{LOAD_LIMIT_PERCENT} % PRB",
            fontsize=9,
            x=0.02,
            ha="left",
        )
        fig.savefig(
            out / f"area_impact_prb_{h.replace(':', '')}.png",
            dpi=140,
            bbox_inches="tight",
        )
        plt.close(fig)
    fig, axes = plt.subplots(
        2, len(hours), figsize=(1.6 * len(hours), 3.6), facecolor="#fcfcfb"
    )
    for i, h in enumerate(hours):
        for j, side in enumerate(SIDES):
            ax = axes[j, i]
            draw_map(ax, case, side, "capacity", h, stats)
            ax.set_xticks([])
            ax.set_yticks([])
            for txt in list(ax.texts):
                txt.remove()
            if j == 0:
                ax.set_title(h, fontsize=7)
            if i == 0:
                ax.set_ylabel(side, fontsize=7)
    fig.savefig(out / "area_impact_prb_hours.png", dpi=140, bbox_inches="tight")
    plt.close(fig)

    with (out / "area_impact.md").open("w", encoding="utf-8") as f:
        f.write(f"# {case['site']}: area impact at {hour} (worst truth hour)\n\n")
        for area in order:
            f.write(
                paragraph(
                    area, stats[area["id"]]["truth"], stats[area["id"]]["agent"], hour
                )
                + "\n"
            )


# ---------------------------------------------------------------- synthetic sample
def synthetic_case() -> CaseInput:
    rng = random.Random(7)
    hours = [f"{h % 24:02d}:00" for h in range(11, 26)]
    profile = [
        0.35 + 0.65 * math.exp(-(((i - 7) / 3.2) ** 2)) for i in range(len(hours))
    ]

    def disc(x: float, y: float, r: float) -> list[list[float]]:
        return [
            [round(x + r * math.cos(t), 3), round(y + r * math.sin(t), 3)]
            for t in np.linspace(0, 2 * math.pi, 40)
        ]

    def strip(
        x: float, y: float, length: float, w: float, deg: float
    ) -> list[list[float]]:
        t = math.radians(deg)
        c = [
            (-length / 2, -w / 2),
            (length / 2, -w / 2),
            (length / 2, w / 2),
            (-length / 2, w / 2),
        ]
        return [
            [
                round(x + u * math.cos(t) - v * math.sin(t), 3),
                round(y + u * math.sin(t) + v * math.cos(t), 3),
            ]
            for u, v in c
        ]

    spec = [
        (
            "S01",
            "Mansfield town",
            "settlement",
            disc(-3.2, -4.1, 2.6),
            (0.34, 0.52, 0.11),
            (0.31, 0.28, 0.09),
            "east",
        ),
        (
            "S02",
            "Storrs village",
            "settlement",
            disc(5.4, 2.6, 1.6),
            (0.58, 0.37, 0.29),
            (0.55, 0.41, 0.26),
            "all",
        ),
        (
            "S03",
            "Coventry hamlet",
            "settlement",
            disc(2.8, -8.6, 1.0),
            (0.75, 0.17, 0.50),
            (0.21, 0.14, 0.07),
            "all",
        ),
        (
            "S04",
            "Ashford hamlet",
            "settlement",
            disc(-9.4, 5.8, 0.8),
            (1.0, 0.0, 0.67),
            (0.44, 0.0, 0.33),
            "all",
        ),
        (
            "C01",
            "Route 195 north-east",
            "corridor",
            strip(0.6, 0.4, 11, 1.2, -38),
            (0.22, 0.61, 0.05),
            (0.24, 0.58, 0.04),
            "all",
        ),
        (
            "C02",
            "Route 44 west",
            "corridor",
            strip(-5.2, 0.9, 9, 1.2, 8),
            (0.41, 0.30, 0.14),
            (0.69, 0.09, 0.27),
            "near",
        ),
        (
            "C03",
            "Route 32 south",
            "corridor",
            strip(-1.4, 7.6, 8, 1.2, 80),
            (0.49, 0.43, 0.20),
            None,
            "none",
        ),
        (
            "A01",
            "activity area east",
            "activity",
            strip(10.8, -3.2, 3, 1.6, 0),
            None,
            (0.18, 0.06, 0.0),
            "all",
        ),
    ]
    areas: list[AreaRecord] = [
        {"id": s[0], "name": s[1], "kind": s[2], "polygon_km": s[3]} for s in spec
    ]

    def inside(poly: list[list[float]], x: float, y: float) -> bool:
        n, hit = len(poly), False
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                hit = not hit
        return hit

    def make(side: Side, spacing: float) -> list[PointRecord]:
        out: list[PointRecord] = []
        for s in spec:
            intent = s[4] if side == "truth" else s[5]
            if intent is None:
                continue
            poly = s[3]
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            off = 0.0 if side == "truth" else spacing / 2
            x = min(xs) + off
            while x <= max(xs):
                y = min(ys) + off
                while y <= max(ys):
                    if (
                        inside(poly, x, y)
                        and not (side == "agent" and s[6] == "east" and x < xs[0] - 2.9)
                        and not (side == "agent" and s[6] == "near" and x < -6.7)
                    ):
                        rec = _point(rng, x, y, s[0], intent, hours, profile)
                        out.append(rec)
                    y += spacing
                x += spacing
        return out

    return {
        "site": "ARL02850 (synthetic)",
        "outage_start": "2026-03-24 11:00",
        "hours": hours,
        "areas": areas,
        "points": {"truth": make("truth", 0.5), "agent": make("agent", 0.3)},
    }


def _point(
    rng: random.Random,
    x: float,
    y: float,
    area_id: str,
    intent: tuple[float, float, float],
    hours: list[str],
    profile: list[float],
) -> PointRecord:
    base: PointRecord = {
        "x_km": round(x, 3),
        "y_km": round(y, 3),
        "area_ids": [area_id],
        "status": "covered",
        "n_backups": 0,
        "n_degraded": 0,
        "hours": {},
    }
    r = rng.random()
    if r < 0.12:
        return {**base, "status": "no_sample"}
    if r < 0.22:
        return {**base, "status": "uncovered"}
    if rng.random() < intent[2]:
        return {**base, "status": "no_backup"}
    n = 1 + rng.randrange(4)
    k = sum(rng.random() < intent[0] for _ in range(n))
    d = max(1, n - (1 if rng.random() < 0.15 else 0))
    hrs: dict[str, HourCounts] = {}
    for h, pr in zip(hours, profile, strict=True):
        c = sum(rng.random() < min(1.0, intent[1] * pr / 0.6) for _ in range(d))
        hrs[h] = {"with_data": d, "congested": c}
    return {**base, "n_backups": n, "n_degraded": k, "hours": hrs}


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "input", help="input JSON, or the output directory with --synthetic"
    )
    ap.add_argument("out", nargs="?", help="output directory")
    ap.add_argument(
        "--synthetic",
        action="store_true",
        help="write a synthetic input to <input>/area_impact_input.json and draw it",
    )
    args = ap.parse_args()
    if args.synthetic:
        out = Path(args.input)
        out.mkdir(parents=True, exist_ok=True)
        case = synthetic_case()
        (out / "area_impact_input.json").write_text(
            json.dumps(case, indent=1), encoding="utf-8"
        )
    else:
        if not args.out:
            ap.error("out directory is required")
        out = Path(args.out)
        case = json.loads(Path(args.input).read_text(encoding="utf-8"))
    draw_all(case, out)
    print(
        f"wrote {out / 'area_impact.png'}, per-hour files, area_impact_prb_hours.png, area_impact.md"
    )


if __name__ == "__main__":
    main()
