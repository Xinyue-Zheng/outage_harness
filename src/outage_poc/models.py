"""Immutable contracts shared by the data server, the harness and the UI exporter."""

from dataclasses import dataclass
from typing import Literal, NewType

Coordinate = tuple[float, float]

GridId = NewType("GridId", str)
AreaId = NewType("AreaId", str)
CellId = NewType("CellId", str)
ObservationId = NewType("ObservationId", str)
StepId = NewType("StepId", str)


@dataclass(frozen=True)
class TaskInput:
    """The investigation request, before initialization looks up the site."""

    down_cell_id: CellId
    outage_time: str
    objective: str


@dataclass(frozen=True)
class Task:
    down_cell_id: CellId
    outage_time: str
    objective: str
    site_x_m: float
    site_y_m: float
    # Fixed by the outage time at initialization; carried on every coverage and KPI query.
    coverage_epoch: Literal["pre_outage"]


@dataclass(frozen=True)
class GridPoint:
    id: GridId
    x_m: float
    y_m: float
    column: int
    row: int


@dataclass(frozen=True)
class Geometry:
    kind: Literal["polygon", "polyline", "buffer"]
    coordinates: tuple[Coordinate, ...]
    buffer_width_m: float | None


GeoKind = Literal[
    "settlement", "highway", "farmland", "vineyard", "forest", "study_area", "cell"
]


@dataclass(frozen=True)
class GeoObject:
    id: str
    kind: GeoKind
    description: str
    geometry: Geometry


@dataclass(frozen=True)
class SpatialRelation:
    subject_id: str
    predicate: str
    object_id: str
    evidence: str


@dataclass(frozen=True)
class Area:
    id: AreaId
    description: str
    geometry: Geometry
    grid_ids: tuple[GridId, ...]
    parent_id: AreaId | None


@dataclass(frozen=True)
class Signal:
    cell_id: CellId
    rsrp_dbm: float
    rsrq_db: float


@dataclass(frozen=True)
class CoverageRecord:
    grid_id: GridId
    status: Literal["valid", "missing"]
    cells: tuple[Signal, ...]
    # Synthetic demand assigned to the down cell, not population inferred from land use.
    down_cell_traffic_mbps: float | None


KpiIndicator = Literal["prb_utilization", "capacity"]
KPI_UNITS: dict[KpiIndicator, Literal["percent", "Mbps"]] = {
    "prb_utilization": "percent",
    "capacity": "Mbps",
}


@dataclass(frozen=True)
class KPIRecord:
    """One row of kpi.query: one pre-outage indicator of one cell."""

    cell_id: CellId
    window: Literal["pre_outage"]
    indicator: KpiIndicator
    value: float
    unit: Literal["percent", "Mbps"]


@dataclass(frozen=True)
class BaselineKPI:
    """The KPI values that one impact estimate used in its load formula."""

    cell_id: CellId
    baseline_prb_percent: float
    capacity_mbps: float


@dataclass(frozen=True)
class Dataset:
    """Everything the synthetic data server holds. The harness never reads it."""

    task: TaskInput
    grid_spacing_m: float
    grid: tuple[GridPoint, ...]
    geography: tuple[GeoObject, ...]
    records: tuple[CoverageRecord, ...]
    baseline_kpis: tuple[KPIRecord, ...]


@dataclass(frozen=True)
class QueryParameters:
    area_id: AreaId
    geometry: Geometry
    grid_ids: tuple[GridId, ...]
    coordinate_system: str
    coverage_epoch: str


@dataclass(frozen=True)
class CoverageObservation:
    id: ObservationId
    source: Literal["synthetic"]
    parameters: QueryParameters
    result_status: Literal["complete", "partial_missing", "all_missing"]
    records: tuple[CoverageRecord, ...]


@dataclass(frozen=True)
class ObservationLink:
    observation_id: ObservationId
    path: str
    area_id: AreaId
    grid_ids: tuple[GridId, ...]


@dataclass(frozen=True)
class GridEvidence:
    grid_id: GridId
    observation_id: ObservationId


@dataclass(frozen=True)
class RegionSummary:
    area_id: AreaId
    total_ids: tuple[GridId, ...]
    queried_ids: tuple[GridId, ...]
    unqueried_ids: tuple[GridId, ...]
    valid_ids: tuple[GridId, ...]
    missing_ids: tuple[GridId, ...]
    valid_covered_ids: tuple[GridId, ...]
    no_coverage_ids: tuple[GridId, ...]
    # Valid locations with cells, but without the target. Not the same as no coverage.
    other_cells_only_ids: tuple[GridId, ...]
    target_ids: tuple[GridId, ...]
    target_rsrp_min_dbm: float | None
    target_rsrp_max_dbm: float | None
    boundary_ids: tuple[GridId, ...]
    boundary_valid_ids: tuple[GridId, ...]
    boundary_missing_ids: tuple[GridId, ...]
    boundary_target_ids: tuple[GridId, ...]
    observation_ids: tuple[ObservationId, ...]


@dataclass(frozen=True)
class BackupAssignment:
    grid_id: GridId
    backup_cell_id: CellId | None
    classification: Literal["transferred", "no_eligible_backup"]
    traffic_mbps: float


@dataclass(frozen=True)
class BackupLoad:
    cell_id: CellId
    assigned_locations: int
    location_share: float
    transferred_mbps: float
    traffic_share: float
    baseline_prb_percent: float
    capacity_mbps: float
    estimated_prb_percent: float
    exceeds_capacity: bool


@dataclass(frozen=True)
class LoadParameters:
    scope_area_id: AreaId
    minimum_rsrp_dbm: float
    minimum_rsrq_db: float
    selection_rule: str
    load_formula: str


@dataclass(frozen=True)
class ImpactAnalysis:
    source: Literal["synthetic"]
    parameters: LoadParameters
    scope_queried_ids: tuple[GridId, ...]
    excluded_missing_ids: tuple[GridId, ...]
    excluded_unqueried_ids: tuple[GridId, ...]
    target_location_count: int
    total_target_traffic_mbps: float
    unserved_traffic_mbps: float
    assignments: tuple[BackupAssignment, ...]
    backup_loads: tuple[BackupLoad, ...]
    baseline_kpis: tuple[BaselineKPI, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class Inspection:
    """Rows of one coverage observation that the model asked to see (the drill-down)."""

    step_index: int
    observation_id: ObservationId
    area_id: AreaId
    first_row: int
    total_rows: int
    records: tuple[CoverageRecord, ...]


NoteKind = Literal["parse_failure", "rejected", "concern", "unmet", "query_failed"]


@dataclass(frozen=True)
class Note:
    """Feedback written into State as a fact, so the next context can show it."""

    kind: NoteKind
    step_index: int
    text: str


@dataclass(frozen=True)
class State:
    id: str
    source: Literal["synthetic"]
    task: Task
    coordinate_system: str
    grid_spacing_m: float
    grid: tuple[GridPoint, ...]
    geography: tuple[GeoObject, ...]
    relations: tuple[SpatialRelation, ...]
    areas: tuple[Area, ...]
    regions: tuple[RegionSummary, ...]
    observations: tuple[ObservationLink, ...]
    evidence: tuple[GridEvidence, ...]
    impact: ImpactAnalysis | None
    unknowns: tuple[str, ...]
    kpis: tuple[KPIRecord, ...]
    notes: tuple[Note, ...]
    # Every cell id that a valid record in the evidence lists, sorted; the down cell included.
    cells_seen: tuple[CellId, ...]
    inspection: Inspection | None


# Registry contracts.

Phase = Literal["initialization", "coverage", "backup"]
ActionPhase = Phase | Literal["any"]
RunsOn = Literal["server", "program"]
ParameterKind = Literal["area_id", "cell_id", "observation_id", "float", "int", "str"]
Precondition = Literal[
    "none", "queried_d0_present", "kpi_present_for_candidates", "observation_present"
]
Cost = Literal["zero", "locations_in_areas"]
ResultKind = Literal[
    "cell_metadata",
    "geography",
    "coverage_rows",
    "kpi_rows",
    "impact",
    "observation_rows",
    "none",
]


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    kind: ParameterKind
    unit: str | None
    set_valued: bool
    max_members: int
    allowed_values: Literal[
        "areas_in_state", "cells_in_state", "observations_in_state", "task_epoch", "any"
    ]
    # The only values a string parameter may take, for example the coverage epoch.
    choices: tuple[str, ...] | None


@dataclass(frozen=True)
class ActionSpec:
    name: str
    description: str
    runs_on: RunsOn
    phase: ActionPhase
    parameters: tuple[ParameterSpec, ...]
    precondition: Precondition
    cost: Cost
    result: ResultKind


# The text the context builder renders and the model receives.


@dataclass(frozen=True)
class Rendered:
    # Stable during a run: skill, task, geography, relations, areas, action list.
    prefix: str
    # Rendered again every round from the current State.
    variable: str

    @property
    def text(self) -> str:
        return self.prefix + "\n\n" + self.variable


# Decision contracts.

ParameterValue = str | float | int | tuple[str, ...]


@dataclass(frozen=True)
class Gap:
    # Area ids or cell ids the question is about; may be empty.
    targets: tuple[str, ...]
    question: str


@dataclass(frozen=True)
class Decision:
    action: str
    # As parsed from JSON; validation turns them into typed values.
    parameters: dict[str, object]
    gap: Gap
    raw_text: str


@dataclass(frozen=True)
class ParseFailure:
    reason: str


ValidationKind = Literal[
    "unknown_action",
    "bad_parameter",
    "precondition_unmet",
    "budget_exceeded",
    "gap_contradicted",
    "action_cannot_answer_gap",
]


@dataclass(frozen=True)
class Rejection:
    kind: ValidationKind
    # Written for the model: names the wrong thing and the right things.
    message: str


@dataclass(frozen=True)
class Accepted:
    action: ActionSpec
    # Typed values: id sets as sorted tuples, numbers as float.
    parameters: dict[str, ParameterValue]
    gap: Gap


@dataclass(frozen=True)
class Review:
    """The verifier's answer: is the decision's gap a sensible next question?"""

    outcome: Literal["agree", "concern"]
    reason: str


@dataclass(frozen=True)
class UnreadableReview:
    """A verifier reply that does not follow the two-line format. The action still runs."""

    reply: str
    problem: str


# Observation contracts.

ObservationStatus = Literal["ok", "empty", "missing", "error", "timeout"]


@dataclass(frozen=True)
class Member:
    """One member of a set-valued call: one area or one cell."""

    member_id: str
    status: ObservationStatus
    result_status: Literal["complete", "partial_missing", "all_missing"] | None
    records_path: str | None


@dataclass(frozen=True)
class KPIRows:
    """The parsed rows of one kpi.query member: one row per indicator."""

    records: tuple[KPIRecord, ...]


@dataclass(frozen=True)
class MemberError:
    """The content of a member's records file when the tool returned an error."""

    error: str


@dataclass(frozen=True)
class Observation:
    id: ObservationId
    action: str
    parameters: dict[str, ParameterValue]
    status: ObservationStatus
    members: tuple[Member, ...]
    duration_ms: int
    recorded_at: str
    data_version: str


# Run control contracts.


@dataclass(frozen=True)
class Counters:
    step: int
    retries: int
    rejections: int
    queried_locations: int
    elapsed_s: float


EndReason = Literal[
    "complete",
    "step_cap",
    "query_budget",
    "time_cap",
    "retry_cap",
    "rejection_cap",
    "repeated_query",
]


@dataclass(frozen=True)
class RunConfig:
    # None: take the data version from the tool declarations.
    data_version: str | None
    step_cap: int = 20
    query_budget_locations: int = 1600
    time_cap_s: float = 1800.0
    retry_cap: int = 3
    rejection_cap: int = 5
    repeated_query_threshold: int = 2
    query_timeout_s: float = 30.0
    boundary_d0_max_share: float = 0.0
    include_recent_steps: bool = False
    recent_steps: int = 3
    # Most rows one inspect_observation call returns.
    inspect_max_rows: int = 50
    init_radius_m: float = 4000.0
    # Spacing of the analysis grid that initialization lays over the study area.
    grid_spacing_m: float = 100.0
    write_maps: bool = False


ExecutionSource = Literal["llm", "scripted_model", "resume"]


@dataclass(frozen=True)
class Step:
    """One round: the decision, its validation, what ran, and the full State after it.

    With the State, counters, versions and query cache a Step is a checkpoint.
    """

    id: StepId
    index: int
    execution_source: ExecutionSource
    state_before: State
    # Path to the exact text sent to the model: the prefix, a blank line, the variable part.
    context: str
    raw_output: str
    decision: Decision | None
    validation: Literal["accepted", "rejected", "parse_failure"]
    validation_message: str | None
    review: Literal["agree", "concern", "not_run"]
    # The verifier's reason; for not_run on an accepted decision, its unreadable reply.
    review_reason: str | None
    # The wrapper of what ran; the parsed rows stay in their member files.
    observation: Observation | None
    state_after: State
    context_after: str
    # One line for the recent-steps section of later contexts.
    outcome: str
    counters: Counters
    data_version: str
    query_cache: tuple[ObservationId, ...]
    registry_version: str
    visualization: str | None


@dataclass(frozen=True)
class StepDigest:
    """What later rounds read about an earlier Step: no State, no paths."""

    index: int
    decision: Decision | None
    validation: Literal["accepted", "rejected", "parse_failure"]
    outcome: str

    @staticmethod
    def of(step: Step) -> "StepDigest":
        return StepDigest(step.index, step.decision, step.validation, step.outcome)


@dataclass(frozen=True)
class Trace:
    run_id: str
    config: RunConfig
    initial_state: str
    prefix: str
    # Step files, in order; each holds its full State.
    steps: tuple[str, ...]
    end_reason: EndReason


@dataclass(frozen=True)
class RunRecord:
    """The content of run.json."""

    run_id: str
    config: RunConfig
    decision_model: str
    verifier_model: str
    end_reason: EndReason
    counters: Counters
    last_step: str | None
    started_at: str
    ended_at: str
    resumed_from: str | None


@dataclass(frozen=True)
class RunResult:
    run_id: str
    end_reason: EndReason
    counters: Counters
    trace: str
