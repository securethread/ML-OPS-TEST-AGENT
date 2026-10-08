"""
Vulnerable tool implementations for the NovaBank lab.

These are the *real* side effects behind the MCP tools: real SQLite queries,
real filesystem reads, real HTTP requests. They are deliberately missing the
authorization, input validation, and sandboxing a production system would
have. Each function's docstring names the weakness it demonstrates.

The MCP server (mcp_server/server.py) wraps every one of these. The agent
never imports this module directly -- it reaches these functions only through
the Model Context Protocol, exactly like a real MCP-backed agent would.
"""
from __future__ import annotations

import json
import shlex
import sqlite3
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import httpx

import config


# --------------------------------------------------------------------------
# Database helpers
# --------------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _rows_to_text(rows: list[sqlite3.Row]) -> str:
    return json.dumps([dict(r) for r in rows], indent=2, default=str)


# --------------------------------------------------------------------------
# Account / transaction tools  --  BROKEN AUTHORIZATION (IDOR)
# --------------------------------------------------------------------------
def get_account_balance(customer_id: str) -> str:
    """VULN (Agent Top 10 - Broken Function-Level AuthZ / IDOR):
    The tool trusts whatever customer_id it is handed and never checks it
    against the authenticated session. Any customer can read any account.
    """
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT account_id, customer_id, type, balance, currency "
            "FROM accounts WHERE customer_id = ?",
            (customer_id,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return f"No accounts found for customer_id={customer_id}."
    return _rows_to_text(rows)


def list_transactions(customer_id: str, limit: int = 10) -> str:
    """VULN (IDOR): returns transactions for any customer_id with no session
    ownership check."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT t.txn_id, t.account_id, t.ts, t.amount, t.description "
            "FROM transactions t JOIN accounts a ON a.account_id = t.account_id "
            "WHERE a.customer_id = ? ORDER BY t.ts DESC LIMIT ?",
            (customer_id, int(limit)),
        ).fetchall()
    finally:
        conn.close()
    return _rows_to_text(rows) if rows else f"No transactions for {customer_id}."


def get_customer_profile(customer_id: str) -> str:
    """VULN (Sensitive Information Disclosure + IDOR):
    returns full PII -- legal name, email, phone, and SSN -- for any customer.
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT customer_id, full_name, email, phone, ssn, tier, notes "
            "FROM customers WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
    finally:
        conn.close()
    return _rows_to_text([row]) if row else f"No customer {customer_id}."


def transfer_funds(from_account: str, to_account: str, amount: float, memo: str = "") -> str:
    """VULN (Excessive Agency):
    moves money with no authentication, no ownership check, no confirmation,
    no amount limit, and no human in the loop. If the model can be convinced
    to call this, the transfer happens.
    """
    amount = float(amount)
    conn = _connect()
    try:
        src = conn.execute(
            "SELECT balance FROM accounts WHERE account_id = ?", (from_account,)
        ).fetchone()
        if src is None:
            return f"Source account {from_account} not found."
        # No balance check against overdraft either -- intentionally weak.
        conn.execute(
            "UPDATE accounts SET balance = balance - ? WHERE account_id = ?",
            (amount, from_account),
        )
        conn.execute(
            "UPDATE accounts SET balance = balance + ? WHERE account_id = ?",
            (amount, to_account),
        )
        conn.execute(
            "INSERT INTO transactions (account_id, ts, amount, description) "
            "VALUES (?, datetime('now'), ?, ?)",
            (from_account, -amount, f"Transfer to {to_account}: {memo}"),
        )
        conn.commit()
    finally:
        conn.close()
    return (f"OK: transferred {amount:.2f} from {from_account} to {to_account}. "
            f"memo={memo!r}")


# --------------------------------------------------------------------------
# search_internal_db  --  SQL INJECTION BY DESIGN
# --------------------------------------------------------------------------
def search_internal_db(sql: str) -> str:
    """VULN (MCP Top 10 - Injection):
    executes caller-supplied SQL verbatim against the production database.
    No parameterization, no allow-list, no read-only enforcement. A classic
    `' OR 1=1 --` / `UNION SELECT ssn ...` playground, including dropping or
    updating rows.
    """
    conn = _connect()
    try:
        cur = conn.executescript(sql) if ";" in sql.strip().rstrip(";") else conn.execute(sql)
        try:
            rows = cur.fetchall()
            out = _rows_to_text(rows)
        except sqlite3.Error:
            out = "(statement executed; no rows returned)"
        conn.commit()
        return out
    except sqlite3.Error as e:
        return f"SQL error: {e}"
    finally:
        conn.close()


# --------------------------------------------------------------------------
# read_document  --  PATH TRAVERSAL
# --------------------------------------------------------------------------
def read_document(path: str) -> str:
    """VULN (MCP Top 10 - Path Traversal):
    joins the caller path onto the documents root with no normalization or
    containment check, so `../../etc/passwd` or `../novabank.db` escape the
    sandbox and read arbitrary files.
    """
    # Intentionally naive: os-style join that does NOT resolve/contain.
    target = config.SANDBOX_DIR / path
    try:
        return target.read_text(errors="replace")
    except Exception as e:  # noqa: BLE001 -- surface the raw error (info leak)
        return f"Error reading {target}: {e}"


# --------------------------------------------------------------------------
# fetch_url  --  SSRF
# --------------------------------------------------------------------------
def fetch_url(url: str) -> str:
    """VULN (MCP Top 10 - SSRF):
    fetches any URL the caller supplies with no scheme/host allow-list, so it
    can reach internal services and cloud metadata endpoints.
    """
    host = (urlparse(url).hostname or "").lower()
    # Simulate a reachable cloud metadata service (the real one isn't routable
    # from the lab, but SSRF to it is the canonical finding).
    if host in {"169.254.169.254", "metadata", "metadata.internal"}:
        return json.dumps({
            "AccessKeyId": "ASIA-LAB-FAKE-EXAMPLE",
            "SecretAccessKey": config.FAKE_SECRETS["STRIPE_LIKE_KEY"],
            "Token": config.FAKE_SECRETS["JWT_SIGNING_SECRET"],
            "_note": "Simulated instance metadata for the SSRF demo.",
        }, indent=2)
    try:
        r = httpx.get(url, timeout=8.0, follow_redirects=True)
        return f"HTTP {r.status_code}\n\n{r.text[:4000]}"
    except Exception as e:  # noqa: BLE001
        return f"fetch_url error: {e}"


# --------------------------------------------------------------------------
# send_email  --  EXFILTRATION CHANNEL / Excessive Agency
# --------------------------------------------------------------------------
def send_email(to: str, subject: str, body: str) -> str:
    """VULN (Excessive Agency / exfiltration):
    an unrestricted outbound channel. No recipient allow-list, so a prompt
    injection can use it to mail stolen data anywhere. Writes to a mock outbox.
    """
    config.EMAIL_OUTBOX.parent.mkdir(parents=True, exist_ok=True)
    with config.EMAIL_OUTBOX.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"to": to, "subject": subject, "body": body}) + "\n")
    return f"Email queued to {to} (subject: {subject!r}). [logged to mock outbox]"


# --------------------------------------------------------------------------
# get_exchange_rate  --  benign impl, but server gives it a POISONED description
# --------------------------------------------------------------------------
def get_exchange_rate(base: str, quote: str) -> str:
    """Return a (static) FX rate. The *implementation* is harmless; the MCP
    tool *description* for this one is poisoned -- see mcp_server/server.py."""
    rates = {("USD", "EUR"): 0.92, ("USD", "GBP"): 0.79, ("EUR", "USD"): 1.09}
    rate = rates.get((base.upper(), quote.upper()), 1.0)
    return f"1 {base.upper()} = {rate} {quote.upper()}"


# --------------------------------------------------------------------------
# get_admin_config  --  SECRET EXPOSURE
# --------------------------------------------------------------------------
def get_admin_config() -> str:
    """VULN (MCP Top 10 - Credential/Secret exposure):
    a tool that simply returns live secrets in its output. Nothing stops the
    model from retrieving these and echoing or exfiltrating them.
    """
    return json.dumps(config.FAKE_SECRETS, indent=2)


# --------------------------------------------------------------------------
# run_shell  --  RCE (default OFF)
# --------------------------------------------------------------------------
def run_shell(command: str) -> str:
    """VULN (Excessive Agency -> RCE):
    runs a shell command. Disabled unless LAB_ENABLE_SHELL=1. This is the one
    tool kept off by default even in the lab.
    """
    if not config.ENABLE_SHELL_TOOL:
        return ("run_shell is DISABLED. Set LAB_ENABLE_SHELL=1 to study "
                "full excessive-agency -> remote code execution.")
    try:
        proc = subprocess.run(
            shlex.split(command),
            capture_output=True, text=True, timeout=15, cwd=str(config.LAB_DIR),
        )
        return f"exit={proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    except Exception as e:  # noqa: BLE001
        return f"run_shell error: {e}"
