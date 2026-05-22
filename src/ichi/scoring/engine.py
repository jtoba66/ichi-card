from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ichi.indicators.helpers import chikou_angle
from ichi.rules.base import RuleResult
from ichi.rules.composites import NoBearSetupRule
from ichi.rules.registry import RuleRegistry


@dataclass
class Scorecard:
    bull_score: int
    bear_score: int
    grade: float
    chikou_angle_val: float
    rules: list[RuleResult]
    sections: dict[str, list[RuleResult]]
    total_scoring_rules: int


def evaluate(df: pd.DataFrame, i: int, registry: RuleRegistry) -> Scorecard:
    """Run all rules at index i and aggregate into a Scorecard.

    NoBearSetupRule is handled after a preliminary bear_score is computed from all other rules,
    to avoid the circular dependency of needing the bear score to compute a rule in the bear score.
    """
    results: list[RuleResult] = []
    no_bear_result: RuleResult | None = None

    # First pass: all rules except NoBearSetupRule
    for rule in registry.all_rules:
        if isinstance(rule, NoBearSetupRule):
            continue
        results.append(rule(df, i))

    # Compute preliminary bear_score from non-NoBearSetup scoring rules
    prelim_bear = sum(
        1 for r in results
        if r.rule_id in registry.scoring_rule_ids and r.qualifies_bear
    )

    # Second pass: NoBearSetupRule with the preliminary bear score
    if registry.no_bear_setup_rule is not None:
        no_bear_result = registry.no_bear_setup_rule(df, i, bear_score=prelim_bear)
        results.append(no_bear_result)

    # Final aggregation
    bull_score = sum(
        1 for r in results if r.rule_id in registry.scoring_rule_ids and r.qualifies_bull
    )
    bear_score = sum(
        1 for r in results if r.rule_id in registry.scoring_rule_ids and r.qualifies_bear
    )
    total = len(registry.scoring_rule_ids)

    # Chikou is visible at i-26 (close.shift(-26) is NaN for the last 26 bars)
    ca_series = df["_chikou_angle"] if "_chikou_angle" in df.columns else chikou_angle(df["chikou"])
    ca_index = max(0, i - 26)
    ca_val = float(ca_series.iat[ca_index]) if not pd.isna(ca_series.iat[ca_index]) else 0.0

    return Scorecard(
        bull_score=bull_score,
        bear_score=bear_score,
        grade=bull_score / total if total > 0 else 0.0,
        chikou_angle_val=ca_val,
        rules=results,
        sections=registry.group_by_section(results),
        total_scoring_rules=total,
    )
