"""Shared fixtures: the synthetic case, script paths, and test doubles for the
verifier node."""

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from outage_poc.data_client import LocalClient, ToolDeclaration
from outage_poc.data_tools import synthetic_tools
from outage_poc.init import build_initial_state, resolve_area
from outage_poc.models import (
    Accepted,
    CellId,
    CoverageObservation,
    Dataset,
    GeoObject,
    ObservationId,
    Rendered,
    Review,
    RunConfig,
    State,
    Task,
    UnreadableReview,
)
from outage_poc.registry import Registry, build_registry
from outage_poc.state import apply_coverage
from outage_poc.synthetic import build_dataset, query_coverage

TESTS = Path(__file__).parent
SCRIPTS = TESTS / "scripts"
FIXTURES = TESTS / "fixtures" / "recorded"
# The land-use areas added to the prototype's eleven areas.
NEW_AREAS = ("F3", "F4", "F5", "F6", "F7", "F8", "W1")

DATASET = build_dataset()
SITE_TASK = Task(
    CellId("D0"),
    DATASET.task.outage_time,
    DATASET.task.objective,
    1000.0,
    1300.0,
    "pre_outage",
)


def geography(dataset: Dataset) -> tuple[GeoObject, ...]:
    return tuple(item for item in dataset.geography if item.kind != "cell")


def initial_state(dataset: Dataset = DATASET) -> State:
    """State 0 as initialization builds it, from the geography osm.geometry returns."""
    return build_initial_state(SITE_TASK, geography(dataset), dataset.grid_spacing_m)


def client(dataset: Dataset = DATASET) -> LocalClient:
    """The synthetic tool library as the loop's data client."""
    return LocalClient(synthetic_tools(dataset))


def tool_declarations(dataset: Dataset = DATASET) -> tuple[ToolDeclaration, ...]:
    return client(dataset).list_tools()


def registry() -> Registry:
    return build_registry(tool_declarations())


def config(**changes: object) -> RunConfig:
    return replace(RunConfig(data_version=None), **changes)


def query(
    dataset: Dataset,
    state: State,
    area_id: str,
    observation_id: str,
    observations: dict[ObservationId, CoverageObservation],
) -> State:
    """One coverage query applied in process, as the loop would apply one member."""
    observation = query_coverage(
        dataset,
        resolve_area(state.grid, state.areas, area_id),
        ObservationId(observation_id),
    )
    observations[observation.id] = observation
    return apply_coverage(
        state,
        ((observation, f"observations/{observation.id}.json"),),
        f"state_{observation_id}",
        observations,
    )


class AlwaysAgree:
    """A verifier double that agrees with every decision."""

    @property
    def name(self) -> str:
        return "test verifier: always agree"

    def review(
        self, decision: Accepted, rendered: Rendered
    ) -> Review | UnreadableReview:
        return Review("agree", "test verifier")


class ScriptedVerifier:
    """A verifier double that replays reviews in order; raises when exhausted."""

    def __init__(self, reviews: Sequence[Review | UnreadableReview]) -> None:
        self._reviews = tuple(reviews)
        self._next = 0

    @property
    def name(self) -> str:
        return "test verifier: scripted"

    def review(
        self, decision: Accepted, rendered: Rendered
    ) -> Review | UnreadableReview:
        if self._next >= len(self._reviews):
            raise RuntimeError(f"No scripted review for decision {self._next + 1}")
        review = self._reviews[self._next]
        self._next += 1
        return review
