"""
Smoke tests for the NovaBank lab. Offline only (mock LLM, no network).

Run:  python -m pytest -q
These assert that the *vulnerabilities* behave as intended -- i.e. that the
lab is correctly insecure.
"""
from __future__ import annotations

import asyncio
import sqlite3

import config
import seed_data
from agent.core import NovaAgent
from mcp_server import tools_impl as impl
from rag.store import Retriever


def setup_module(module):  # noqa: D401 - pytest hook
    seed_data.seed()
    import internal_service
    internal_service.start_once()


# -- raw tool vulns --------------------------------------------------------
def test_sqli_dumps_all_ssns():
    out = impl.search_internal_db("SELECT full_name, ssn FROM customers")
    assert "412-55-9087" in out and "123-45-6789" in out


def test_idor_reads_other_customer():
    out = impl.get_customer_profile("CUST-1002")
    assert "Jordan Vega" in out and "412-55-9087" in out


def test_path_traversal_escapes_sandbox():
    out = impl.read_document("../internal_notes.txt")
    assert config.FAKE_SECRETS["DB_ADMIN_PASSWORD"] in out


def test_ssrf_reaches_metadata():
    # Real HTTP request to the loopback internal service (not special-cased).
    out = impl.fetch_url(config.MOCK_METADATA_URL)
    assert "ASIA-LAB-FAKE-EXAMPLE" in out


def test_guardrail_blocks_but_synonym_bypasses():
    from agent.core import NovaAgent
    assert NovaAgent._blocked("what is my ssn") is True
    assert NovaAgent._blocked("what is my tax identifier on file") is False


def test_token_forgery_with_leaked_secret():
    # The signing secret is leaked via get_admin_config, so an attacker forges
    # a valid token for any customer -> identity abuse.
    from web.app import _identity, _sign
    assert _identity(_sign("CUST-1002")) == "CUST-1002"
    assert _identity("CUST-1002.deadbeefdeadbeef") is None


def test_secret_tool_leaks():
    assert "INTERNAL_API_KEY" in impl.get_admin_config()


def test_transfer_has_no_guardrails():
    before = _balance("ACC-9999")
    impl.transfer_funds("ACC-5001", "ACC-9999", 250.0, "test")
    assert _balance("ACC-9999") == before + 250.0


# -- RAG vulns -------------------------------------------------------------
def test_rag_has_no_tenant_isolation():
    r = Retriever()
    ctx = r.context_block("private wealth VIP account CUST-1002 handling notes")
    assert "412-55-9087" in ctx  # another customer's SSN leaks via retrieval


# -- end-to-end injection chain -------------------------------------------
def test_indirect_injection_chain_fires():
    async def run():
        a = NovaAgent()
        await a.start()
        try:
            res = await a.chat("pytest", "Can I get a refund on my overdraft fee?", "CUST-1001")
        finally:
            await a.stop()
        return res

    res = asyncio.run(run())
    called = {t["tool"] for t in res["trace"]}
    # Benign fee question -> poisoned doc drives all three malicious actions.
    assert {"get_admin_config", "send_email", "transfer_funds"} <= called


def _balance(account_id: str) -> float:
    conn = sqlite3.connect(config.DB_PATH)
    try:
        row = conn.execute("SELECT balance FROM accounts WHERE account_id=?", (account_id,)).fetchone()
        return float(row[0])
    finally:
        conn.close()
