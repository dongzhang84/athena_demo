# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-05-04

### Added
- Streamlit web UI (`app.py`) with chat-style interface, example-question sidebar, and a Clear-conversation button. Streams responses via `st.write_stream`.
- Public deployment at https://athena-chat-demo.streamlit.app on Streamlit Community Cloud.
- `streamlit>=1.40` added to `requirements.txt`.
- `README.md`, `CHANGELOG.md`, `CLAUDE.md`, and an MIT `LICENSE`.

## [0.1.0] - 2026-05-03

### Added
- `CODEBASE_REPORT.md` — a comprehensive technical report on the Athena++ codebase (architecture, physics modules, build system, conventions). This is the grounding context the chatbot reads from.
- `chat.py` — CLI chatbot. Streams answers from `claude-haiku-4-5` with the report cached in the system prompt via `cache_control: ephemeral`.
- `.gitignore` excluding `.env.local`, virtualenvs, caches, and OS junk.
- Initial `requirements.txt` (`anthropic`, `python-dotenv`).

[Unreleased]: https://github.com/dongzhang84/athena_demo/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/dongzhang84/athena_demo/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/dongzhang84/athena_demo/releases/tag/v0.1.0
