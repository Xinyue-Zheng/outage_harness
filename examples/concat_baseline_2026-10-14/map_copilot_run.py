"""Draw the locations that a Copilot baseline run read, from its records.

    python map_copilot_run.py <run folder> [--site LAT,LON] [--site LAT,LON]

Reads `<run folder>/records/reads.jsonl` and writes, into the run folder:

    map_classes.svg   every read location, coloured by its class
    map_order.svg     every read location, coloured by the order it was read in
    reads.geojson     the same points, for any map viewer

The script uses the standard library only and makes no network call. Open the
SVG files in a browser or in the editor. Do not upload `reads.geojson` to a
public web viewer.

If the records use other field names, edit the three constants below. The
script stops with the field names it found when one of them is missing.
"""

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

FIELD_CLASS = "class"
FIELD_CENTRE = "centre"  # [lat, lon], or {"lat": ..., "lon": ...}
FIELD_ORDER = "index"

CLASS_COLOURS: dict[str, str] = {
    "covered_backup": "#1a9850",
    "covered_no_backup": "#d73027",
    "not_covered": "#4575b4",
    "no_sample": "#bdbdbd",
    "error": "#000000",
}
ORDER_RAMP: tuple[tuple[int, int, int], ...] = (
    (68, 1, 84),
    (59, 82, 139),
    (33, 145, 140),
    (94, 201, 98),
    (253, 231, 37),
)
GRID_M = 100.0
MAP_PX = 900
MARGIN_PX = 60
LEGEND_PX = 230
METRES_PER_DEGREE_LAT = 110_540.0
METRES_PER_DEGREE_LON = 111_320.0


@dataclass(frozen=True)
class Read:
    order: int
    lat: float
    lon: float
    location_class: str


@dataclass(frozen=True)
class Frame:
    """Projection of latitude and longitude to pixels, north up, equal scale on both axes."""

    lat0: float
    lon0: float
    half_m: float

    @property
    def px_per_m(self) -> float:
        return (MAP_PX - 2 * MARGIN_PX) / (2 * self.half_m)

    def xy(self, lat: float, lon: float) -> tuple[float, float]:
        east = (
            (lon - self.lon0)
            * METRES_PER_DEGREE_LON
            * math.cos(math.radians(self.lat0))
        )
        north = (lat - self.lat0) * METRES_PER_DEGREE_LAT
        return MAP_PX / 2 + east * self.px_per_m, MAP_PX / 2 - north * self.px_per_m


def number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SystemExit(f"{what} is not a number: {value!r}")
    return float(value)


def centre_of(value: object) -> tuple[float, float]:
    if isinstance(value, list | tuple) and len(value) == 2:
        return number(value[0], "latitude"), number(value[1], "longitude")
    if isinstance(value, dict) and "lat" in value and "lon" in value:
        return number(value["lat"], "latitude"), number(value["lon"], "longitude")
    raise SystemExit(
        f"Field {FIELD_CENTRE!r} is neither [lat, lon] nor {{lat, lon}}: {value!r}"
    )


def load_reads(path: Path) -> list[Read]:
    if not path.is_file():
        raise SystemExit(f"Not found: {path}")
    reads: list[Read] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        record: object = json.loads(line)
        if not isinstance(record, dict):
            raise SystemExit(f"{path} line {line_number} is not a JSON object")
        missing = [
            name
            for name in (FIELD_CLASS, FIELD_CENTRE, FIELD_ORDER)
            if name not in record
        ]
        if missing:
            raise SystemExit(
                f"{path} line {line_number} has no field {missing}. Fields found: {sorted(record)}. "
                "Edit the FIELD_ constants at the top of this script."
            )
        lat, lon = centre_of(record[FIELD_CENTRE])
        reads.append(
            Read(
                order=int(number(record[FIELD_ORDER], FIELD_ORDER)),
                lat=lat,
                lon=lon,
                location_class=str(record[FIELD_CLASS]),
            )
        )
    if not reads:
        raise SystemExit(f"{path} holds no read")
    return sorted(reads, key=lambda read: read.order)


def parse_site(text: str) -> tuple[float, float]:
    parts = text.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("a site is LAT,LON")
    return float(parts[0]), float(parts[1])


def frame_for(reads: list[Read], sites: list[tuple[float, float]]) -> Frame:
    points = [(read.lat, read.lon) for read in reads] + sites
    lat0 = sum(lat for lat, _ in points) / len(points)
    lon0 = sum(lon for _, lon in points) / len(points)
    probe = Frame(lat0, lon0, 1.0)
    reach = 0.0
    for lat, lon in points:
        x, y = probe.xy(lat, lon)
        reach = max(
            reach,
            abs(x - MAP_PX / 2) / probe.px_per_m,
            abs(y - MAP_PX / 2) / probe.px_per_m,
        )
    return Frame(lat0, lon0, max(reach, 500.0) * 1.05)


def ring_step_m(half_m: float) -> float:
    for step in (500.0, 1000.0, 2000.0, 5000.0, 10000.0, 20000.0):
        if half_m / step <= 8:
            return step
    return 50000.0


def ramp_colour(share: float) -> str:
    position = min(max(share, 0.0), 1.0) * (len(ORDER_RAMP) - 1)
    low = min(int(position), len(ORDER_RAMP) - 2)
    part = position - low
    red, green, blue = (
        round(
            ORDER_RAMP[low][channel]
            + part * (ORDER_RAMP[low + 1][channel] - ORDER_RAMP[low][channel])
        )
        for channel in range(3)
    )
    return f"#{red:02x}{green:02x}{blue:02x}"


def svg_base(frame: Frame, sites: list[tuple[float, float]], title: str) -> list[str]:
    width = MAP_PX + LEGEND_PX
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{MAP_PX}" '
        f'viewBox="0 0 {width} {MAP_PX}" font-family="sans-serif" font-size="13">',
        f'<rect width="{width}" height="{MAP_PX}" fill="#ffffff"/>',
        f'<text x="{MARGIN_PX}" y="28" font-size="17">{title}</text>',
        f'<text x="{MAP_PX - MARGIN_PX}" y="28" text-anchor="end">north is up</text>',
    ]
    step = ring_step_m(frame.half_m)
    for site_lat, site_lon in sites:
        x, y = frame.xy(site_lat, site_lon)
        radius_m = step
        while radius_m <= frame.half_m * 1.5:
            radius_px = radius_m * frame.px_per_m
            parts.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius_px:.1f}" fill="none" stroke="#dddddd"/>'
            )
            parts.append(
                f'<text x="{x + 3:.1f}" y="{y - radius_px - 3:.1f}" fill="#999999" font-size="11">'
                f"{radius_m / 1000:g} km</text>"
            )
            radius_m += step
    bar_px = step * frame.px_per_m
    bar_y = MAP_PX - 24
    parts.append(
        f'<line x1="{MARGIN_PX}" y1="{bar_y}" x2="{MARGIN_PX + bar_px:.1f}" y2="{bar_y}" stroke="#000000" stroke-width="2"/>'
    )
    parts.append(f'<text x="{MARGIN_PX}" y="{bar_y - 6}">{step / 1000:g} km</text>')
    return parts


def svg_sites(frame: Frame, sites: list[tuple[float, float]]) -> list[str]:
    parts: list[str] = []
    for number_of_site, (site_lat, site_lon) in enumerate(sites, start=1):
        x, y = frame.xy(site_lat, site_lon)
        parts.append(
            f'<path d="M {x:.1f} {y - 9:.1f} L {x + 8:.1f} {y + 7:.1f} L {x - 8:.1f} {y + 7:.1f} Z" fill="#000000" stroke="#ffffff"/>'
        )
        parts.append(
            f'<text x="{x + 11:.1f}" y="{y + 5:.1f}" font-weight="bold">site {number_of_site}</text>'
        )
    return parts


def square(frame: Frame, read: Read, colour: str, hollow: bool) -> str:
    x, y = frame.xy(read.lat, read.lon)
    side = max(GRID_M * frame.px_per_m, 3.0)
    fill = "none" if hollow else colour
    return (
        f'<rect x="{x - side / 2:.1f}" y="{y - side / 2:.1f}" width="{side:.1f}" height="{side:.1f}" '
        f'fill="{fill}" stroke="{colour}" stroke-width="0.6"/>'
    )


def legend_row(row: int, colour: str, label: str, hollow: bool) -> list[str]:
    y = 70 + row * 26
    fill = "none" if hollow else colour
    return [
        f'<rect x="{MAP_PX + 10}" y="{y - 11}" width="13" height="13" fill="{fill}" stroke="{colour}"/>',
        f'<text x="{MAP_PX + 32}" y="{y}">{label}</text>',
    ]


def classes_svg(
    reads: list[Read], sites: list[tuple[float, float]], frame: Frame
) -> str:
    parts = svg_base(frame, sites, f"Locations read, by class ({len(reads)} locations)")
    seen = sorted({read.location_class for read in reads})
    unknown = [name for name in seen if name not in CLASS_COLOURS]
    if unknown:
        raise SystemExit(f"Unknown class {unknown}. Add a colour to CLASS_COLOURS.")
    # Draw the classes that say least first, so that covered locations stay visible.
    for name in (
        "no_sample",
        "error",
        "not_covered",
        "covered_backup",
        "covered_no_backup",
    ):
        for read in reads:
            if read.location_class == name:
                parts.append(
                    square(frame, read, CLASS_COLOURS[name], hollow=name == "no_sample")
                )
    parts += svg_sites(frame, sites)
    for row, name in enumerate(CLASS_COLOURS):
        count = sum(1 for read in reads if read.location_class == name)
        parts += legend_row(
            row, CLASS_COLOURS[name], f"{name}: {count}", hollow=name == "no_sample"
        )
    return "\n".join(parts + ["</svg>"])


def order_svg(reads: list[Read], sites: list[tuple[float, float]], frame: Frame) -> str:
    parts = svg_base(frame, sites, f"Locations read, by order ({len(reads)} locations)")
    last = max(len(reads) - 1, 1)
    for position, read in enumerate(reads):
        parts.append(square(frame, read, ramp_colour(position / last), hollow=False))
    parts += svg_sites(frame, sites)
    for row, share in enumerate((0.0, 0.25, 0.5, 0.75, 1.0)):
        parts += legend_row(
            row,
            ramp_colour(share),
            f"read number {round(share * last) + 1}",
            hollow=False,
        )
    return "\n".join(parts + ["</svg>"])


def geojson(reads: list[Read]) -> str:
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [read.lon, read.lat]},
            "properties": {"order": read.order, "class": read.location_class},
        }
        for read in reads
    ]
    return json.dumps({"type": "FeatureCollection", "features": features})


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Draw the locations a Copilot baseline run read."
    )
    parser.add_argument("run_folder", type=Path)
    parser.add_argument(
        "--site",
        type=parse_site,
        action="append",
        default=[],
        help="a down site as LAT,LON; repeat for more",
    )
    arguments = parser.parse_args()
    run_folder: Path = arguments.run_folder
    sites: list[tuple[float, float]] = arguments.site

    reads = load_reads(run_folder / "records" / "reads.jsonl")
    frame = frame_for(reads, sites)
    outputs = {
        "map_classes.svg": classes_svg(reads, sites, frame),
        "map_order.svg": order_svg(reads, sites, frame),
        "reads.geojson": geojson(reads),
    }
    for name, text in outputs.items():
        (run_folder / name).write_text(text, encoding="utf-8")
        print(f"wrote {run_folder / name}")


if __name__ == "__main__":
    main()
