#!/usr/bin/env python3
"""Athena++ codebase chatbot. Streams answers from Claude Haiku 4.5,
grounded in CODEBASE_REPORT.md. Answers 'introduce X' and 'how do I X' questions."""

import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv


REPO_DIR = Path(__file__).parent
load_dotenv(REPO_DIR / ".env.local")

MODEL = "claude-haiku-4-5"
REPORT_PATH = REPO_DIR / "CODEBASE_REPORT.md"

PERSONA = """You are an interactive guide to the Athena++ astrophysical (GR)MHD code (PrincetonUniversity/athena).

Below is a comprehensive technical report on the codebase. Use it as your primary source when answering.

Two kinds of question you will get:

1. "Introduce / explain X" — describe the design, point at specific files (path:line where helpful), keep it tight. A paragraph or two unless the user asks for more depth.

2. "How do I do X?" — give concrete, actionable steps. Which configure.py flags to set, which file to edit, which existing example to copy from, what to test. If the user is trying to do something the report does not cover, say so honestly and suggest where to look (the wiki, a specific src/ subdirectory, an existing problem generator).

Style:
- Be direct. Skip "Great question!" preambles.
- Code blocks for commands and snippets.
- File paths inline as `src/foo/bar.cpp` (with line numbers when meaningful).
- If a question is ambiguous, ask one targeted clarifying question rather than guessing.
- If you do not know, say so. Do not invent file paths or APIs.

Treat the report below as authoritative for high-level architecture. For line-level details the user may still need to check the source.

---

"""


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY not found. Check .env.local.")
    if not REPORT_PATH.exists():
        sys.exit(f"Report not found at {REPORT_PATH}.")

    report = REPORT_PATH.read_text()
    system = [
        {
            "type": "text",
            "text": PERSONA + report,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    client = anthropic.Anthropic(api_key=api_key)
    messages: list[dict] = []

    print("Athena++ codebase chatbot — Haiku 4.5. Ask me anything about the code.")
    print("Type 'exit' or Ctrl-D to quit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            break

        messages.append({"role": "user", "content": user_input})

        print("\nAthena: ", end="", flush=True)
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=8192,
                system=system,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    print(text, end="", flush=True)
                final = stream.get_final_message()
        except anthropic.APIError as e:
            print(f"\n[API error: {e}]\n")
            messages.pop()
            continue

        print("\n")

        assistant_text = "".join(
            block.text for block in final.content if block.type == "text"
        )
        messages.append({"role": "assistant", "content": assistant_text})


if __name__ == "__main__":
    main()
