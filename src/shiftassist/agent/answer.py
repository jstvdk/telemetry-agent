"""The structured final answer (ADR-0005) and the tool that submits it.

The agent must end by calling ``submit_answer``. Every claim cites what it rests on:
  EV-000017                        a detector event
  RB-005                           a runbook entry
  journal:4407 / log/<file>:<n>    a raw journal or log line (as returned by the tools)
  telemetry:<subsystem>/<entity>/<channel>@<start>/<end>
                                   a monitoring window; the validator recomputes its features
                                   (entity '-' when there is none)
Numbers the claim states go in ``values`` so the validator can check them against the citations.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

Status = Literal["answered", "insufficient_data", "not_in_runbook", "out_of_scope"]


class Claim(BaseModel):
    text: str = Field(description="One factual statement, in plain words.")
    citations: list[str] = Field(
        description="IDs this claim rests on: EV-…, RB-…, journal:/log/ refs, or telemetry:…"
    )
    values: dict[str, float] = Field(
        default_factory=dict,
        description="Numbers stated in the claim, by name (e.g. {'slope_per_h': 1.5}).",
    )


class Answer(BaseModel):
    status: Annotated[
        Status,
        Field(
            description=(
                "answered; insufficient_data (the snapshot cannot tell); not_in_runbook "
                "(explained, but no runbook entry covers it: escalate); out_of_scope"
            )
        ),
    ]
    answer: str = Field(description="The answer for the operator, 2-6 sentences.")
    claims: list[Claim] = Field(description="Every factual statement of the answer, cited.")
    runbook_entry: str | None = Field(
        default=None, description="The runbook entry that applies (RB-…), or null if none does."
    )
    recommended_checks: list[str] = Field(
        default_factory=list,
        description="What the operator should check or do next, taken from the runbook entry.",
    )


SUBMIT_NAME = "submit_answer"
SUBMIT_DESCRIPTION = (
    "End the investigation with a structured, cited answer. Call exactly once, when done. "
    "Every factual statement must be a claim with citations; state numbers in `values`. "
    "Cite only IDs that tools returned. Set runbook_entry only to an entry you read; if no entry "
    "covers the situation, use status not_in_runbook and recommend escalation."
)


def submit_schema() -> dict[str, Any]:
    s = Answer.model_json_schema()
    s.pop("title", None)
    return s
