"""Comparison cells preserve reported context; reference checks are not entailment."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    version_ids: list[str] = Field(min_length=2, max_length=4)
    fields: list[str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def check_selection(self) -> "ComparisonRequest":
        self.question = self.question.strip()
        self.fields = [field.strip() for field in self.fields]
        if not self.question or any(not f or len(f) > 100 for f in self.fields):
            raise ValueError("Provide a question and field names of 1–100 characters")
        if len(set(self.version_ids)) != len(self.version_ids):
            raise ValueError("Select distinct document versions")
        if len({f.casefold() for f in self.fields}) != len(self.fields):
            raise ValueError("Comparison fields must be distinct")
        return self


class Cell(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: str
    field: str
    status: Literal["reported", "missing", "conflicting"]
    value: str | None = Field(default=None, max_length=2000)
    unit: str | None = Field(default=None, max_length=200)
    currency: str | None = Field(default=None, max_length=100)
    period: str | None = Field(default=None, max_length=300)
    scope: str | None = Field(default=None, max_length=500)
    citations: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def check_support(self) -> "Cell":
        if self.status == "missing":
            if any(
                (
                    self.value,
                    self.unit,
                    self.currency,
                    self.period,
                    self.scope,
                    self.citations,
                )
            ):
                raise ValueError("Missing cells cannot assert factual content")
        elif not self.value or not self.value.strip() or not self.citations:
            raise ValueError("Every factual cell requires a value and citations")
        if self.status == "conflicting" and len(set(self.citations)) < 2:
            raise ValueError("A conflicting cell needs two source references")
        return self


class ComparisonTable(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cells: list[Cell] = Field(max_length=32)


def validate_table(
    raw: Any, request: ComparisonRequest, sources: list[dict[str, Any]]
) -> ComparisonTable:
    table = ComparisonTable.model_validate(raw)
    expected = {(v, f) for v in request.version_ids for f in request.fields}
    seen = [(c.version_id, c.field) for c in table.cells]
    if set(seen) != expected or len(seen) != len(expected):
        raise ValueError(
            "Comparison must contain exactly one cell per version and field"
        )
    references = {s["evidence_id"]: s for s in sources}
    for cell in table.cells:
        if any(
            c not in references or references[c]["version_id"] != cell.version_id
            for c in cell.citations
        ):
            raise ValueError("Cell cites unknown evidence or another document version")
    return table
