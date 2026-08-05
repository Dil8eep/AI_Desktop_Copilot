import { describe, expect, it, vi } from "vitest";
import { LocalCaptureHelperClient } from "../src/main/services/localCaptureHelperClient";

const helperScript = String.raw`
const readline = require("node:readline");
const emit = (id, event, payload) => process.stdout.write(JSON.stringify({version:"1.0",id,event,payload}) + "\n");
emit(null, "helper.ready", {protocolVersion:"1.0"});
readline.createInterface({input:process.stdin}).on("line", (line) => {
  const request = JSON.parse(line);
  if (request.command === "ocr.analyze") {
    emit(request.id, "ocr.result", {text:"Which option is correct?",width:800,height:600,blockCount:1,truncated:false});
  } else if (request.command === "audio.start") {
    emit(request.id, "audio.started", {source:"system-audio",sampleRateHz:16000});
    setTimeout(() => emit(request.id, "audio.chunk", {source:"system-audio",sampleRateHz:16000,mimeType:"audio/pcm;codec=s16le",byteLength:3,audioBase64:Buffer.from([1,2,3]).toString("base64")}), 5);
  } else if (request.command === "audio.stop") {
    emit(request.id, "audio.stopped", {source:"system-audio"});
  } else if (request.command === "shutdown") {
    emit(request.id, "helper.stopped", {});
    process.exit(0);
  }
});
`;

const createClient = (onAudioChunk = vi.fn()): LocalCaptureHelperClient =>
  new LocalCaptureHelperClient(
    { command: process.execPath, args: ["-e", helperScript] },
    onAudioChunk,
  );

const waitUntil = async (predicate: () => boolean): Promise<void> => {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  throw new Error("Timed out waiting for helper event.");
};

describe("LocalCaptureHelperClient", () => {
  it("returns local OCR text without exposing helper process access", async () => {
    const client = createClient();
    await expect(
      client.analyzeScreen(new Uint8Array([1, 2, 3]), "image/jpeg"),
    ).resolves.toBe("Which option is correct?");
    await client.shutdown();
  });

  it("forwards bounded system-audio PCM under the helper session id", async () => {
    const onAudioChunk = vi.fn();
    const client = createClient(onAudioChunk);
    const sessionId = await client.startSystemAudio();
    await waitUntil(() => onAudioChunk.mock.calls.length === 1);
    expect(onAudioChunk).toHaveBeenCalledWith(
      sessionId,
      expect.any(Uint8Array),
      16_000,
    );
    expect([...onAudioChunk.mock.calls[0][1]]).toEqual([1, 2, 3]);
    await client.stopSystemAudio(sessionId);
    await client.shutdown();
  });

  it("rejects empty images before launching", async () => {
    const client = createClient();
    await expect(client.analyzeScreen(new Uint8Array(), "image/png")).rejects.toThrow(
      "between 1 byte and 10 MiB",
    );
  });
});
