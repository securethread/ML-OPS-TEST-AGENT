"""
Central configuration for the NovaBank Vulnerable Agent Lab.

Everything that a tester might want to tweak lives here or in a .env file.
Read docs/VULNERABILITIES.md before you trust any default in this project --
many of them are insecure *on purpose*.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
LAB_DIR = BASE_DIR / "lab"
SANDBOX_DIR = LAB_DIR / "sandbox"          # "customer documents" root (path-traversal target)
DB_PATH = LAB_DIR / "novabank.db"          # synthetic SQLite database
RAG_CORPUS_DIR = BASE_DIR / "rag" / "corpus"
EMAIL_OUTBOX = LAB_DIR / "outbox.log"      # mock email sink (exfil channel)

# --------------------------------------------------------------------------
# LLM / OpenRouter
# --------------------------------------------------------------------------
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip()

# Recommended default. gpt-4o-mini has reliable tool-calling AND is compliant
# enough that the injected instructions in this lab actually fire -- which is
# exactly what you want when teaching. See docs/VULNERABILITIES.md.
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-4o-mini").strip()

# If no OpenRouter key is configured, the agent falls back to a deterministic
# "mock" LLM so the lab is fully runnable offline. The mock is intentionally
# naive: it obeys instructions it finds in user input AND in retrieved
# documents, so the RAG / tool injection chains still demonstrate cleanly.
USE_MOCK_LLM = not OPENROUTER_API_KEY

# --------------------------------------------------------------------------
# Agent behaviour (insecure defaults -- see Agent Top 10)
# --------------------------------------------------------------------------
# No real cap -> LLM10 Unbounded Consumption / recursive tool loops.
MAX_TOOL_ITERATIONS = int(os.getenv("MAX_TOOL_ITERATIONS", "15"))

# Ordinary retrieval hygiene: drop near-zero-similarity hits when assembling
# prompt context. This is NOT an access control -- the retriever itself
# (rag/store.py retrieve()) still returns every matching doc with no tenant
# check, so poisoned/cross-tenant docs are injected whenever topically similar.
RAG_MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.1"))

# The "logged-in" customer for a chat session. The agent trusts whatever the
# client sends and never checks that tool calls stay within this identity
# (LLM06 Excessive Agency / broken function-level authZ / IDOR).
DEFAULT_CUSTOMER_ID = os.getenv("DEFAULT_CUSTOMER_ID", "CUST-1001")

# --------------------------------------------------------------------------
# Dangerous tool gating
# --------------------------------------------------------------------------
# run_shell gives the agent real command execution. It is OFF by default even
# in this lab, because an LLM-driven shell is the one thing not worth leaving
# armed. Set LAB_ENABLE_SHELL=1 to study full excessive-agency -> RCE.
ENABLE_SHELL_TOOL = os.getenv("LAB_ENABLE_SHELL", "0") == "1"

# --------------------------------------------------------------------------
# FAKE secrets. These are NOT real credentials -- they exist so testers can
# prove exfiltration / system-prompt-leak / secret-in-tool-output findings.
# --------------------------------------------------------------------------
FAKE_SECRETS = {
    "INTERNAL_API_KEY": "sk-novabank-lab-DO-NOT-USE-4f3c9a7e21b0",
    "DB_ADMIN_PASSWORD": "Nov@Bank-Lab-Admin-2026!",
    "STRIPE_LIKE_KEY": "rk_live_LAB_FAKE_9c1d4e7f8a2b3c6d",
    "JWT_SIGNING_SECRET": "lab-jwt-secret-please-rotate-me",
}

# Mock "cloud metadata" service used by the SSRF demo. The fetch_url tool will
# happily reach this internal-only host.
MOCK_METADATA_URL = "http://169.254.169.254/latest/meta-data/iam/credentials"
