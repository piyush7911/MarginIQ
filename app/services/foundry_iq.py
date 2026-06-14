from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from app.core.config import (
    FOUNDRY_IQ_API_KEY,
    FOUNDRY_IQ_API_VERSION,
    FOUNDRY_IQ_ENDPOINT,
    FOUNDRY_IQ_INDEX,
    FOUNDRY_IQ_KNOWLEDGE_SOURCE,
)


@dataclass
class PolicyPassage:
    """A retrieved policy passage with its source citation."""

    document: str
    heading: str
    text: str

    def cite(self) -> str:
        return f"[{self.document} → {self.heading}]"


class FoundryIQService:
    """Grounded policy retrieval via Foundry IQ (Azure AI Search agentic retrieval).

    Foundry IQ knowledge bases are backed by Azure AI Search. Retrieval uses the
    Search service's knowledge-base `retrieve` action:
        POST {search-endpoint}/knowledgebases/{kb}/retrieve?api-version=...
    See https://learn.microsoft.com/azure/search/agentic-retrieval-how-to-retrieve

    Foundry IQ is required. There is no local fallback — the critic is grounded
    exclusively on the hosted knowledge base.
    """

    source = "Foundry IQ"

    def __init__(self) -> None:
        if not (FOUNDRY_IQ_ENDPOINT and FOUNDRY_IQ_API_KEY):
            raise RuntimeError(
                "Foundry IQ is not configured. Set FOUNDRY_IQ_ENDPOINT (Azure AI Search "
                "service URL) and FOUNDRY_IQ_API_KEY (Azure AI Search key)."
            )

    async def retrieve_policy_context(self, query: str, top_k: int = 3) -> str:
        """Return a Markdown block of cited policy passages relevant to the query."""
        passages = await self._retrieve_from_foundry(query, top_k)
        return self._format(passages)

    async def _retrieve_from_foundry(self, query: str, top_k: int) -> list[PolicyPassage]:
        # Azure AI Search agentic retrieval: knowledge-base retrieve action.
        url = (
            f"{FOUNDRY_IQ_ENDPOINT}/knowledgebases/{FOUNDRY_IQ_INDEX}/retrieve"
            f"?api-version={FOUNDRY_IQ_API_VERSION}"
        )
        headers = {"api-key": FOUNDRY_IQ_API_KEY, "Content-Type": "application/json"}
        # Use `intents` input: it is supported at every reasoning-effort level
        # (the `messages` input only works at low/medium effort, and our knowledge
        # base defaults to minimal/extractive retrieval).
        body: dict = {
            "intents": [{"type": "semantic", "search": query}]
        }
        if FOUNDRY_IQ_KNOWLEDGE_SOURCE:
            body["knowledgeSourceParams"] = [
                {
                    "knowledgeSourceName": FOUNDRY_IQ_KNOWLEDGE_SOURCE,
                    "kind": "searchIndex",
                    "includeReferences": True,
                }
            ]
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
        return self._parse_foundry_response(data, top_k)

    def _parse_foundry_response(self, data: dict, top_k: int) -> list[PolicyPassage]:
        """The retrieve response packs grounding chunks as a JSON-encoded string at
        response[].content[].text — an array of {ref_id, content, ...}."""
        passages: list[PolicyPassage] = []
        for message in data.get("response", []):
            for part in message.get("content", []):
                if part.get("type") != "text":
                    continue
                raw = part.get("text", "")
                try:
                    chunks = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    if raw.strip():
                        passages.append(PolicyPassage("Foundry IQ", "Policy", raw.strip()))
                    continue
                for chunk in chunks:
                    if not isinstance(chunk, dict):
                        continue
                    content = str(chunk.get("content", "")).strip()
                    document = str(chunk.get("title") or chunk.get("docKey") or "")
                    if not document:
                        # Hosted chunks carry only ref_id + content; derive a label
                        # from the first Markdown heading in the content.
                        document = _first_heading(content) or "Foundry IQ knowledge base"
                    passages.append(
                        PolicyPassage(
                            document=document,
                            heading=f"ref {chunk.get('ref_id', '?')}",
                            text=content,
                        )
                    )
        return [p for p in passages if p.text][:top_k]

    def _format(self, passages: list[PolicyPassage]) -> str:
        if not passages:
            return "(no grounded policy found via Foundry IQ)"
        lines = ["Grounded policy (retrieved via Foundry IQ):", ""]
        for p in passages:
            lines.append(p.cite())
            lines.append(p.text)
            lines.append("")
        return "\n".join(lines).strip()


def _first_heading(content: str) -> str:
    """Pull the first Markdown heading from a content chunk, for use as a citation
    label when the hosted response carries no document title."""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""
