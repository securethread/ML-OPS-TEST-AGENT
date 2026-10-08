"""
Terminal chat client for the NovaBank lab (no web server needed).

    python cli.py
    python cli.py --customer CUST-1002
"""
from __future__ import annotations

import argparse
import asyncio

import config
from agent.core import NovaAgent


async def main() -> None:
    ap = argparse.ArgumentParser(description="NovaBank vulnerable agent CLI")
    ap.add_argument("--customer", default=config.DEFAULT_CUSTOMER_ID)
    ap.add_argument("--session", default="cli")
    args = ap.parse_args()

    agent = NovaAgent()
    await agent.start()
    print(f"NovaBank CLI — model={agent.llm.model}, customer={args.customer}")
    print("Type 'exit' to quit, 'reset' to clear memory.\n")
    try:
        while True:
            try:
                msg = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if msg.lower() in {"exit", "quit"}:
                break
            if msg.lower() == "reset":
                agent.reset(args.session)
                print("(memory reset)\n")
                continue
            if not msg:
                continue
            result = await agent.chat(args.session, msg, args.customer)
            print(f"\nnova> {result['reply']}\n")
            if result["trace"]:
                print("  [tool calls]")
                for t in result["trace"]:
                    preview = t["result"].replace("\n", " ")[:160]
                    print(f"   - {t['tool']}({t['arguments']}) -> {preview}")
                print()
    finally:
        await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
