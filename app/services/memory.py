from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.schemas import PromotionAnalysisRequest


@dataclass
class AnalysisMemory:
    request: PromotionAnalysisRequest
    data_inventory: dict[str, dict[str, str]]
    findings: dict[str, dict[str, Any]] = field(default_factory=dict)
    narrative: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    plan: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: {"done": [], "pending": []})
    decision: dict[str, Any] = field(default_factory=dict)

    def record_finding(
        self,
        capability: str,
        *,
        result: dict[str, Any],
        confidence: float,
        summary: str,
        flags_for_downstream: list[str] | None = None,
        narrative_line: str | None = None,
        open_questions: list[str] | None = None,
    ) -> None:
        self.findings[capability] = {
            "result": result,
            "confidence": confidence,
            "summary": summary,
            "flags_for_downstream": flags_for_downstream or [],
        }
        if narrative_line:
            self.narrative.append(narrative_line)
        if open_questions:
            self.open_questions.extend(open_questions)

    def mark_done(self, capability: str, reason: str) -> None:
        self.plan["done"].append({"capability": capability, "reason": reason})
        self.plan["pending"] = [item for item in self.plan["pending"] if item.get("capability") != capability]

    def queue_pending(self, capability: str, reason: str) -> None:
        if capability not in {item.get("capability") for item in self.plan["pending"]}:
            self.plan["pending"].append({"capability": capability, "reason": reason})

    def render_for_llm(self) -> str:
        """Render blackboard findings as structured Markdown for LLM prompts.
        Much easier for a text model to reason over than a raw Python dict dump."""
        if not self.findings:
            return "(no findings yet)"
        lines: list[str] = []
        for name, finding in self.findings.items():
            heading = name.replace("_", " ").title()
            lines.append(f"## {heading}  (confidence {finding['confidence']:.2f})")
            lines.append(finding.get("summary", ""))
            result = finding.get("result", {})
            key_metrics = {
                k: v for k, v in result.items()
                if isinstance(v, (int, float, str, bool)) and not k.startswith("_")
            }
            if key_metrics:
                for k, v in key_metrics.items():
                    label = k.replace("_", " ")
                    value = f"{v:.2f}" if isinstance(v, float) else str(v)
                    lines.append(f"- {label}: {value}")
            flags = finding.get("flags_for_downstream", [])
            if flags:
                lines.append(f"- flags: {', '.join(flags)}")
            lines.append("")
        if self.open_questions:
            lines.append("## Open Questions")
            for q in self.open_questions:
                if q:
                    lines.append(f"- {q}")
            lines.append("")
        return "\n".join(lines).strip()
