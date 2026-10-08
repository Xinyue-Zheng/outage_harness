"""Build State 0 for one hypothetical rural site from real OpenStreetMap data.

Input:  osm_raw.json, the Overpass answer for a 30 km x 30 km square around the site
        (query in overpass_query.txt).
Output: state_00.json            State 0 as the harness would hold it (grid ids in a
                                 separate file because there are 90,000 of them)
        areas_grid_ids.json      area id -> grid ids
        context_state_00.txt     the text the model reads before its first decision
        map_state_00.svg         the window for people: land-use classes, settlements,
                                 corridors, blocks, the site

Everything here is fixed program logic. No coverage is read, no model is called.
Standard library only; run with python3.
"""

import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

HERE = Path(__file__).parent

# ---- the declared rules (these are the choices to record, not facts) ----------------
SITE_LAT, SITE_LON = 39.95, -87.95
DOWN_CELL = "C-IL-0042"
OUTAGE_TIME = "2026-03-02T06:40:00Z"
ENVIRONMENT = "rural"  # would come from cell.lookup metadata
INITIAL_WINDOW_M = {"rural": 30_000.0}  # rule table; other classes deliberately unset
GRID_SPACING_M = 100.0  # equals the coverage heatmap resolution used for the first scan
BLOCK_SIZE_M = 5_000.0  # land-use blocks that tile the window
SETTLEMENT_RADIUS_M = {"city": 3_000.0, "town": 2_000.0, "village": 1_000.0, "hamlet": 500.0}
CORRIDOR_FULL_WIDTH_M = {"motorway": 400.0, "trunk": 300.0, "primary": 300.0, "secondary": 200.0}
MIN_CORRIDOR_LOCATIONS = 50  # shorter mapped routes stay inside their blocks
LABEL_PRECEDENCE = (  # one label per grid cell when polygons overlap
    "settlement",
    "industrial_commercial",
    "water",
    "forest",
    "farmland",
    "grassland",
    "unmapped",
)
LANDUSE_LABEL = {
    ("landuse", "residential"): "settlement",
    ("landuse", "industrial"): "industrial_commercial",
    ("landuse", "commercial"): "industrial_commercial",
    ("landuse", "retail"): "industrial_commercial",
    ("landuse", "quarry"): "industrial_commercial",
    ("landuse", "farmland"): "farmland",
    ("landuse", "farmyard"): "farmland",
    ("landuse", "orchard"): "farmland",
    ("landuse", "vineyard"): "farmland",
    ("landuse", "forest"): "forest",
    ("natural", "wood"): "forest",
    ("landuse", "meadow"): "grassland",
    ("landuse", "grass"): "grassland",
    ("landuse", "cemetery"): "grassland",
    ("natural", "grassland"): "grassland",
    ("natural", "scrub"): "grassland",
    ("natural", "water"): "water",
    ("landuse", "reservoir"): "water",
}

Point = tuple[float, float]
Ring = list[Point]


@dataclass(frozen=True)
class Grid:
    origin_lat: float
    origin_lon: float
    spacing_m: float
    columns: int
    rows: int


@dataclass(frozen=True)
class GeoObject:
    id: str
    kind: str  # settlement_place | landuse | water | road
    label: str
    name: str | None
    tags: dict[str, str]
    geometry_kind: str  # point | polygon | polyline
    vertex_count: int


@dataclass(frozen=True)
class Area:
    id: str
    kind: str  # settlement | road_corridor | block
    description: str
    grid_count: int
    label_counts: dict[str, int]


@dataclass(frozen=True)
class Relation:
    subject_id: str
    predicate: str
    object_id: str
    evidence: str


@dataclass(frozen=True)
class RegionSummary:
    area_id: str
    total: int
    queried: int
    unqueried: int


# ---- projection: equirectangular local metres, origin at the window's south-west corner
def projector(lat0: float, lon0: float, half: float):
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat0))
    origin_lat = lat0 - half / m_per_deg_lat
    origin_lon = lon0 - half / m_per_deg_lon

    def to_m(lat: float, lon: float) -> Point:
        return ((lon - origin_lon) * m_per_deg_lon, (lat - origin_lat) * m_per_deg_lat)

    return origin_lat, origin_lon, to_m


# ---- ring assembly for multipolygon relations --------------------------------------
def assemble_rings(ways: list[list[Point]]) -> list[Ring]:
    """Join way fragments end to end into closed rings. Open leftovers are dropped."""
    pending = [list(w) for w in ways if len(w) >= 2]
    rings: list[Ring] = []
    while pending:
        ring = pending.pop()
        changed = True
        while changed and ring[0] != ring[-1]:
            changed = False
            for i, other in enumerate(pending):
                if other[0] == ring[-1]:
                    ring += other[1:]
                elif other[-1] == ring[-1]:
                    ring += list(reversed(other))[1:]
                elif other[-1] == ring[0]:
                    ring = other[:-1] + ring
                elif other[0] == ring[0]:
                    ring = list(reversed(other))[:-1] + ring
                else:
                    continue
                pending.pop(i)
                changed = True
                break
        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append(ring)
    return rings


# ---- scanline fill: which grid cells does a ring cover ---------------------------------
def fill(ring: Ring, spacing: float, columns: int, rows: int) -> set[int]:
    cells: set[int] = set()
    ys = [p[1] for p in ring]
    r0 = max(0, int(min(ys) // spacing))
    r1 = min(rows - 1, int(max(ys) // spacing))
    for r in range(r0, r1 + 1):
        y = (r + 0.5) * spacing
        xs: list[float] = []
        for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
            if (y1 > y) != (y2 > y):
                xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
        xs.sort()
        for xa, xb in zip(xs[0::2], xs[1::2]):
            c0 = max(0, int(math.ceil((xa - spacing / 2) / spacing)))
            c1 = min(columns - 1, int(math.floor((xb - spacing / 2) / spacing)))
            for c in range(c0, c1 + 1):
                cells.add(r * columns + c)
    return cells


def disc(center: Point, radius: float, spacing: float, columns: int, rows: int) -> set[int]:
    cx, cy = center
    cells: set[int] = set()
    for r in range(max(0, int((cy - radius) // spacing)), min(rows, int((cy + radius) // spacing) + 2)):
        y = (r + 0.5) * spacing
        for c in range(max(0, int((cx - radius) // spacing)), min(columns, int((cx + radius) // spacing) + 2)):
            x = (c + 0.5) * spacing
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius**2:
                cells.add(r * columns + c)
    return cells


def corridor(line: list[Point], half_width: float, spacing: float, columns: int, rows: int) -> set[int]:
    cells: set[int] = set()
    for (x1, y1), (x2, y2) in zip(line, line[1:]):
        xmin, xmax = min(x1, x2) - half_width, max(x1, x2) + half_width
        ymin, ymax = min(y1, y2) - half_width, max(y1, y2) + half_width
        dx, dy = x2 - x1, y2 - y1
        length2 = dx * dx + dy * dy
        for r in range(max(0, int(ymin // spacing)), min(rows, int(ymax // spacing) + 2)):
            y = (r + 0.5) * spacing
            for c in range(max(0, int(xmin // spacing)), min(columns, int(xmax // spacing) + 2)):
                x = (c + 0.5) * spacing
                t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / length2))
                px, py = x1 + t * dx, y1 + t * dy
                if (x - px) ** 2 + (y - py) ** 2 <= half_width**2:
                    cells.add(r * columns + c)
    return cells


def main() -> None:
    half = INITIAL_WINDOW_M[ENVIRONMENT] / 2
    origin_lat, origin_lon, to_m = projector(SITE_LAT, SITE_LON, half)
    columns = rows = int(round(2 * half / GRID_SPACING_M))
    grid = Grid(origin_lat, origin_lon, GRID_SPACING_M, columns, rows)
    n_cells = columns * rows
    site_xy = to_m(SITE_LAT, SITE_LON)

    elements = json.loads((HERE / "osm_raw.json").read_text(encoding="utf-8"))["elements"]
    geography: list[GeoObject] = []
    cell_label = ["unmapped"] * n_cells
    rank = {label: i for i, label in enumerate(LABEL_PRECEDENCE)}
    places: list[tuple[str, str, str, Point]] = []  # id, name, place type, xy
    roads: dict[str, list[tuple[str, list[Point]]]] = defaultdict(list)  # route -> segments

    def paint(cells: set[int], label: str) -> None:
        for i in cells:
            if rank[label] < rank[cell_label[i]]:
                cell_label[i] = label

    for el in elements:
        tags = el.get("tags", {})
        if "place" in tags:
            if el["type"] == "node":
                xy = to_m(el["lat"], el["lon"])
            else:
                pts = [to_m(p["lat"], p["lon"]) for p in el.get("geometry", [])]
                xy = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
            pid = f"P{len(places) + 1:02d}"
            places.append((pid, tags.get("name", pid), tags["place"], xy))
            geography.append(GeoObject(pid, "settlement_place", "settlement", tags.get("name"), {"place": tags["place"]}, "point", 1))
            continue
        if "highway" in tags:
            route = tags.get("ref") or tags.get("name") or f"{tags['highway']} road"
            roads[route].append((tags["highway"], [to_m(p["lat"], p["lon"]) for p in el["geometry"]]))
            continue
        key = ("landuse", tags["landuse"]) if "landuse" in tags else ("natural", tags.get("natural", ""))
        label = LANDUSE_LABEL.get(key)
        if label is None:
            continue
        if el["type"] == "way":
            ring = [to_m(p["lat"], p["lon"]) for p in el["geometry"]]
            rings = [ring] if ring and ring[0] == ring[-1] else []
            inner: list[Ring] = []
        else:
            outer_ways = [[to_m(p["lat"], p["lon"]) for p in m["geometry"]] for m in el.get("members", []) if m.get("role") == "outer" and "geometry" in m]
            inner_ways = [[to_m(p["lat"], p["lon"]) for p in m["geometry"]] for m in el.get("members", []) if m.get("role") == "inner" and "geometry" in m]
            rings = assemble_rings(outer_ways)
            inner = assemble_rings(inner_ways)
        covered: set[int] = set()
        for ring in rings:
            covered |= fill(ring, GRID_SPACING_M, columns, rows)
        for ring in inner:
            covered -= fill(ring, GRID_SPACING_M, columns, rows)
        if not covered:
            continue
        gid = f"L{len(geography) + 1:04d}"
        geography.append(GeoObject(gid, "water" if label == "water" else "landuse", label, tags.get("name"), {key[0]: key[1]}, "polygon", sum(len(r) for r in rings)))
        paint(covered, label)

    # ---- areas ------------------------------------------------------------------------
    area_cells: dict[str, set[int]] = {}
    areas: list[Area] = []
    relations: list[Relation] = []

    def add_area(area_id: str, kind: str, description: str, cells: set[int]) -> None:
        counts = Counter(cell_label[i] for i in cells)
        area_cells[area_id] = cells
        areas.append(Area(area_id, kind, description, len(cells), dict(sorted(counts.items()))))

    settlement_ids: dict[str, str] = {}
    for n, (pid, name, ptype, xy) in enumerate(places, start=1):
        sid = f"S{n:02d}"
        settlement_ids[pid] = sid
        radius = SETTLEMENT_RADIUS_M[ptype]
        cells = disc(xy, radius, GRID_SPACING_M, columns, rows)
        paint(cells, "settlement")
        add_area(sid, "settlement", f"{name} ({ptype}): disc of radius {radius:g} m around the mapped place node, by the settlement rule.", cells)
    n = 0
    for route, segments in sorted(roads.items()):
        n += 1
        rid = f"R{n:02d}"
        classes = sorted({cls for cls, _ in segments})
        width = max(CORRIDOR_FULL_WIDTH_M[cls] for cls in classes)
        cells: set[int] = set()
        for _, line in segments:
            cells |= corridor(line, width / 2, GRID_SPACING_M, columns, rows)
        if len(cells) < MIN_CORRIDOR_LOCATIONS:
            continue
        add_area(rid, "road_corridor", f"{route} ({'/'.join(classes)}): road-centerline buffer with full width {width:g} m, {len(segments)} mapped segments.", cells)
        for pid, sid in settlement_ids.items():
            if cells & area_cells[sid]:
                relations.append(Relation(rid, "crosses", sid, f"corridor cells overlap the settlement disc ({len(cells & area_cells[sid])} grid cells)"))
    blocks_per_side = int(round(2 * half / BLOCK_SIZE_M))
    cells_per_block = int(BLOCK_SIZE_M / GRID_SPACING_M)
    for br in range(blocks_per_side):
        for bc in range(blocks_per_side):
            bid = f"B{br + 1}{chr(ord('a') + bc)}"
            cells = {r * columns + c for r in range(br * cells_per_block, (br + 1) * cells_per_block) for c in range(bc * cells_per_block, (bc + 1) * cells_per_block)}
            counts = Counter(cell_label[i] for i in cells)
            share = ", ".join(f"{k} {100 * v / len(cells):.0f}%" for k, v in counts.most_common())
            add_area(bid, "block", f"{BLOCK_SIZE_M / 1000:g} km square, row {br + 1} column {bc + 1} from the south-west corner. Mapped land use: {share}.", cells)
            for pid, sid in settlement_ids.items():
                if places[int(pid[1:]) - 1][3] and area_cells[sid] & cells:
                    relations.append(Relation(bid, "contains part of", sid, f"{len(area_cells[sid] & cells)} settlement grid cells inside the block"))

    region_summaries = [RegionSummary(a.id, a.grid_count, 0, a.grid_count) for a in areas]
    label_totals = Counter(cell_label)
    state = {
        "id": "state_00",
        "task": {
            "down_cell_id": DOWN_CELL,
            "outage_time": OUTAGE_TIME,
            "coverage_epoch": "before the outage time",
            "objective": f"Investigate the outage impact of cell {DOWN_CELL}: affected area, backup cells, resulting load.",
        },
        "site": {
            "cell_id": DOWN_CELL,
            "lat": SITE_LAT,
            "lon": SITE_LON,
            "x_m": round(site_xy[0], 1),
            "y_m": round(site_xy[1], 1),
            "metadata": {"environment": ENVIRONMENT, "note": "hypothetical site; metadata would come from cell.lookup"},
        },
        "study_area": {
            "rule": f"initial_window_by_environment[{ENVIRONMENT}] = {INITIAL_WINDOW_M[ENVIRONMENT]:g} m square centered on the site",
            "side_m": INITIAL_WINDOW_M[ENVIRONMENT],
            "south": origin_lat,
            "west": origin_lon,
            "north": 2 * SITE_LAT - origin_lat,
            "east": 2 * SITE_LON - origin_lon,
            "center": {"lat": SITE_LAT, "lon": SITE_LON},
        },
        "coordinate_system": "equirectangular local metres; origin at the study-area south-west corner; x east, y north",
        "grid": asdict(grid),
        "geography_summary": {
            "objects": len(geography),
            "by_label": dict(sorted(Counter(g.label for g in geography).items())),
            "places": [{"id": p[0], "name": p[1], "place": p[2]} for p in places],
            "routes": sorted(roads),
            "grid_cells_by_label": {k: label_totals[k] for k in LABEL_PRECEDENCE},
            "source": "OpenStreetMap via Overpass, query in overpass_query.txt",
        },
        "geography": [asdict(g) for g in geography],
        "areas": [asdict(a) for a in areas],
        "relations": [asdict(r) for r in relations],
        "regions": [asdict(s) for s in region_summaries],
        "cells_seen": [DOWN_CELL],
        "kpis": [],
        "impact": None,
        "notes": [],
        "unknowns": {
            "coverage": {
                "areas_unqueried": len(areas),
                "by_kind": dict(Counter(a.kind for a in areas)),
                "locations_unqueried": n_cells,
            },
            "backup_cells": "unknown until a coverage record lists a cell other than the down cell",
            "kpi": "none queried",
            "impact": "not computed",
        },
        "data_version": "osm-overpass-2026-10-08; coverage and KPI sources not yet attached",
    }
    (HERE / "state_00.json").write_text(json.dumps(state, indent=1), encoding="utf-8")
    (HERE / "areas_grid_ids.json").write_text(json.dumps({k: sorted(v) for k, v in area_cells.items()}), encoding="utf-8")
    (HERE / "context_state_00.txt").write_text(render(state, areas, relations), encoding="utf-8")
    (HERE / "map_state_00.svg").write_text(svg(cell_label, grid, areas, area_cells, places, site_xy, roads), encoding="utf-8")
    print(f"grid {columns}x{rows} = {n_cells} cells; geography objects {len(geography)}; areas {len(areas)} ({Counter(a.kind for a in areas)}); relations {len(relations)}")
    print("grid cells by label:", dict(label_totals))


def render(state: dict, areas: list[Area], relations: list[Relation]) -> str:
    t = state["task"]
    u = state["unknowns"]
    g = state["grid"]
    lines = [
        "Task:",
        f"Investigate the outage impact of cell {t['down_cell_id']}.",
        f"Outage time: {t['outage_time']}. Coverage epoch: {t['coverage_epoch']}.",
        f"Site of {t['down_cell_id']}: lat {state['site']['lat']}, lon {state['site']['lon']} "
        f"(x {state['site']['x_m']} m, y {state['site']['y_m']} m in the local frame). Environment class: {state['site']['metadata']['environment']}.",
        "",
        "Study area:",
        f"{state['study_area']['rule']}. Bounds: lat {state['study_area']['south']:.4f} to "
        f"{state['study_area']['north']:.4f}, lon {state['study_area']['west']:.4f} to "
        f"{state['study_area']['east']:.4f}. Analysis grid: {g['columns']} x {g['rows']} locations at {g['spacing_m']:g} m spacing; "
        f"{g['columns'] * g['rows']} locations in total. Coordinates are local metres, not latitude/longitude.",
        "",
        "Known geography (from OpenStreetMap; a land-use label says what the map shows, never how many people or how much traffic there is):",
        "Mapped grid cells by label: " + ", ".join(f"{k} {v}" for k, v in state["geography_summary"]["grid_cells_by_label"].items()) + ".",
        "Unmapped means no OpenStreetMap polygon covers the location; it is an area to query like any other.",
        "",
        "Areas (each resolves to a fixed set of grid locations; counts of overlapping areas must not be added together):",
    ]
    for a in areas:
        lines.append(f"- {a.id} [{a.kind}]: {a.description} Resolves to {a.grid_count} locations.")
    lines.append("")
    lines.append("Spatial relations:")
    for r in relations:
        lines.append(f"- {r.subject_id} {r.predicate} {r.object_id}. Evidence: {r.evidence}.")
    lines += [
        "",
        "Investigation progress:",
        "No coverage has been queried. Every area has 0 queried locations.",
        "Cells seen in coverage records: none yet; the down cell is the only known cell.",
        "Backup selection, traffic transfer and load estimation have not been performed.",
        "",
        "Remaining unknowns:",
        f"- Coverage: unknown in all {u['coverage']['areas_unqueried']} areas "
        f"({', '.join(f'{v} {k}s' for k, v in u['coverage']['by_kind'].items())}); "
        f"{u['coverage']['locations_unqueried']} locations unqueried.",
        f"- Backup cells: {u['backup_cells']}.",
        f"- KPI: {u['kpi']}. Impact: {u['impact']}.",
        "",
        "Scope of the investigation:",
        "You do not have to resolve every unknown. Decide which areas matter for the",
        f"impact of {t['down_cell_id']} and in what order, and stop when the evidence supports",
        "a result. When you choose finish, name the areas you leave unqueried in the gap",
        "targets and give the reason in the question. The program accepts a stop only if:",
        "- no query-boundary location of the study area shows the down cell (boundary rule),",
        "- every area left unqueried has no unqueried location bordering an observed",
        f"  {t['down_cell_id']} location, or is named with a reason (key-areas rule),",
        "- the backup load is estimated after the last coverage query (backup-load rule).",
        "Areas whose unqueried locations border observed down-cell coverage cannot be",
        "skipped; the program reports that border count for every open area after each query.",
        "",
        "Actions allowed now (phase coverage): coverage.query.",
        "",
    ]
    return "\n".join(lines)


def svg(cell_label: list[str], grid: Grid, areas: list[Area], area_cells: dict[str, set[int]], places, site_xy: Point, roads) -> str:
    colors = {"settlement": "#d75066", "industrial_commercial": "#8a5cc9", "water": "#3f74b9", "forest": "#2f855a", "farmland": "#d7b14a", "grassland": "#9ccc65", "unmapped": "#e8e8e8"}
    W = grid.columns
    px = 3  # pixels per grid cell
    size = W * px
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size + 220}" height="{size + 20}" viewBox="0 0 {size + 220} {size + 20}" font-family="Helvetica, Arial, sans-serif" font-size="11">']
    out.append(f'<rect width="{size + 220}" height="{size + 20}" fill="#ffffff"/>')
    # cells, rows run south to north so flip y
    for r in range(grid.rows):
        c = 0
        while c < W:
            label = cell_label[r * W + c]
            run = 1
            while c + run < W and cell_label[r * W + c + run] == label:
                run += 1
            if label != "unmapped":
                out.append(f'<rect x="{c * px}" y="{(grid.rows - 1 - r) * px}" width="{run * px}" height="{px}" fill="{colors[label]}"/>')
            c += run
    out.append(f'<rect x="0" y="0" width="{size}" height="{size}" fill="#e8e8e8" opacity="0" stroke="#222" stroke-width="1"/>')
    # blocks
    step = int(BLOCK_SIZE_M / grid.spacing_m) * px
    for k in range(0, size + 1, step):
        out.append(f'<line x1="{k}" y1="0" x2="{k}" y2="{size}" stroke="#555" stroke-width="0.6" stroke-dasharray="4 3"/>')
        out.append(f'<line x1="0" y1="{k}" x2="{size}" y2="{k}" stroke="#555" stroke-width="0.6" stroke-dasharray="4 3"/>')
    for a in areas:
        if a.kind == "block":
            br = int(a.id[1]) - 1; bc = ord(a.id[2]) - ord("a")
            out.append(f'<text x="{bc * step + 4}" y="{size - br * step - 4}" fill="#333" font-size="10">{a.id}</text>')
    # corridors
    for route, segments in roads.items():
        for _, line in segments:
            pts = " ".join(f"{x / grid.spacing_m * px:.1f},{size - y / grid.spacing_m * px:.1f}" for x, y in line)
            out.append(f'<polyline points="{pts}" fill="none" stroke="#111" stroke-width="1.2"/>')
    # settlements
    for n, (pid, name, ptype, (x, y)) in enumerate(places, start=1):
        radius = SETTLEMENT_RADIUS_M[ptype] / grid.spacing_m * px
        cx, cy = x / grid.spacing_m * px, size - y / grid.spacing_m * px
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius:.1f}" fill="none" stroke="#b00020" stroke-width="1.4"/>')
        out.append(f'<text x="{cx + radius + 2:.1f}" y="{cy + 4:.1f}" fill="#b00020" font-size="10">S{n:02d} {name}</text>')
    sx, sy = site_xy[0] / grid.spacing_m * px, size - site_xy[1] / grid.spacing_m * px
    out.append(f'<polygon points="{sx},{sy - 8} {sx - 7},{sy + 6} {sx + 7},{sy + 6}" fill="#000"/>')
    out.append(f'<text x="{sx + 10}" y="{sy + 4}" font-weight="bold">{DOWN_CELL} site</text>')
    # legend
    ly = 20
    out.append(f'<text x="{size + 12}" y="{ly}" font-weight="bold">Mapped land use (OSM)</text>')
    for k, v in colors.items():
        ly += 18
        out.append(f'<rect x="{size + 12}" y="{ly - 11}" width="14" height="12" fill="{v}" stroke="#777" stroke-width="0.5"/>')
        out.append(f'<text x="{size + 32}" y="{ly}">{k}</text>')
    ly += 28
    out.append(f'<text x="{size + 12}" y="{ly}">circles: settlement discs (S)</text>'); ly += 16
    out.append(f'<text x="{size + 12}" y="{ly}">black lines: road centerlines (R)</text>'); ly += 16
    out.append(f'<text x="{size + 12}" y="{ly}">dashed grid: 5 km blocks (B)</text>'); ly += 16
    out.append(f'<text x="{size + 12}" y="{ly}">30 km x 30 km, 100 m grid</text>'); ly += 16
    out.append(f'<text x="{size + 12}" y="{ly}">no coverage queried yet</text>')
    out.append("</svg>")
    return "\n".join(out)


if __name__ == "__main__":
    main()
