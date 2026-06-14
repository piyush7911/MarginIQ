"""Accuracy harness. Runs MarginIQ on Azure (gpt-4o + Foundry IQ) across the six demo
scenarios — each a transform of the seed with a KNOWN correct direction — and scores
the system's recommendation against expectation. Writes results/scenario_results.json.

Run:  python tests/scenario_accuracy.py
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.promotion_manager import PromotionManager
from app.services.scenarios import SCENARIOS


# ---- metric extractors -------------------------------------------------------

def _agent_metric(resp, agent: str, key: str, default: float = 0.0) -> float:
    for a in resp.agent_insights:
        if a.agent == agent:
            return float(a.metrics.get(key, default))
    return default


def _heat(resp):
    return _agent_metric(resp, "CompetitorIntelligenceAgent", "market_heat")


def _weather_index(resp):
    return _agent_metric(resp, "WeatherImpactAgent", "weather_index")


def _timing_score(resp):
    return _agent_metric(resp, "TimingAgent", "timing_score", 1.0)


def _clearance_pressure(resp):
    return _agent_metric(resp, "InventoryRiskAgent", "clearance_pressure")


def _margin_violation(resp):
    for a in resp.agent_insights:
        if a.agent == "ProfitabilityAgent" and a.metrics.get("min_margin_ok") is False:
            return True
    return resp.optimization.recommended_discount <= 5


# ---- per-scenario pass/fail checks (keyed to the shared scenario module) ------

CHECKS = {
    "s1": lambda r: 5 <= r.optimization.recommended_discount <= 15,
    "s2": lambda r: r.optimization.recommended_discount >= 25 and _clearance_pressure(r) > 0.1,
    "s3": lambda r: r.optimization.recommended_discount <= 10 and r.metrics.inventory_risk == "high",
    "s4": lambda r: _heat(r) >= 0.7,
    "s5": lambda r: _weather_index(r) <= 0.1 and _timing_score(r) <= 0.35,
    "s6": lambda r: r.optimization.recommended_discount <= 10 and _margin_violation(r),
}


async def run() -> list[dict]:
    pm = PromotionManager()
    rows: list[dict] = []
    for key, scenario in SCENARIOS.items():
        resp = await pm.analyze(scenario.build_request())
        ok = bool(CHECKS[key](resp))
        rows.append(
            {
                "key": key,
                "title": scenario.title,
                "expectation": scenario.expectation,
                "recommended_discount": resp.optimization.recommended_discount,
                "decided_by": resp.optimization.decided_by,
                "expected_profit": round(resp.optimization.expected_profit, 2),
                "downside_risk": round(resp.optimization.downside_risk, 4),
                "inventory_risk": resp.metrics.inventory_risk,
                "competitor_heat": round(_heat(resp), 3),
                "weather_index": round(_weather_index(resp), 3),
                "timing_score": round(_timing_score(resp), 3),
                "clearance_pressure": round(_clearance_pressure(resp), 3),
                "grounding_source": resp.verification.grounding_source,
                "confidence": resp.confidence,
                "decision_factors": resp.optimization.decision_factors,
                "recommendation": resp.recommendation,
                "passed": ok,
            }
        )
    return rows


def main() -> None:
    rows = asyncio.run(run())
    passed = sum(r["passed"] for r in rows)

    print("\n" + "=" * 104)
    print(f"{'SCENARIO':<40} {'rec%':>4} {'decided_by':>16} {'invRisk':>7} {'heat':>5} {'grounding':>12} {'result':>6}")
    print("-" * 104)
    for r in rows:
        print(f"{r['title']:<40} {r['recommended_discount']:>4} {r['decided_by']:>16} "
              f"{r['inventory_risk']:>7} {r['competitor_heat']:>5.2f} {r['grounding_source']:>12} "
              f"{'PASS' if r['passed'] else 'FAIL':>6}")
    print("-" * 104)
    print(f"MarginIQ accuracy: {passed}/{len(rows)} scenarios matched expectation\n")

    out_dir = ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "scenario_results.json"
    out_path.write_text(json.dumps({"passed": passed, "total": len(rows), "scenarios": rows}, indent=2))
    print(f"Saved detailed results -> {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
