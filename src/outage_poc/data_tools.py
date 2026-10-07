"""The synthetic tool library: the four data actions over build_dataset().

Each tool is a function from a JSON-like argument mapping to a list of rows,
published with a declaration (name, description, parameter schema, data
version). The library holds the data and nothing about the investigation. The
internal environment replaces it with the same four declarations over the real
data functions; the row shapes and the meaning of an absent row stay the same.
"""

import hashlib
import json
from dataclasses import asdict

from outage_poc.data_client import (
    Arguments,
    LocalClient,
    LocalTool,
    Row,
    ToolDeclaration,
    ToolError,
)
from outage_poc.geometry import bounds, within_distance
from outage_poc.init import COVERAGE_EPOCH, derive_areas, resolve_area
from outage_poc.models import Area, Dataset, ObservationId
from outage_poc.synthetic import build_dataset, query_coverage


def dataset_version(dataset: Dataset) -> str:
    """SHA-256 over the canonical JSON of the whole dataset."""
    canonical = json.dumps(asdict(dataset), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _string(arguments: Arguments, name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str):
        raise ToolError(f"argument {name!r} must be a string")
    return value


def _number(arguments: Arguments, name: str) -> float:
    value = arguments.get(name)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ToolError(f"argument {name!r} must be a number")
    return float(value)


def _strings(arguments: Arguments, name: str) -> list[str]:
    value = arguments.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ToolError(f"argument {name!r} must be a list of strings")
    return [str(item) for item in value]


def cell_rows(dataset: Dataset, cell_id: str) -> list[Row]:
    matches = [
        item for item in dataset.geography if item.kind == "cell" and item.id == cell_id
    ]
    if len(matches) != 1:
        raise ToolError(f"unknown cell {cell_id!r}")
    left, bottom, right, top = bounds(matches[0].geometry)
    return [
        {
            "cell_id": cell_id,
            "x_m": (left + right) / 2,
            "y_m": (bottom + top) / 2,
            "metadata": {"kind": "cell", "description": matches[0].description},
        }
    ]


def geography_rows(
    dataset: Dataset, center_x_m: float, center_y_m: float, radius_m: float
) -> list[Row]:
    """Every mapped object with some part within the radius. Cell sites are not geography."""
    return [
        {
            "id": item.id,
            "kind": item.kind,
            "description": item.description,
            "geometry": asdict(item.geometry),
        }
        for item in dataset.geography
        if item.kind != "cell"
        and within_distance((center_x_m, center_y_m), item.geometry, radius_m)
    ]


def coverage_rows(
    dataset: Dataset, areas: tuple[Area, ...], area_ids: list[str], epoch: str
) -> list[Row]:
    """One row per grid location with data, in area order.

    A location with missing data has no row, as the design's result rule states.
    """
    if epoch != COVERAGE_EPOCH:
        raise ToolError(f"unknown epoch {epoch!r}; only {COVERAGE_EPOCH!r} exists")
    known = {area.id for area in areas}
    rows: list[Row] = []
    for area_id in area_ids:
        if area_id not in known:
            raise ToolError(f"unknown area {area_id!r}")
        parameters = resolve_area(dataset.grid, areas, area_id)
        observation = query_coverage(
            dataset, parameters, ObservationId(f"server_{area_id}")
        )
        rows.extend(
            {"area_id": area_id, **asdict(record)}
            for record in observation.records
            if record.status == "valid"
        )
    return rows


def kpi_rows(
    dataset: Dataset, cell_ids: list[str], window: str, indicators: list[str]
) -> list[Row]:
    """One row per cell and indicator, in request order."""
    rows: list[Row] = []
    for cell_id in cell_ids:
        for indicator in indicators:
            matches = [
                kpi
                for kpi in dataset.baseline_kpis
                if kpi.cell_id == cell_id
                and kpi.window == window
                and kpi.indicator == indicator
            ]
            if len(matches) != 1:
                raise ToolError(
                    f"no {indicator!r} KPI for cell {cell_id!r} in window {window!r}"
                )
            rows.append(asdict(matches[0]))
    return rows


def _schema(**properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(properties),
    }


STRING: dict[str, object] = {"type": "string"}
NUMBER: dict[str, object] = {"type": "number"}
STRINGS: dict[str, object] = {"type": "array", "items": {"type": "string"}}


def synthetic_tools(dataset: Dataset) -> tuple[LocalTool, ...]:
    """The four data actions, declared and bound to the synthetic dataset."""
    geography = tuple(item for item in dataset.geography if item.kind != "cell")
    known_areas = derive_areas(dataset.grid, geography, dataset.grid_spacing_m)
    version = dataset_version(dataset)

    def cell_lookup(arguments: Arguments) -> list[Row]:
        return cell_rows(dataset, _string(arguments, "cell_id"))

    def osm_geometry(arguments: Arguments) -> list[Row]:
        return geography_rows(
            dataset,
            _number(arguments, "center_x_m"),
            _number(arguments, "center_y_m"),
            _number(arguments, "radius_m"),
        )

    def coverage_query(arguments: Arguments) -> list[Row]:
        return coverage_rows(
            dataset,
            known_areas,
            _strings(arguments, "areas"),
            _string(arguments, "epoch"),
        )

    def kpi_query(arguments: Arguments) -> list[Row]:
        return kpi_rows(
            dataset,
            _strings(arguments, "cells"),
            _string(arguments, "window"),
            _strings(arguments, "indicators"),
        )

    return (
        LocalTool(
            ToolDeclaration(
                "cell.lookup",
                "Site position (local metres) and metadata of one cell.",
                _schema(cell_id=STRING),
                version,
            ),
            cell_lookup,
        ),
        LocalTool(
            ToolDeclaration(
                "osm.geometry",
                (
                    "Mapped geography objects with some part within a radius of a "
                    "point: the study area, settlements, roads as centrelines, and "
                    "land use."
                ),
                _schema(center_x_m=NUMBER, center_y_m=NUMBER, radius_m=NUMBER),
                version,
            ),
            osm_geometry,
        ),
        LocalTool(
            ToolDeclaration(
                "coverage.query",
                (
                    "Pre-outage coverage for every analysis grid location in each "
                    "named area: data status (valid or missing), each cell present "
                    "with RSRP and RSRQ, and synthetic down-cell traffic."
                ),
                _schema(areas=STRINGS, epoch=STRING),
                version,
            ),
            coverage_query,
        ),
        LocalTool(
            ToolDeclaration(
                "kpi.query",
                (
                    "Pre-outage KPI of each named cell, one row per indicator: "
                    "prb_utilization (percent of PRBs in use) and capacity (Mbps)."
                ),
                _schema(cells=STRINGS, window=STRING, indicators=STRINGS),
                version,
            ),
            kpi_query,
        ),
    )


def synthetic_client() -> LocalClient:
    """The client the command line and the tests use."""
    return LocalClient(synthetic_tools(build_dataset()))
