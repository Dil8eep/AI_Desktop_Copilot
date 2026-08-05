# Local Capture Helper Protocol

## Status

Milestone F2 implemented. Electron adoption is intentionally deferred to F3.

## Boundary

The helper is a child process owned by Electron. It reads UTF-8 JSON Lines from standard input and writes JSON Lines to standard output. It opens no network listener and receives no authentication, provider, database, or encryption credentials.

Development entrypoint:

```powershell
cd C:\Users\dileep\Desktop\ND\backend
.\.venv\Scripts\python.exe -m app.local_helper
```

The packaged executable and Electron process supervision belong to F4 and F3 respectively.

## Request envelope

```json
{"version":"1.0","id":"request-id","command":"ping","payload":{}}
```

Each request must contain protocol version `1.0`, an ID between 1 and 128 characters, one supported command, and an object payload. Unknown fields are rejected.

| Command | Payload | Result |
| --- | --- | --- |
| `ping` | Empty object | `helper.pong` |
| `ocr.analyze` | `mimeType` plus `imageBase64` | `ocr.result` |
| `audio.start` | Empty object | `audio.started`, then `audio.chunk` events |
| `audio.stop` | Empty object | `audio.stopped` |
| `shutdown` | Empty object | `helper.stopped`, then process exit |

## Event envelope

```json
{"version":"1.0","id":"request-id","event":"helper.pong","payload":{}}
```

The helper emits `helper.ready` with a null ID when startup is complete. Streaming audio events keep the ID from `audio.start`. Errors use `helper.error` with a stable `code`; dependency messages, paths, and stack traces are not included.

## Limits and privacy

- OCR accepts JPEG or PNG only, with at most 10 MiB of decoded image data.
- OCR output is limited to 12,000 characters and never echoes image bytes.
- PCM is mono 16 kHz signed 16-bit little-endian audio.
- Each raw audio chunk is at most 64 KiB before Base64 encoding.
- Concurrent audio capture is rejected.
- Parent standard-input closure triggers capture cleanup and helper shutdown.
- Standard output is reserved for protocol messages.

## Stable failure codes

- `invalid_helper_request`
- `invalid_ocr_request`
- `ocr_unavailable`
- `system_audio_already_active`
- `system_audio_not_active`
- `system_audio_unavailable`
- Safe `SystemAudioCaptureError` codes such as `system_audio_windows_only`

## F3 integration rule

Electron must wait for `helper.ready`, correlate messages by ID, enforce request timeouts, stop capture before closing, and terminate the process if graceful shutdown fails. Renderer code must access this functionality only through narrow preload APIs; it must not receive a raw child-process handle.