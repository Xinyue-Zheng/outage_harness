"""The verifier node's model: is the decision's gap a sensible next question?

It reads the same rendered State as the deciding model, plus the accepted
decision, and answers agree, or concern with a reason. It is advisory: a
concern becomes a Note in State and the action still runs. It never rejects
and never ends a run. A reply that does not follow the two-line format is kept
as an unreadable review: the Step records it, and the action still runs.
"""

import json
from typing import Protocol

from outage_poc.model import ChatEndpoint, chat
from outage_poc.models import Accepted, Rendered, Review, UnreadableReview

INSTRUCTIONS = """You review one proposed step of an outage impact investigation.

A deciding model read the investigation State shown to you and proposed an
action, its parameters and an information gap: the question the action is meant
to answer. The program has already checked that the action exists, that the
parameters are valid, and that the gap agrees with the State.

Answer one question: is this gap a sensible next question to ask now, given what
the State already shows?

Answer concern only for a specific reason that the State supports. For example:
the State already answers the question; the decision ignores a Feedback line;
the action spends query budget where the State gives no sign of the down cell
while an area next to observed down-cell coverage is still unqueried; or the
investigation tries to finish while the State shows open questions. Otherwise
answer agree. Judge the question, not the result it has not produced yet:
impact.estimate is itself the computation of backup selection, traffic transfer
and load, so "impact has not been computed" is not a reason against it. For a
finish, judge whether the reason for each area left unqueried is supported by
the State: an area whose unqueried locations border no queried down-cell
location may be left unqueried; one that does border such a location may not.

Reply with exactly two lines and nothing else. The first line starts with
"outcome: " followed by agree or concern; the second starts with "reason: ".
Example of a reply:
outcome: concern
reason: The State already shows all 36 locations of S1 queried with valid data."""


class VerifierAdapter(Protocol):
    @property
    def name(self) -> str: ...

    def review(
        self, decision: Accepted, rendered: Rendered
    ) -> Review | UnreadableReview: ...


def decision_text(decision: Accepted) -> str:
    parameters = {
        name: list(value) if isinstance(value, tuple) else value
        for name, value in decision.parameters.items()
    }
    gap = {"targets": list(decision.gap.targets), "question": decision.gap.question}
    return (
        f"action: {decision.action.name}\n"
        f"parameters: {json.dumps(parameters, sort_keys=True)}\n"
        f"gap: {json.dumps(gap)}"
    )


def parse_review(raw: str) -> Review | UnreadableReview:
    """Exactly two lines, `outcome:` then `reason:`. No repair: anything else is unreadable."""
    lines = [line.strip() for line in raw.strip().splitlines() if line.strip()]
    if len(lines) != 2:
        return UnreadableReview(raw, f"the reply has {len(lines)} lines, not 2")
    if not lines[0].startswith("outcome:") or not lines[1].startswith("reason:"):
        return UnreadableReview(raw, "the lines do not start with outcome: and reason:")
    outcome = lines[0].removeprefix("outcome:").strip()
    reason = lines[1].removeprefix("reason:").strip()
    if not reason:
        return UnreadableReview(raw, "the reason is empty")
    match outcome:
        case "agree" | "concern":
            return Review(outcome, reason)
        case _:
            return UnreadableReview(raw, f"outcome {outcome!r} is not agree or concern")


class ChatVerifier:
    """The verifier model, called on every decision that passed the program checks."""

    def __init__(self, endpoint: ChatEndpoint) -> None:
        self._endpoint = endpoint

    @property
    def name(self) -> str:
        return self._endpoint.describe()

    def review(
        self, decision: Accepted, rendered: Rendered
    ) -> Review | UnreadableReview:
        user = (
            "The investigation State, exactly as the deciding model read it:\n"
            "<<<\n"
            f"{rendered.text}\n"
            ">>>\n\n"
            f"The proposed decision:\n{decision_text(decision)}\n\n"
            "Is this gap a sensible next question to ask now? Reply with exactly "
            "two lines in this form:\noutcome: <agree or concern>\n"
            "reason: <one sentence>"
        )
        return parse_review(chat(self._endpoint, INSTRUCTIONS, user))
