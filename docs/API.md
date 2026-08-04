# API Contract (Milestone 5)

The local backend exposes `GET /health` and an authenticated WebSocket endpoint
at `/ws`, bound to loopback by default. Every connection must send the
`x-copilot-token` header matching `COPILOT_LOCAL_AUTH_TOKEN`.

## Streaming commands

- `session.start` requires `{ "prompt": string }`; it emits one or more
  `llm.token` events and exactly one `llm.completed` event.
- `session.stop` requires `{}` and cooperatively cancels the active stream.
- `screen.capture` declares `{ "mimeType": "image/jpeg" | "image/png",
  "byteLength": number }`, immediately followed by exactly one matching binary
  image frame. Images are capped at 10 MiB.
- `audio.chunk` declares `{ "mimeType": "audio/pcm;codec=s16le",
  "sampleRateHz": 16000, "byteLength": number }`, followed by one matching
  PCM16 mono binary frame. Audio chunks are capped at 64 KiB.

OCR runs in a background task and publishes `vision.updated` followed by
`context.updated`. Local VAD publishes `audio.segmented` when it closes an
utterance; transcription is not performed until Milestone 6.

Malformed envelopes, mismatched byte lengths, unsupported media types, and
unsupported commands produce `protocol.error` with a safe error code.

All envelopes conform to
[`shared/protocol/events.schema.json`](../shared/protocol/events.schema.json).