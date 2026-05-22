from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import pandas as pd


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    state: str
    label: str
    qualifies_bull: bool
    qualifies_bear: bool
    detail: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class Rule(Protocol):
    rule_id: str

    def __call__(self, df: "pd.DataFrame", i: int) -> RuleResult: ...
