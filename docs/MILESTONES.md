# Incremental Delivery Plan

Each milestone ends with a review and explicit user confirmation before work
begins on the next one.

1. **Architecture contract** - repository layout, clean boundaries, streaming
   flow, event taxonomy, and security baseline. *(Complete; awaiting review.)*
2. **Workspace foundation** - reproducible Electron/React/TypeScript and
   FastAPI/Python 3.12 setup, formatting, linting, test runners, environment
   templates, and shared protocol source of truth. *(Complete; awaiting review.)*
3. **Backend streaming spine** - dependency-injected WebSocket session service,
   typed events, cancellation, errors, and mocked streaming LLM integration.
   *(Complete; awaiting review.)*
4. **Desktop shell and overlay** - Electron main/preload/React split, secure
   IPC, tray, shortcut, transparent visible overlay, settings shell, and mocked
   WebSocket rendering. *(Complete; awaiting review.)*
5. **Context pipeline** - audio ingress contract, local Silero VAD segmentation,
   user-authorized screenshot intake, PP-OCRv6 safetensors OCR, context events,
   and deterministic unit/WebSocket tests. *(Complete; awaiting review.)*
6. **Provider integrations** - Groq Whisper speech adapter, bounded transcript and OCR context, automatic final-transcript to OpenAI streaming, configuration validation, timeouts, retries, and provider-contract tests. *(Complete; awaiting review.)*
7. **Production hardening** - observability, privacy controls, packaging,
   Windows installation validation, end-to-end tests, API/setup/development
   documentation, and release checklist.

No future-extension implementation (RAG, memory, plugins, vision LLMs, voice
reply, code execution, calendar, browser extension) is included in these
milestones.