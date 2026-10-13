"""Additive sector CSV evidence for the investigation harness.

Place this module beside evidence_state.py.

Heatmap coverage, coverage_samples, summaries, regions, and cells_seen
remain unchanged when applying a sector CSV.

Use a pre-integration state or a new run, not the older merged-source
adapter.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path

from . import evidence_state as evidence


SECTOR_TOOL_NAME = "query_sector_coverage"

SEMANTICS = (
    "Per-sector returned samples inside the study grid. Missing rows are unknown, "
    "not proof of no coverage. Valid RSRP is not a coverage-threshold decision. "
    "Shared grid occupancy does not establish same-point overlap. No overlap "
    "ratio or backup suitability has been calculated."
)


def _contract(observation: dict) -> tuple[str, str, dict]:
    oid = observation.get("id")
    action = observation.get("action")
    result = observation.get("result")

    if not isinstance(oid, str) or not oid:
        raise ValueError("Observation requires a non-empty string id")

    if (
        not isinstance(action, dict)
        or action.get("function") != SECTOR_TOOL_NAME
    ):
        raise ValueError(
            f"Expected action.function={SECTOR_TOOL_NAME}"
        )

    params = observation.get(
        "parameters",
        action.get("parameters"),
    )
    sector = (
        params.get("sector_id")
        if isinstance(params, dict)
        else None
    )

    if not isinstance(sector, str) or not sector.strip():
        raise ValueError(
            "Observation requires action.parameters.sector_id"
        )

    if (
        not isinstance(result, dict)
        or result.get("status") not in {"success", "error"}
    ):
        raise ValueError(
            "Observation result.status must be success or error"
        )

    return oid, sector.strip(), result


def _register(state: dict, observation: dict) -> None:
    oid = observation["id"]
    prior = state.get("observations", [])
    record = copy.deepcopy(observation)

    # Preserve metadata produced by the existing evidence parser.
    details = {}
    for item in prior:
        if (
            item.get("id", item.get("observation_id")) == oid
            and isinstance(item.get("result"), dict)
        ):
            details.update(item["result"])

    record["result"] = {
        **details,
        **record["result"],
    }

    result = record["result"]
    action = record["action"]

    path = None
    if result.get("status") == "success":
        path = (
            result.get("output_file")
            or result.get("csv_path")
        )

    record.update(
        observation_id=oid,
        function=action["function"],
        kind=action["function"],
        params=copy.deepcopy(
            record.get(
                "parameters",
                action.get("parameters", {}),
            )
        ),
        files=[str(path)] if path else [],
        source=result.get("source", "tool_error"),
    )

    state["observations"] = [
        item
        for item in prior
        if item.get("id", item.get("observation_id")) != oid
    ] + [record]

    state["evidence_ids"] = list(
        dict.fromkeys([
            *state.get("evidence_ids", []),
            oid,
        ])
    )

    if path:
        state["available"] = list(
            dict.fromkeys([
                *state.get("available", []),
                str(path),
            ])
        )


def _parse_csv(
    path: Path,
    sector: str,
    oid: str,
    geometry: dict,
) -> dict:
    memberships: dict[str, list[str]] = {}

    for area_id, area in geometry["areas"].items():
        for grid_id in area["grid_ids"]:
            memberships.setdefault(
                str(grid_id),
                [],
            ).append(area_id)

    known = set(memberships)

    counts = {
        "row_count": 0,
        "invalid_coordinate_count": 0,
        "outside_scope_count": 0,
        "duplicate_row_count": 0,
        "missing_rsrp_count": 0,
        "valid_row_count": 0,
        "invalid_distance_count": 0,
    }

    grids = {}
    samples = []
    seen = set()

    with path.open(
        newline="",
        encoding="utf-8-sig",
    ) as stream:
        reader = csv.DictReader(stream, strict=True)

        fields = [
            evidence._normalize(name)
            for name in reader.fieldnames or []
        ]
        required = {
            "lng",
            "lat",
            "meanrsrpdbm",
            "eudlideandistm",
        }

        if (
            not required <= set(fields)
            or len(fields) != len(set(fields))
        ):
            raise ValueError(
                "CSV needs unique lng, lat, mean_RSRP_dbm, "
                "eudlidean_dist_m headers"
            )

        for raw in reader:
            counts["row_count"] += 1

            if (
                None in raw
                or any(value is None for value in raw.values())
            ):
                raise ValueError(
                    f"CSV row {reader.line_num} "
                    "has the wrong number of fields"
                )

            row = evidence._row(raw)

            lng = evidence._number(
                evidence._get(row, "lng")
            )
            lat = evidence._number(
                evidence._get(row, "lat")
            )

            if (
                lng is None
                or lat is None
                or not (
                    -180 <= lng <= 180
                    and -90 <= lat <= 90
                )
            ):
                counts["invalid_coordinate_count"] += 1
                continue

            # Ignore unexpected grid_id/x/y columns.
            grid_id = evidence._locate(
                {
                    "lng": str(lng),
                    "lat": str(lat),
                },
                geometry,
                known,
            )

            if grid_id is None:
                counts["outside_scope_count"] += 1
                continue

            rsrp = evidence._number(
                evidence._get(row, "mean_RSRP_dbm")
            )
            distance = evidence._number(
                evidence._get(row, "eudlidean_dist_m")
            )

            if distance is not None and distance < 0:
                distance = None

            key = (lng, lat, rsrp, distance)

            if key in seen:
                counts["duplicate_row_count"] += 1
                continue

            seen.add(key)
            counts["invalid_distance_count"] += (
                distance is None
            )

            grid = grids.setdefault(
                grid_id,
                {
                    "status": "missing",
                    "observation": oid,
                    "area_ids": memberships[grid_id],
                    "cells": {},
                    "sample_count": 0,
                    "valid_sample_count": 0,
                    "missing_sample_count": 0,
                },
            )

            grid["sample_count"] += 1

            samples.append({
                "observation": oid,
                "grid_id": grid_id,
                "area_ids": memberships[grid_id],
                "cell_id": sector,
                "longitude": lng,
                "latitude": lat,
                "rsrp_dbm": rsrp,
                "eudlidean_dist_m": distance,
                "status": (
                    "valid"
                    if rsrp is not None
                    else "missing"
                ),
            })

            if rsrp is None:
                counts["missing_rsrp_count"] += 1
                grid["missing_sample_count"] += 1
                continue

            counts["valid_row_count"] += 1
            grid["status"] = "valid"
            grid["valid_sample_count"] += 1

            evidence._add_signal(
                grid["cells"],
                sector,
                rsrp,
            )

    if (
        counts["row_count"]
        and counts["invalid_coordinate_count"]
        == counts["row_count"]
    ):
        raise ValueError(
            "All CSV rows have invalid coordinates"
        )

    return {
        "sector_id": sector,
        "cell_id": sector,
        "observation_id": oid,
        "grids": grids,
        "samples": samples,
        **counts,
        "retained_row_count": len(samples),
        "sampled_grid_count": len(grids),
        "valid_grid_count": sum(
            grid["status"] == "valid"
            for grid in grids.values()
        ),
    }


def _snapshot(
    observation: dict,
    run_dir: str | Path,
) -> tuple[Path, str]:
    path = evidence._csv_path(observation, run_dir)
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()

    snapshot = evidence._root_path(
        run_dir,
        Path("artifacts/sector_coverage")
        / digest
        / path.name,
    )
    snapshot.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        with snapshot.open("xb") as stream:
            stream.write(content)
    except FileExistsError:
        if snapshot.read_bytes() != content:
            raise ValueError(
                "Sector CSV snapshot hash conflict"
            ) from None

    return snapshot, digest


def _refresh_progress(state: dict) -> None:
    section = state["sector_coverage"]

    known = state.get(
        "sector_ids",
        state.get("cells_seen"),
    )
    known = (
        sorted(set(known))
        if (
            isinstance(known, list)
            and all(isinstance(x, str) for x in known)
        )
        else None
    )

    queries = section["queries"]
    active = section["by_sector"]

    section["progress"] = {
        "known_sector_ids": known,
        "attempted_sector_ids": sorted(queries),
        "loaded_sector_ids": sorted(active),
        "latest_failed_sector_ids": sorted(
            sector
            for sector, query in queries.items()
            if query["status"] == "error"
        ),
        "unqueried_sector_ids": (
            sorted(set(known) - set(queries))
            if known is not None
            else None
        ),
        "sectors_without_loaded_csv": (
            sorted(set(known) - set(active))
            if known is not None
            else None
        ),
        "sectors_without_valid_samples": sorted(
            sector
            for sector, data in active.items()
            if not data["valid_row_count"]
        ),
    }

    section["semantics"] = SEMANTICS


def apply_sector_coverage(
    state: dict,
    observation: dict,
    run_dir: str | Path,
) -> dict:
    """Ingest one sector query without mutating the input state.

    Expected observation:
        id
        action.function
        action.parameters.sector_id
        result.status: "success" or "error"
        result.output_file: CSV inside run_dir

    CSV/schema/IO errors are recorded as ingestion errors and preserve
    the last good sector source. A header-only CSV is valid empty
    evidence, not proof of no coverage.
    """
    oid, sector, result = _contract(observation)

    if "coverage_sources" in state:
        raise ValueError(
            "Use a fresh/pre-integration state; "
            "the older merged-source adapter is incompatible"
        )

    updated = copy.deepcopy(state)

    section = updated.setdefault(
        "sector_coverage",
        {
            "by_sector": {},
            "queries": {},
            "comparisons": {},
        },
    )

    canonical = copy.deepcopy(observation)

    previous = next(
        (
            item
            for item in state.get("observations", [])
            if item.get(
                "id",
                item.get("observation_id"),
            ) == oid
        ),
        None,
    )

    if previous is not None:
        prior_ingestion = previous.get("ingestion", {})
        prior_result = previous.get("result", {})

        if (
            prior_ingestion.get("sector_id") != sector
            or prior_result.get(
                "fetch_status",
                prior_result.get("status"),
            ) != result["status"]
        ):
            raise ValueError(
                "An observation id cannot be reused "
                "for another query or outcome"
            )

        if prior_result.get("status") == "success":
            path = evidence._csv_path(
                observation,
                run_dir,
            )
            digest = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()

            if digest != prior_ingestion.get("sha256"):
                raise ValueError(
                    "An observation id cannot refer "
                    "to different CSV contents"
                )

        # Replaying an old observation must not restore old data.
        return updated

    query = {
        "observation_id": oid,
        "sector_id": sector,
        "status": result["status"],
    }

    if result["status"] == "success":
        geometry = evidence._geometry(state, run_dir)

        try:
            snapshot, digest = _snapshot(
                observation,
                run_dir,
            )
            parsed = _parse_csv(
                snapshot,
                sector,
                oid,
                geometry,
            )
        except (
            OSError,
            UnicodeError,
            csv.Error,
            ValueError,
        ) as exc:
            canonical["result"].update(
                status="error",
                fetch_status="success",
                error_type="SectorCoverageIngestionError",
                error=str(exc),
            )
            query.update(
                status="error",
                error=str(exc),
            )
        else:
            relative = snapshot.relative_to(
                Path(run_dir).resolve()
            ).as_posix()

            parsed.update(
                csv_path=relative,
                sha256=digest,
            )

            section["by_sector"][sector] = parsed

            # New evidence invalidates derived overlap results.
            section["comparisons"] = {}

            query.update({
                key: value
                for key, value in parsed.items()
                if key not in {"grids", "samples"}
            })

            canonical["result"].update(
                output_file=str(snapshot),
                csv_path=relative,
                row_count=parsed["row_count"],
                retained_row_count=parsed[
                    "retained_row_count"
                ],
            )
    else:
        query["error"] = result.get(
            "error",
            "Sector query failed",
        )

    section["queries"][sector] = query
    canonical["ingestion"] = copy.deepcopy(query)

    _register(updated, canonical)
    _refresh_progress(updated)

    return updated


def update_evidence_state(
    state: dict,
    observation: dict,
    run_dir: str | Path,
) -> dict:
    """Dispatch evidence updates from update_state_node.

    Final-report, inspection, routing, and JSON persistence stay
    in the caller.
    """
    action = observation["action"]["function"]

    if action == SECTOR_TOOL_NAME:
        return apply_sector_coverage(
            state,
            observation,
            run_dir,
        )

    success = (
        observation["result"].get("status") == "success"
    )
    spatial = isinstance(
        state.get("geography"),
        dict,
    )

    if (
        success
        and spatial
        and action in {
            "query_coverage_heatmap",
            "query_area_coverage",
        }
    ):
        updated = evidence.apply_coverage(
            state,
            observation,
            run_dir,
        )

        updated.setdefault(
            "coverage_artifacts",
            {},
        )["latest"] = copy.deepcopy(
            observation["result"]
        )

    elif (
        success
        and spatial
        and action in {
            "query_nr_rrc_prb",
            "query_lte_rrc_prb",
        }
    ):
        updated = evidence.apply_kpi(
            state,
            observation,
            run_dir,
        )

    else:
        from .runner import (
            _apply_coverage_progress,
            _update_state,
        )

        updated = _update_state(
            copy.deepcopy(state),
            observation,
        )

        if (
            success
            and not spatial
            and action in {
                "query_coverage_heatmap",
                "query_area_coverage",
            }
        ):
            updated = _apply_coverage_progress(
                updated,
                Path(run_dir),
            )

    _register(updated, observation)

    if "sector_coverage" in updated:
        _refresh_progress(updated)

    return updated


def inspect_sector_coverage(
    state: dict,
    sector_id: str,
    area_id: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> list[dict]:
    """Inspect active raw samples for one sector."""
    if any(
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        for value in (offset, limit)
    ):
        raise ValueError(
            "offset and limit must be nonnegative integers"
        )

    if (
        area_id is not None
        and area_id not in state["geography"]["areas"]
    ):
        raise ValueError(f"Unknown area: {area_id}")

    source = (
        state.get("sector_coverage", {})
        .get("by_sector", {})
        .get(sector_id)
    )

    if source is None:
        raise ValueError(
            "No successfully loaded CSV for sector: "
            f"{sector_id}"
        )

    samples = [
        sample
        for sample in source["samples"]
        if (
            area_id is None
            or area_id in sample["area_ids"]
        )
    ]

    return copy.deepcopy(
        samples[offset:offset + limit]
    )


def inspect_coverage(
    state: dict,
    observation_id: str | None,
    area_id: str | None,
    offset: int,
    limit: int,
) -> list[dict]:
    """Keep the existing inspector interface.

    Sector observation IDs select the corresponding sector grids.
    observation_id=None keeps the heatmap-only behavior.

    Superseded sector observations have no active rows; their
    immutable CSV remains available through the observation record.
    """
    if any(
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        for value in (offset, limit)
    ):
        raise ValueError(
            "offset and limit must be nonnegative integers"
        )

    if (
        area_id is not None
        and area_id not in state["geography"]["areas"]
    ):
        raise ValueError(f"Unknown area: {area_id}")

    sources = (
        state.get("sector_coverage", {})
        .get("by_sector", {})
    )

    for source in sources.values():
        if source["observation_id"] == observation_id:
            rows = [
                {
                    "grid_id": grid_id,
                    **grid,
                }
                for grid_id, grid in sorted(
                    source["grids"].items()
                )
                if (
                    area_id is None
                    or area_id in grid["area_ids"]
                )
            ]

            return copy.deepcopy(
                rows[offset:offset + limit]
            )

    return evidence.inspect_coverage(
        state,
        observation_id,
        area_id,
        offset,
        limit,
    )


def render_sector_coverage_context(state: dict) -> str:
    section = state.get("sector_coverage")

    if not section:
        return ""

    active = {
        sector: {
            key: value
            for key, value in data.items()
            if key not in {"grids", "samples"}
        }
        for sector, data in section["by_sector"].items()
    }

    payload = {
        "progress": section["progress"],
        "active_sources": active,
        "latest_queries": section["queries"],
        "semantics": SEMANTICS,
    }

    return (
        "Sector coverage evidence:\n"
        + json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
        )
    )
