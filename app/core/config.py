import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATABASE_PATH = BASE_DIR / "marginiq.sqlite3"

# Azure AI Foundry (gpt-4o) — the only reasoning backend. Required.
AZURE_AI_PROJECT_ENDPOINT = os.getenv("AZURE_AI_PROJECT_ENDPOINT", "").rstrip("/")
AZURE_AI_API_KEY = os.getenv("AZURE_AI_API_KEY", "")
AZURE_AI_MODEL_DEPLOYMENT = os.getenv("AZURE_AI_MODEL_DEPLOYMENT", "gpt-4o")
AZURE_AI_API_VERSION = os.getenv("AZURE_AI_API_VERSION", "2024-08-01-preview")
AZURE_AI_TIMEOUT_SECONDS = float(os.getenv("AZURE_AI_TIMEOUT_SECONDS", "45"))
AZURE_AI_MAX_RETRIES = int(os.getenv("AZURE_AI_MAX_RETRIES", "2"))

# Foundry IQ — grounded policy retrieval (Azure AI Search agentic retrieval). Required.
# FOUNDRY_IQ_ENDPOINT is the Azure AI Search service URL backing the knowledge base
# (https://<service>.search.windows.net). FOUNDRY_IQ_API_KEY is the AI Search key.
# FOUNDRY_IQ_INDEX is the knowledge base name; FOUNDRY_IQ_KNOWLEDGE_SOURCE is the
# attached knowledge source name (optional — if empty the KB planner queries all sources).
FOUNDRY_IQ_ENDPOINT = os.getenv("FOUNDRY_IQ_ENDPOINT", "").rstrip("/")
FOUNDRY_IQ_API_KEY = os.getenv("FOUNDRY_IQ_API_KEY", "")
FOUNDRY_IQ_INDEX = os.getenv("FOUNDRY_IQ_INDEX", "marginiq-pricing-policy")
FOUNDRY_IQ_KNOWLEDGE_SOURCE = os.getenv("FOUNDRY_IQ_KNOWLEDGE_SOURCE", "")
FOUNDRY_IQ_API_VERSION = os.getenv("FOUNDRY_IQ_API_VERSION", "2025-11-01-preview")

MAX_ANALYSIS_MEMORY_GB = float(os.getenv("MAX_ANALYSIS_MEMORY_GB", "10"))
