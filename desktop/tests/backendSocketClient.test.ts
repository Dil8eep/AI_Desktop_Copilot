import { once } from "node:events";
import { afterEach, describe, expect, it } from "vitest";
import { WebSocketServer } from "ws";
import { BackendSocketClient } from "../src/main/services/backendSocketClient";

const waitFor = async <T>(
  register: (resolve: (value: T) => void) => void,
): Promise<T> => new Promise<T>((resolve) => register(resolve));

describe("BackendSocketClient", () => {
  const servers: WebSocketServer[] = [];

  afterEach(async () => {
    await Promise.all(
      servers.map((server) => new Promise<void>((resolve) => server.close(resolve))),
    );
  });

  it("drops microphone chunks quietly while disconnected", () => {
    const client = new BackendSocketClient({
      url: "ws://127.0.0.1:8765/ws",
      localToken: "test-token",
      reconnectDelayMs: 10,
    });

    expect(client.sendAudioChunk("session", new Uint8Array([1, 2]), 16_000)).toBe(
      false,
    );
  });

  it("keeps authentication tokens in the main process and forwards streaming events", async () => {
    const server = new WebSocketServer({ port: 0 });
    servers.push(server);
    await once(server, "listening");
    const address = server.address();
    if (typeof address === "string" || address === null) {
      throw new Error("Expected a TCP test server.");
    }

    const receivedCommand = waitFor<Record<string, unknown>>((resolve) => {
      server.on("connection", (socket, request) => {
        expect(request.headers["x-copilot-token"]).toBe("test-token");
        expect(request.headers.authorization).toBe("Bearer user-jwt");
        socket.on("message", (raw) => {
          const command = JSON.parse(raw.toString()) as Record<string, unknown>;
          resolve(command);
          socket.send(
            JSON.stringify({
              event: "llm.token",
              sessionId: command.sessionId,
              requestId: command.requestId,
              timestamp: new Date().toISOString(),
              payload: { delta: "streamed" },
            }),
          );
        });
      });
    });

    const client = new BackendSocketClient({
      url: `ws://127.0.0.1:${address.port}`,
      localToken: "test-token",
      reconnectDelayMs: 10,
    });
    const connected = waitFor<void>((resolve) => {
      client.onStatus((status) => {
        if (status === "connected") {
          resolve();
        }
      });
    });
    const streamed = waitFor<string>((resolve) => {
      client.onEvent((event) => {
        if (event.event === "llm.token") {
          resolve(String(event.payload.delta));
        }
      });
    });

    client.setAccessToken("user-jwt");
    client.start();
    await connected;
    const sessionId = client.startSession("Test the stream");

    expect((await receivedCommand).sessionId).toBe(sessionId);
    await expect(streamed).resolves.toBe("streamed");
    client.shutdown();
  });
});
