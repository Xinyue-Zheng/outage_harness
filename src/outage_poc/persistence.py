"""Plain JSON output and explicit decoding of the recorded contracts."""

import json
import types
from dataclasses import asdict, fields, is_dataclass
from math import isfinite
from pathlib import Path
from typing import (
    Literal,
    NewType,
    TypeAliasType,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from outage_poc.models import (
    CoverageObservation,
    Dataset,
    Geometry,
    ImpactAnalysis,
    Inspection,
    KPIRecord,
    KPIRows,
    MemberError,
    Observation,
    ObservationId,
    RunRecord,
    State,
    Step,
    Trace,
)

type Artifact = (
    Dataset
    | State
    | Step
    | Trace
    | RunRecord
    | Observation
    | CoverageObservation
    | ImpactAnalysis
    | KPIRecord
    | KPIRows
    | Inspection
    | MemberError
)


def write_json(path: Path, artifact: Artifact) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(artifact), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    mapping = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in mapping):
        raise ValueError("Expected string object keys")
    return cast(dict[str, object], mapping)


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Expected a JSON array")
    return cast(list[object], value)


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected a JSON string")
    return value


def _number(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
    ):
        raise ValueError("Expected a finite JSON number")
    return float(value)


def _field(mapping: dict[str, object], name: str) -> object:
    if name not in mapping:
        raise ValueError(f"Missing required field {name!r}")
    return mapping[name]


def _geometry(value: object) -> Geometry:
    mapping = _object(value)
    kind = _string(_field(mapping, "kind"))
    if kind not in ("polygon", "polyline", "buffer"):
        raise ValueError(f"Unsupported geometry kind {kind!r}")
    coordinates: list[tuple[float, float]] = []
    for raw_pair in _array(_field(mapping, "coordinates")):
        pair = _array(raw_pair)
        if len(pair) != 2:
            raise ValueError("Coordinates must be x/y pairs")
        coordinates.append((_number(pair[0]), _number(pair[1])))
    raw_width = _field(mapping, "buffer_width_m")
    return Geometry(
        kind,
        tuple(coordinates),
        None if raw_width is None else _number(raw_width),
    )


def read_observation(path: Path) -> CoverageObservation:
    return read_json(CoverageObservation, path)


def load_observations(
    state: State, output_root: Path
) -> dict[ObservationId, CoverageObservation]:
    """Find the raw query records by following a state's persisted provenance links."""
    observations: dict[ObservationId, CoverageObservation] = {}
    for link in state.observations:
        relative_path = Path(link.path)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(
                "Observation links must be relative to the output directory"
            )
        observation = read_observation(output_root / relative_path)
        if observation.id != link.observation_id:
            raise ValueError("Observation ID does not match state link")
        observations[observation.id] = observation
    return observations


def _decode(hint: object, value: object, where: str) -> object:
    """Decode JSON into the type a dataclass field declares, or raise naming the field."""
    if isinstance(hint, TypeAliasType):
        return _decode(hint.__value__, value, where)
    if isinstance(hint, NewType):
        return _decode(hint.__supertype__, value, where)
    if hint is object:
        return value
    if hint is type(None):
        if value is not None:
            raise ValueError(f"{where}: expected null")
        return None
    if hint is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{where}: expected a boolean")
        return value
    if hint is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{where}: expected an integer")
        return value
    if hint is float:
        return _number(value)
    if hint is str:
        if not isinstance(value, str):
            raise ValueError(f"{where}: expected a string")
        return value
    origin = get_origin(hint)
    arguments = get_args(hint)
    if origin is Literal:
        if value not in arguments:
            raise ValueError(f"{where}: {value!r} is not one of {arguments}")
        return value
    if origin is Union or origin is types.UnionType:
        errors: list[str] = []
        for option in arguments:
            try:
                return _decode(option, value, where)
            except ValueError as error:
                errors.append(str(error))
        raise ValueError(f"{where}: matches no option of {hint}: {errors}")
    if origin is tuple:
        items = _array(value)
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            return tuple(
                _decode(arguments[0], item, f"{where}[{index}]")
                for index, item in enumerate(items)
            )
        if len(items) != len(arguments):
            raise ValueError(f"{where}: expected {len(arguments)} items")
        return tuple(
            _decode(argument, item, f"{where}[{index}]")
            for index, (argument, item) in enumerate(zip(arguments, items, strict=True))
        )
    if origin is dict:
        if arguments[0] is not str:
            raise ValueError(f"{where}: only string-keyed objects are supported")
        return {
            key: _decode(arguments[1], item, f"{where}.{key}")
            for key, item in _object(value).items()
        }
    if isinstance(hint, type) and is_dataclass(hint):
        mapping = _object(value)
        hints = get_type_hints(hint)
        names = [item.name for item in fields(hint)]
        if set(mapping) != set(names):
            raise ValueError(
                f"{where}: {hint.__name__} keys {sorted(mapping)} != {sorted(names)}"
            )
        return hint(
            **{
                name: _decode(hints[name], mapping[name], f"{where}.{name}")
                for name in names
            }
        )
    raise ValueError(f"{where}: unsupported type {hint!r}")


def decode[T](kind: type[T], value: object) -> T:
    """Decode a JSON value written by write_json back into its frozen dataclass."""
    return cast(T, _decode(kind, value, kind.__name__))


def read_json[T](kind: type[T], path: Path) -> T:
    return decode(kind, json.loads(path.read_text(encoding="utf-8")))


def read_state(path: Path) -> State:
    return read_json(State, path)


def read_step(path: Path) -> Step:
    return read_json(Step, path)


_CHECKPOINT_FORMAT = "tagged-json-zlib"
