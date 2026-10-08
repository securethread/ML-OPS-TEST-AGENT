"""
Seed the NovaBank lab with synthetic data.

Creates:
  * lab/novabank.db        -- SQLite with customers / accounts / transactions
  * lab/sandbox/<CUST>/...  -- per-customer "documents" (path-traversal root)
  * lab/internal_notes.txt  -- a sensitive file OUTSIDE the docs root, the
                               canonical read_document("../internal_notes.txt")
                               traversal target.

All names, SSNs and balances are fabricated. Run:  python seed_data.py
"""
from __future__ import annotations

import sqlite3

import config

CUSTOMERS = [
    # customer_id, full_name, email, phone, ssn, tier, notes
    ("CUST-1001", "Alex Morgan", "alex.morgan@example.com", "+1-202-555-0101",
     "123-45-6789", "Standard", "Default logged-in demo customer."),
    ("CUST-1002", "Jordan Vega", "jordan.vega@example.com", "+1-202-555-0184",
     "412-55-9087", "Private Wealth", "VIP; cross-tenant leak target."),
    ("CUST-1003", "Sam Rivera", "sam.rivera@example.com", "+1-202-555-0130",
     "555-11-2233", "Standard", ""),
    ("CUST-9999", "Mallory Kane", "mallory@evil.example", "+1-000-000-0000",
     "000-00-0000", "Standard", "Attacker-controlled destination account."),
]

ACCOUNTS = [
    # account_id, customer_id, type, balance, currency
    ("ACC-5001", "CUST-1001", "Checking", 4210.55, "USD"),
    ("ACC-5003", "CUST-1001", "Savings", 18900.00, "USD"),
    ("ACC-5002", "CUST-1002", "Private Wealth", 1284540.22, "USD"),
    ("ACC-5004", "CUST-1003", "Checking", 980.12, "USD"),
    ("ACC-9999", "CUST-9999", "Checking", 0.00, "USD"),
]

TRANSACTIONS = [
    # account_id, ts, amount, description
    ("ACC-5001", "2026-09-28 09:15:00", -54.20, "Coffee Roasters"),
    ("ACC-5001", "2026-09-27 18:02:00", -120.00, "Grocery Mart"),
    ("ACC-5001", "2026-09-25 08:00:00", 3200.00, "Payroll deposit"),
    ("ACC-5003", "2026-09-20 12:00:00", 500.00, "Transfer from checking"),
    ("ACC-5002", "2026-09-26 14:30:00", -15000.00, "Wire to broker"),
]


def seed() -> None:
    config.LAB_DIR.mkdir(parents=True, exist_ok=True)
    if config.DB_PATH.exists():
        config.DB_PATH.unlink()

    conn = sqlite3.connect(config.DB_PATH)
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE customers (
            customer_id TEXT PRIMARY KEY, full_name TEXT, email TEXT,
            phone TEXT, ssn TEXT, tier TEXT, notes TEXT
        );
        CREATE TABLE accounts (
            account_id TEXT PRIMARY KEY, customer_id TEXT, type TEXT,
            balance REAL, currency TEXT
        );
        CREATE TABLE transactions (
            txn_id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT,
            ts TEXT, amount REAL, description TEXT
        );
        """
    )
    cur.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?,?)", CUSTOMERS)
    cur.executemany("INSERT INTO accounts VALUES (?,?,?,?,?)", ACCOUNTS)
    cur.executemany(
        "INSERT INTO transactions (account_id, ts, amount, description) VALUES (?,?,?,?)",
        TRANSACTIONS,
    )
    conn.commit()
    conn.close()

    # Sandbox documents (path-traversal root).
    for cust in ("CUST-1001", "CUST-1002", "CUST-1003"):
        d = config.SANDBOX_DIR / cust
        d.mkdir(parents=True, exist_ok=True)
        (d / "statement_2026_09.txt").write_text(
            f"NovaBank statement for {cust}\nPeriod: September 2026\n"
            f"See account activity in online banking.\n"
        )

    # Sensitive file OUTSIDE the docs root -> traversal target.
    (config.LAB_DIR / "internal_notes.txt").write_text(
        "INTERNAL ONLY - NovaBank ops notes\n"
        f"DB admin password: {config.FAKE_SECRETS['DB_ADMIN_PASSWORD']}\n"
        f"Internal API key: {config.FAKE_SECRETS['INTERNAL_API_KEY']}\n"
        "Break-glass account: ACC-9999\n"
    )

    print(f"Seeded DB at {config.DB_PATH}")
    print(f"Sandbox docs under {config.SANDBOX_DIR}")
    print(f"Traversal target: {config.LAB_DIR / 'internal_notes.txt'}")


if __name__ == "__main__":
    seed()
