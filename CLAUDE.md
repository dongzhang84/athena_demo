# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A demo chatbot that answers questions about Athena++ (PrincetonUniversity/athena), grounded in `CODEBASE_REPORT.md`. **The chatbot does not modify Athena++ source — it explains it.** The Athena++ source itself is not in this repo.

Two surfaces share the same logic, persona, and model:

- `chat.py` — CLI REPL.
- `app.py` — Streamlit web UI. Deployed at https://athena-chat-demo.streamlit.app.

If you edit one, change the other to match. The `PERSONA` constant and the `MODEL` constant are duplicated by design (this is a demo; resisting the urge to factor them out keeps the surfaces independent).

## The grounding pattern

`CODEBASE_REPORT.md` is concatenated to the persona and put in the `system` field with `cache_control: {"type": "ephemeral"}`. Haiku 4.5's minimum cacheable prefix is 4096 tokens — the report (~7K tokens) clears that comfortably. After the first request of a ~5-minute window the prefix is served from cache.

If you swap the model, check `shared/prompt-caching.md` of the `claude-api` skill for the new minimum cacheable prefix — Sonnet's is 2048, Opus's is 4096.

If you change the report or the persona, the cache invalidates on the next request (single byte difference in the prefix → full rewrite). That is fine; just expect one full-price request after edits.

## Secrets

- **Local**: `ANTHROPIC_API_KEY` in `.env.local`, loaded via `python-dotenv`. `.env.local` is gitignored — never commit it.
- **Streamlit Cloud**: same key set in the app's Secrets dashboard, accessed via `st.secrets["ANTHROPIC_API_KEY"]`. `app.py` falls back from env → `st.secrets` so the same code path works in both places.
- `GITHUB_TOKEN` in `.env.local` is unused at runtime — kept for ad-hoc `gh` CLI work.

## Running and testing

```sh
pip install -r requirements.txt
python3 chat.py            # CLI
streamlit run app.py       # web UI on http://localhost:8501
```

No build step, no test suite — this is a demo. UI verification means actually opening the browser and sending a question; `curl http://localhost:8501/_stcore/health` only confirms the server boots.

## Deploy

Streamlit Community Cloud points at `app.py` on `main`. Pushing to `main` triggers a redeploy automatically. The secret has to be set manually in the Streamlit dashboard — Streamlit does not read `.env.local`.

## Repurposing for a different codebase

Replace `CODEBASE_REPORT.md` with a report on a different codebase, then update the `PERSONA` strings in `app.py` and `chat.py` to mention the new domain. Everything else is generic. The plumbing is the demo; the report is the value.
