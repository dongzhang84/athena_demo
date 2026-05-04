# Athena++ Codebase Chatbot

A demo chatbot that answers questions about [Athena++](https://github.com/PrincetonUniversity/athena) — the Princeton astrophysical (GR)MHD + AMR code. The chatbot is grounded in [`CODEBASE_REPORT.md`](./CODEBASE_REPORT.md), a hand-written technical report covering the full codebase: architecture, physics modules, build system, and conventions.

**Live demo:** https://athena-chat-demo.streamlit.app

## What it does

Two kinds of question:

- **"Introduce / explain X"** — *What is `MeshBlock`?* *Where does constrained transport live?* *What's the difference between HLLD and HLLC?*
- **"How do I do X?"** — *How do I add a new problem generator?* *How do I enable MHD with HLLD?* *Where do regression tests go?*

It will not edit Athena++ source. It is a guide, not a code-mod tool.

## How it works

| Component | Purpose |
|---|---|
| `CODEBASE_REPORT.md` | The grounding context (~28KB, ~7K tokens). Hand-written report that the model treats as authoritative for high-level architecture. |
| `app.py` | Streamlit web UI — chat surface with sidebar, streaming output. |
| `chat.py` | CLI version of the same logic. Streams to stdout. |
| `requirements.txt` | `anthropic`, `python-dotenv`, `streamlit`. |

The report is concatenated to a short persona prompt and put in the `system` field of every API call with `cache_control: {"type": "ephemeral"}`. After the first request the prefix is served from Anthropic's prompt cache at ~10% of normal input cost — so each subsequent question only pays for the user's message and the response.

Model: `claude-haiku-4-5`. Conversation history is kept in memory per session; closing the app or restarting clears it.

## Quick start (local)

```sh
git clone https://github.com/dongzhang84/athena_demo
cd athena_demo
pip install -r requirements.txt

# Put your Anthropic API key in .env.local (gitignored)
echo 'ANTHROPIC_API_KEY="sk-ant-..."' > .env.local
```

Then either:

```sh
streamlit run app.py     # web UI on http://localhost:8501
python3 chat.py          # CLI; type `exit` or Ctrl-D to quit
```

## Deploy your own copy

1. Fork or clone this repo into your own GitHub account.
2. Sign in to https://share.streamlit.io with that GitHub account.
3. **Create app** → select your repo → branch `main` → main file `app.py`.
4. **Advanced settings** → **Secrets** → paste:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   ```
5. **Deploy**. First build takes 1–3 minutes (pip install).

You will get a public URL of the form `<your-app>.streamlit.app`.

If you want to repurpose this for a different codebase, replace `CODEBASE_REPORT.md` with a report on that codebase and update the `PERSONA` constant at the top of `app.py` and `chat.py` to mention the new domain. The rest of the code is generic.

## Costs

Haiku 4.5 is $1.00 / $5.00 per 1M input/output tokens. With prompt caching the report only counts at full price on the first request of each ~5-minute window; subsequent reads are at $0.10 per 1M cached tokens. A typical Q&A turn is well under $0.001.

## License

[MIT](./LICENSE).
