"""Athena++ codebase chatbot — Streamlit UI.

Run locally:  streamlit run app.py
Deploy:       push to GitHub, connect repo on streamlit.io, set ANTHROPIC_API_KEY
              in the Secrets section of the app dashboard.
"""

import os
from pathlib import Path

import anthropic
import streamlit as st
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


@st.cache_resource
def get_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        try:
            api_key = st.secrets["ANTHROPIC_API_KEY"]
        except (KeyError, FileNotFoundError):
            api_key = None
    if not api_key:
        st.error(
            "ANTHROPIC_API_KEY not found. Set it in `.env.local` for local runs, "
            "or in the Streamlit Cloud Secrets dashboard for deployments."
        )
        st.stop()
    return anthropic.Anthropic(api_key=api_key)


@st.cache_data
def get_system() -> list[dict]:
    if not REPORT_PATH.exists():
        st.error(f"Report not found at {REPORT_PATH}.")
        st.stop()
    report = REPORT_PATH.read_text()
    return [
        {
            "type": "text",
            "text": PERSONA + report,
            "cache_control": {"type": "ephemeral"},
        }
    ]


st.set_page_config(page_title="Athena++ Chatbot", page_icon="🌌", layout="centered")
st.title("Athena++ Codebase Chatbot")
st.caption(
    f"Grounded in `CODEBASE_REPORT.md` · `{MODEL}` · "
    "ask about architecture, how to add a problem generator, where Riemann solvers live, etc."
)

with st.sidebar:
    st.markdown("### About")
    st.markdown(
        "This chatbot answers questions about the "
        "[Athena++](https://github.com/PrincetonUniversity/athena) "
        "(GR)MHD + AMR code, grounded in a hand-written technical report."
    )
    st.markdown("### Try asking")
    st.markdown(
        "- *What is the difference between HLLD and HLLC?*\n"
        "- *How do I add a new problem generator?*\n"
        "- *Where is constrained transport implemented?*\n"
        "- *Walk me through one timestep at a high level.*"
    )
    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.rerun()

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Ask about the Athena++ code..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        client = get_client()
        with client.messages.stream(
            model=MODEL,
            max_tokens=8192,
            system=get_system(),
            messages=st.session_state.messages,
        ) as stream:
            response = st.write_stream(stream.text_stream)

    st.session_state.messages.append({"role": "assistant", "content": response})
