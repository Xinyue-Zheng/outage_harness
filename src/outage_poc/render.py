"""Offline human artifacts rendered only from observed state and recorded steps."""

import json
from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path

from .models import AreaId, Coordinate, Geometry, State, Step, Trace
from .state import STUDY_AREA


@dataclass(frozen=True)
class View:
    left: float
    top: float
    width: float
    height: float
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @property
    def scale(self) -> float:
        return min(
            self.width / (self.xmax - self.xmin), self.height / (self.ymax - self.ymin)
        )

    def project(self, point: Coordinate) -> Coordinate:
        dx = (self.width - (self.xmax - self.xmin) * self.scale) / 2
        dy = (self.height - (self.ymax - self.ymin) * self.scale) / 2
        return (
            self.left + dx + (point[0] - self.xmin) * self.scale,
            self.top + dy + (self.ymax - point[1]) * self.scale,
        )


def _points(geometry: Geometry, view: View) -> str:
    return " ".join(
        f"{x:.2f},{y:.2f}" for x, y in map(view.project, geometry.coordinates)
    )


def _text(x: float, y: float, content: str, size: int = 13) -> str:
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" '
        f'fill="#172436">{escape(content)}</text>'
    )


def _view_for(
    geometry: Geometry,
    left: float,
    top: float,
    width: float,
    height: float,
    margin: float,
) -> View:
    if not geometry.coordinates:
        raise ValueError("Map geometry must contain coordinates.")
    xs = [point[0] for point in geometry.coordinates]
    ys = [point[1] for point in geometry.coordinates]
    if max(xs) <= min(xs) or max(ys) <= min(ys):
        raise ValueError("A map viewport requires a nondegenerate area geometry.")
    return View(
        left,
        top,
        width,
        height,
        min(xs) - margin,
        min(ys) - margin,
        max(xs) + margin,
        max(ys) + margin,
    )


def render_map(state: State) -> str:
    """Return a self-contained SVG; unknown coverage never enters this function."""
    regions = {region.area_id: region for region in state.regions}
    areas = {area.id: area for area in state.areas}
    study = regions[STUDY_AREA]
    missing_pattern_id = f"{escape(state.id, quote=True)}_missing"
    unknown = set(study.unqueried_ids)
    missing = set(study.missing_ids)
    empty = set(study.no_coverage_ids)
    other = set(study.other_cells_only_ids)
    target = set(study.target_ids)
    boundary = set(regions[AreaId("S2")].boundary_ids)
    backup_colors: dict[str, str] = {}
    assignment_colors: dict[str, tuple[str, str]] = {}
    if state.impact is not None:
        palette = ("#168c66", "#7b4bc0", "#ab671d", "#167e9e")
        for index, backup in enumerate(state.impact.backup_loads):
            backup_colors[backup.cell_id] = palette[index % len(palette)]
        for assignment in state.impact.assignments:
            if assignment.classification == "no_eligible_backup":
                assignment_colors[assignment.grid_id] = (
                    "#edb100",
                    "No eligible backup",
                )
            else:
                backup = assignment.backup_cell_id
                if backup is None:
                    raise ValueError("A transferred assignment requires a backup cell.")
                assignment_colors[assignment.grid_id] = (
                    backup_colors[backup],
                    f"Transfer to {backup}",
                )
    views = (
        (
            "overview",
            _view_for(
                areas[STUDY_AREA].geometry,
                25,
                110,
                900,
                740,
                state.grid_spacing_m,
            ),
        ),
        (
            "detail",
            _view_for(
                areas[AreaId("S2")].geometry, 970, 435, 355, 400, state.grid_spacing_m
            ),
        ),
    )
    parts = [
        (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1360 940" role="img" '
            'aria-label="Synthetic outage investigation map with study overview and settlement detail">'
        ),
        (
            f'<defs><pattern id="{missing_pattern_id}" width="6" height="6" patternUnits="userSpaceOnUse">'
            '<rect width="6" height="6" fill="#ffeedb"/><path d="M0 0L6 6M6 0L0 6" '
            'stroke="#b9671c" stroke-width="1"/></pattern></defs>'
        ),
        '<rect width="1360" height="940" fill="#f5f7fa"/>',
        '<g font-family="system-ui, sans-serif">',
        _text(25, 35, f"Synthetic outage investigation: {state.id}", 23),
        _text(
            25,
            63,
            "Human visualization of observed evidence • local planar coordinates in metres • not real OSM",
            15,
        ),
        _text(
            25,
            91,
            "Study overview: gray grid = unqueried coverage; geography is known independently.",
            14,
        ),
        _text(970, 419, "S2 detail / query boundary", 14),
    ]
    land_colors = {
        "farmland": "#e7edbe",
        "vineyard": "#e5d5ec",
        "forest": "#c4e0cc",
        "settlement": "#dfe8f3",
        "study_area": "#ffffff",
        "cell": "#ffffff",
    }
    for name, view in views:
        clip_id = f"{escape(state.id, quote=True)}_{name}"
        parts.append(
            f'<defs><clipPath id="{clip_id}"><rect x="{view.left}" y="{view.top}" '
            f'width="{view.width}" height="{view.height}"/></clipPath></defs>'
        )
        parts.append(f'<g clip-path="url(#{clip_id})">')
        parts.append(
            f'<rect x="{view.left}" y="{view.top}" width="{view.width}" height="{view.height}" fill="white"/>'
        )
        for item in state.geography:
            if item.geometry.kind == "polygon":
                parts.append(
                    f'<polygon points="{_points(item.geometry, view)}" '
                    f'fill="{land_colors[item.kind]}" stroke="#728093" stroke-width="0.8"/>'
                )
        side = state.grid_spacing_m * view.scale * 0.8
        for point in state.grid:
            label: str
            color: str
            if point.id in unknown:
                color, label = "#e2e5eb", "Unknown: not queried"
            elif point.id in missing:
                color, label = f"url(#{missing_pattern_id})", "Queried: missing data"
            elif point.id in empty:
                color, label = "#27313f", "Valid: no cell coverage"
            elif point.id in other:
                color, label = (
                    "#4d86c9",
                    f"Valid: other cells, no {state.task.down_cell_id}",
                )
            elif point.id in target:
                if point.id in assignment_colors:
                    color, label = assignment_colors[point.id]
                else:
                    color, label = (
                        "#d75066",
                        f"Valid: {state.task.down_cell_id} present before outage",
                    )
            else:
                raise ValueError(
                    f"Grid {point.id} has no recognized state classification."
                )
            x, y = view.project((point.x_m, point.y_m))
            parts.append(
                f'<rect x="{x - side / 2:.2f}" y="{y - side / 2:.2f}" '
                f'width="{side:.2f}" height="{side:.2f}" fill="{color}" '
                f'stroke="{"#111827" if point.id in boundary else "none"}" stroke-width="1.2">'
                f"<title>{escape(point.id)}: {escape(label)}</title></rect>"
            )
        for item in state.geography:
            geometry = item.geometry
            if geometry.kind == "polyline":
                parts.append(
                    f'<polyline points="{_points(geometry, view)}" fill="none" stroke="white" stroke-width="4"/>'
                )
                parts.append(
                    f'<polyline points="{_points(geometry, view)}" fill="none" stroke="#25364f" stroke-width="1.8" stroke-dasharray="7 4"/>'
                )
            elif item.kind == "settlement":
                parts.append(
                    f'<polygon points="{_points(geometry, view)}" fill="none" stroke="#1e3554" stroke-width="1.7"/>'
                )
            if item.kind != "study_area":
                if geometry.kind == "polyline":
                    anchor = (
                        sum(point[0] for point in geometry.coordinates)
                        / len(geometry.coordinates),
                        sum(point[1] for point in geometry.coordinates)
                        / len(geometry.coordinates),
                    )
                else:
                    anchor = (
                        min(point[0] for point in geometry.coordinates),
                        max(point[1] for point in geometry.coordinates),
                    )
                x, y = view.project(anchor)
                parts.append(
                    f'<rect x="{x + 2:.2f}" y="{y - 18:.2f}" width="{len(item.id) * 8 + 4}" '
                    'height="17" rx="2" fill="white" fill-opacity="0.9"/>'
                )
                parts.append(_text(x + 4, y - 5, item.id, 12))
        site_x, site_y = view.project((state.task.site_x_m, state.task.site_y_m))
        parts.append(
            f'<circle cx="{site_x:.2f}" cy="{site_y:.2f}" r="6" fill="#d75066" '
            'stroke="#172436" stroke-width="1.5"/>'
        )
        parts.append(_text(site_x + 8, site_y + 4, state.task.down_cell_id, 12))
        parts.append("</g>")
        parts.append(
            f'<rect x="{view.left}" y="{view.top}" width="{view.width}" height="{view.height}" fill="none" stroke="#bac5d3"/>'
        )
    legend = [
        ("#e2e5eb", "Unknown / not queried"),
        (f"url(#{missing_pattern_id})", "Queried / missing data"),
        ("#27313f", "Valid / no cell coverage"),
        ("#4d86c9", f"Valid / other cells, no {state.task.down_cell_id}"),
        ("#d75066", f"Valid / pre-outage {state.task.down_cell_id}"),
    ]
    if state.impact is not None:
        legend.extend(
            (color, f"Target traffic transferred to {cell}")
            for cell, color in backup_colors.items()
        )
        legend.append(("#edb100", "Target / no eligible backup"))
    parts.append(_text(970, 112, "Grid evidence / impact legend", 16))
    for index, (color, label) in enumerate(legend):
        y = 137 + index * 24
        parts.append(
            f'<rect x="970" y="{y - 12}" width="16" height="16" fill="{color}" stroke="#8190a4"/>'
        )
        parts.append(_text(996, y, label, 12))
    parts.extend(
        [
            _text(970, 373, "Black outline: S2 query boundary", 12),
            _text(970, 393, "Dashed line: highway centerline", 12),
            _text(
                25,
                879,
                f"Scope Study_area: {len(study.queried_ids)} queried / {len(study.total_ids)} locations; {len(study.missing_ids)} missing.",
                14,
            ),
            _text(
                25,
                903,
                "Target absence, no coverage, missing data, and unqueried coverage are distinct. The end of a run does not prove sufficient investigation.",
                13,
            ),
            "</g></svg>",
        ]
    )
    return "\n".join(parts)


def _details(title: str, content: str, path: str) -> str:
    return (
        f'<details><summary>{escape(title)} <a href="{escape(path, quote=True)}">'
        f"open artifact</a></summary><pre>{escape(content)}</pre></details>"
    )


def _read(output_dir: Path, path: str) -> str:
    return (output_dir / path).read_text(encoding="utf-8")


def render_page(output_dir: Path, trace: Trace, steps: list[Step]) -> str:
    """Embed every recorded artifact of a run in one offline HTML page."""
    navigation = " ".join(
        f'<a href="#{escape(step.id, quote=True)}">{escape(step.id)}</a>'
        for step in steps
    )
    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        "<title>Synthetic outage investigation</title>",
        (
            "<style>body{font:15px/1.55 system-ui,sans-serif;color:#18263b;background:#f3f6fa;margin:0}"
            "main{max-width:1320px;margin:auto;padding:24px}header,article{background:white;padding:24px;border:1px solid #dbe3ed;border-radius:12px;margin:18px 0}"
            "h1,h2,h3{line-height:1.2}nav{display:flex;gap:12px;flex-wrap:wrap}a{color:#155ea5}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef2f7;padding:16px;font:12px/1.5 ui-monospace,monospace;max-height:560px;overflow:auto}"
            "details{margin:12px 0}summary{cursor:pointer;font-weight:600}summary a{font-size:12px;margin-left:12px;font-weight:400}"
            "svg{width:100%;height:auto}.tag{background:#fff0cd;padding:4px 8px;border-radius:6px}.context{font-size:13px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}"
            "@media(max-width:800px){.pair{display:block}main{padding:10px}article{padding:14px}}</style></head><body><main>"
        ),
        "<header><h1>Synthetic outage investigation</h1>",
        (
            '<p><span class="tag">synthetic geography, coverage, KPI and traffic</span> '
            f'<span class="tag">run {escape(trace.run_id)}</span> '
            f'<span class="tag">end reason: {escape(trace.end_reason)}</span></p>'
        ),
        (
            "<p>Each step is one round: the text sent to the model, its reply, "
            "validation, what ran, and the State after it. Maps are for people; "
            "the model receives text only.</p>"
        ),
        f"<nav>{navigation}</nav>",
        _details(
            "Context prefix (skill, task, geography, actions)",
            _read(output_dir, trace.prefix),
            trace.prefix,
        ),
        _details(
            "Initial state",
            _read(output_dir, trace.initial_state),
            trace.initial_state,
        ),
        "</header>",
    ]
    for step in steps:
        action = step.decision.action if step.decision is not None else "unparsed reply"
        decision = (
            json.dumps(asdict(step.decision), indent=2)
            if step.decision is not None
            else step.raw_output
        )
        parts.extend(
            [
                f'<article id="{escape(step.id, quote=True)}"><h2>{escape(step.id)} · {escape(action)}</h2>',
                (
                    f"<p>Execution source: <strong>{escape(step.execution_source)}</strong>. "
                    f"Validation: <strong>{escape(step.validation)}</strong>. "
                    f"Review: <strong>{escape(step.review)}</strong>. "
                    f"Outcome: {escape(step.outcome)}</p>"
                ),
                (
                    f"<p>{escape(step.validation_message)}</p>"
                    if step.validation_message
                    else ""
                ),
                (
                    f"<p>Verifier: {escape(step.review_reason)}</p>"
                    if step.review_reason
                    else ""
                ),
                "<h3>Decision</h3>",
                f"<pre>{escape(decision)}</pre>",
                _details(
                    "Text sent to the model",
                    _read(output_dir, step.context),
                    step.context,
                ),
                (
                    _details(
                        "Observation",
                        json.dumps(asdict(step.observation), indent=2),
                        f"observations/{step.observation.id}.json",
                    )
                    if step.observation is not None
                    else ""
                ),
                (
                    "<h3>Map after the step</h3>"
                    + _read(output_dir, step.visualization)
                    if step.visualization is not None
                    else ""
                ),
                _details(
                    "Context after (variable part)",
                    _read(output_dir, step.context_after),
                    step.context_after,
                ),
                "</article>",
            ]
        )
    parts.append(
        "<footer><p>The end of a run does not establish investigation sufficiency, "
        "model decision quality or cross-case generalization.</p></footer></main></body></html>"
    )
    return "\n".join(parts)
