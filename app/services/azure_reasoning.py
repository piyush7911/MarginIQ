from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import (
    AZURE_AI_API_KEY,
    AZURE_AI_API_VERSION,
    AZURE_AI_MAX_RETRIES,
    AZURE_AI_MODEL_DEPLOYMENT,
    AZURE_AI_PROJECT_ENDPOINT,
    AZURE_AI_TIMEOUT_SECONDS,
)


class AzureReasoningService:
    """Structured-output reasoning client backed by Azure AI Foundry (gpt-4o).

    Azure is required. There is no alternate provider and no deterministic
    fallback — every reasoning stage runs on Azure AI Foundry.
    """

    def __init__(self) -> None:
        if not (AZURE_AI_PROJECT_ENDPOINT and AZURE_AI_API_KEY):
            raise RuntimeError(
                "Azure AI Foundry is not configured. Set AZURE_AI_PROJECT_ENDPOINT and "
                "AZURE_AI_API_KEY."
            )
        self.model = AZURE_AI_MODEL_DEPLOYMENT
        # Accept either the base resource endpoint
        # (https://<resource>.services.ai.azure.com) or the project endpoint
        # (.../api/projects/<name>); chat completions lives on the base, so strip any
        # /api/projects/... suffix before building the URL.
        base = AZURE_AI_PROJECT_ENDPOINT.split("/api/projects/")[0].rstrip("/")
        self.url = (
            f"{base}/openai/deployments/"
            f"{AZURE_AI_MODEL_DEPLOYMENT}/chat/completions"
            f"?api-version={AZURE_AI_API_VERSION}"
        )
        self.headers = {
            "api-key": AZURE_AI_API_KEY,
            "Content-Type": "application/json",
        }
        self.timeout = AZURE_AI_TIMEOUT_SECONDS
        self.max_retries = max(1, AZURE_AI_MAX_RETRIES)

    async def json_completion(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "marginiq_response",
                    "strict": True,
                    "schema": schema,
                },
            },
        }

        last_error: Exception | None = None
        for _ in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(self.url, headers=self.headers, json=payload)
                    response.raise_for_status()
                    data = response.json()
                content = data["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError("Structured output content was not a string.")
                return json.loads(content)
            except Exception as exc:  # pragma: no cover
                last_error = exc

        raise RuntimeError(f"Azure AI Foundry completion failed: {last_error}")
