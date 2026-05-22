from __future__ import annotations

from dataclasses import dataclass, field

from ichi.rules.base import Rule, RuleResult
from ichi.rules.composites import (
    CSClearRule,
    KumoTrapRule,
    NoBearSetupRule,
    PerfectSetupRule,
    SanyakuRule,
    SSBDirectionRule,
)
from ichi.rules.kumo import CloudCurlingRule, FutureBullRule, FwdThickRule, KumoBullishRule
from ichi.rules.lines import (
    AngleGte20Rule,
    AwayFromSpanBRule,
    BothRisingRule,
    ChikouClearedRule,
    FullBullRule,
    KijunFlatRule,
    KJAlignedRule,
    KJBalancedRule,
    KJNoCurlRule,
    KJRisingRule,
    NoFakeoutRule,
    NoTKCrossRule,
    TKBounceRule,
    TKMagnetRule,
    TKNoCurlRule,
    TKRisingRule,
)
from ichi.rules.trend_position import (
    AboveCloudRule,
    AboveKijunRule,
    AbovePriceRule,
    AngleGte10Rule,
    BullStackRule,
    HighVolumeRule,
    NoDivRule,
    OBVRisingRule,
    TKBullishRule,
    TripleSweepRule,
)


@dataclass
class RuleRegistry:
    all_rules: list[Rule]
    scoring_rule_ids: set[str]
    sections: dict[str, list[str]] = field(default_factory=dict)
    no_bear_setup_rule: NoBearSetupRule | None = None

    @classmethod
    def canonical(cls) -> "RuleRegistry":
        """Full 18-rule registry mirroring the LuxAlgo/Shinobi reference panel."""
        no_bear = NoBearSetupRule()

        # All rules in panel display order
        all_rules: list[Rule] = [
            # Bull Condition · Status
            AboveCloudRule(),
            AbovePriceRule(),
            AngleGte10Rule(),
            TKBullishRule(),
            HighVolumeRule(),
            OBVRisingRule(),
            KumoBullishRule(),
            AboveKijunRule(),
            NoDivRule(),
            TripleSweepRule(),
            TKRisingRule(),
            KJRisingRule(),
            BullStackRule(),
            TKBounceRule(),
            ChikouClearedRule(),
            FullBullRule(),
            NoTKCrossRule(),
            # Kumo Analysis
            FutureBullRule(),
            FwdThickRule(),
            CloudCurlingRule(),
            # Ichi Structure
            KijunFlatRule(),
            AwayFromSpanBRule(),
            AngleGte20Rule(),
            PerfectSetupRule(),
            TKMagnetRule(),
            KJBalancedRule(),
            NoFakeoutRule(),
            KJAlignedRule(),
            # TK/KJ Slope
            TKNoCurlRule(),
            KJNoCurlRule(),
            BothRisingRule(),
            # Sanyaku / CS Traps
            SanyakuRule(),
            KumoTrapRule(),
            CSClearRule(),
            SSBDirectionRule(),
            no_bear,
        ]

        # The canonical 18 that count toward the headline score
        # [default-guess] — 17 from Bull Condition · Status + BothRising as 18th
        scoring_ids = {
            "above_cloud", "above_price", "angle_gte10", "tk_bullish",
            "high_volume", "obv_rising", "kumo_bullish", "above_kijun",
            "no_div", "triple_sweep", "tk_rising", "kj_rising",
            "bull_stack", "tk_bounce", "chikou_cleared", "full_bull",
            "no_tk_cross", "both_rising",
        }

        sections = {
            "Bull Condition · Status": [
                "above_cloud", "above_price", "angle_gte10", "tk_bullish",
                "high_volume", "obv_rising", "kumo_bullish", "above_kijun",
                "no_div", "triple_sweep", "tk_rising", "kj_rising",
                "bull_stack", "tk_bounce", "chikou_cleared", "full_bull", "no_tk_cross",
            ],
            "Kumo Analysis": ["future_bull", "fwd_thick", "cloud_curling"],
            "Ichi Structure": [
                "kijun_flat", "away_from_spanb", "angle_gte20", "perfect_setup",
                "tk_magnet", "kj_balanced", "no_fakeout", "kj_aligned",
            ],
            "TK / KJ Slope": ["tk_rising", "kj_rising", "tk_no_curl", "kj_no_curl", "both_rising"],
            "Sanyaku / CS Traps [v7]": [
                "sanyaku", "kumo_trap", "cs_clear", "ssb_direction",
                "no_tk_cross", "no_bear_setup",
            ],
        }

        return cls(
            all_rules=all_rules,
            scoring_rule_ids=scoring_ids,
            sections=sections,
            no_bear_setup_rule=no_bear,
        )

    def group_by_section(self, results: list[RuleResult]) -> dict[str, list[RuleResult]]:
        result_map = {r.rule_id: r for r in results}
        return {
            section: [result_map[rid] for rid in rule_ids if rid in result_map]
            for section, rule_ids in self.sections.items()
        }
