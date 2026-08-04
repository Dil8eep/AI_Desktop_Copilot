import { useEffect, useState, type ReactElement } from "react";
import type {
  BackendConnectionStatus,
  OverlayPreferences,
} from "../../../shared/desktopApi";

const initialPreferences: OverlayPreferences = { opacity: 0.92, fontSize: 16 };

const captureDisplay = async (): Promise<Uint8Array> => {
  const stream = await navigator.mediaDevices.getDisplayMedia({
    audio: false,
    video: true,
  });
  try {
    const video = document.createElement("video");
    video.srcObject = stream;
    video.muted = true;
    await video.play();
    const track = stream.getVideoTracks()[0];
    const settings = track?.getSettings();
    const width = settings?.width ?? video.videoWidth;
    const height = settings?.height ?? video.videoHeight;
    if (!width || !height) {
      throw new Error("The selected screen has no video dimensions.");
    }
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (!context) {
      throw new Error("Unable to prepare the screen capture.");
    }
    context.drawImage(video, 0, 0, width, height);
    const blob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(
        (image) =>
          image ? resolve(image) : reject(new Error("Screen capture failed.")),
        "image/jpeg",
        0.85,
      );
    });
    return new Uint8Array(await blob.arrayBuffer());
  } finally {
    stream.getTracks().forEach((track) => track.stop());
  }
};

/** User-visible control surface; it never holds provider credentials. */
export const SettingsApp = (): ReactElement => {
  const [backendStatus, setBackendStatus] =
    useState<BackendConnectionStatus>("connecting");
  const [preferences, setPreferences] = useState(initialPreferences);
  const [message, setMessage] = useState("Ready to connect to the local backend.");
  const [isCapturingScreen, setIsCapturingScreen] = useState(false);
  const [isCapturingSystemAudio, setIsCapturingSystemAudio] = useState(false);
  const [systemAudioSessionId, setSystemAudioSessionId] = useState<string>();
  const [transcript, setTranscript] = useState("");

  useEffect(() => {
    void window.desktopApi.getBackendStatus().then(setBackendStatus);
    const unsubscribeStatus = window.desktopApi.onBackendStatus(setBackendStatus);
    const unsubscribeEvents = window.desktopApi.onBackendEvent((event) => {
      if (event.event === "vision.updated") {
        const blocks = event.payload.blocks;
        setMessage(
          `Screen analyzed: ${Array.isArray(blocks) ? blocks.length : 0} text regions found.`,
        );
      }
      if (event.event === "system_audio.started") {
        setIsCapturingSystemAudio(true);
        setMessage("Capturing selected Windows speaker output.");
      }
      if (event.event === "system_audio.stopped") {
        setIsCapturingSystemAudio(false);
        setSystemAudioSessionId(undefined);
        setMessage("System-audio capture stopped.");
      }
      if (event.event === "audio.segmented") {
        setMessage("Other-speaker segment detected; transcribing with Groq...");
      }
      if (event.event === "speech.final" && typeof event.payload.text === "string") {
        const source =
          event.payload.source === "system-audio" ? "Other speaker" : "Speaker";
        setTranscript(
          (current) =>
            `${current}${current ? "\n" : ""}${source}: ${event.payload.text}`,
        );
        setMessage("Final transcript received; generating the overlay response.");
      }
      if (event.event === "protocol.error" && typeof event.payload.code === "string") {
        setMessage(`Backend rejected input: ${event.payload.code}`);
      }
    });
    return () => {
      unsubscribeStatus();
      unsubscribeEvents();
    };
  }, []);

  const updatePreferences = (next: OverlayPreferences): void => {
    setPreferences(next);
    void window.desktopApi.setOverlayPreferences(next);
  };

  const captureScreen = async (): Promise<void> => {
    setIsCapturingScreen(true);
    setMessage("Choose a display to analyze. The image stays on your local backend.");
    try {
      const image = await captureDisplay();
      await window.desktopApi.sendScreenCapture(image, "image/jpeg");
      setMessage("Analyzing selected screen text...");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Unable to capture the screen.",
      );
    } finally {
      setIsCapturingScreen(false);
    }
  };

  const toggleSystemAudio = async (): Promise<void> => {
    try {
      if (isCapturingSystemAudio && systemAudioSessionId) {
        await window.desktopApi.stopSystemAudio(systemAudioSessionId);
        setMessage("Stopping Windows speaker-output capture...");
        return;
      }
      const sessionId = await window.desktopApi.startSystemAudio();
      setSystemAudioSessionId(sessionId);
      setMessage("Starting Windows speaker-output capture...");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Unable to capture system audio.",
      );
    }
  };

  return (
    <main className="min-h-screen bg-slate-950 p-10 text-slate-100">
      <section className="mx-auto max-w-2xl rounded-3xl border border-slate-800 bg-slate-900/80 p-8 shadow-2xl">
        <p className="text-sm font-medium tracking-[0.2em] text-cyan-300">
          CONTROL CENTER
        </p>
        <h1 className="mt-3 text-3xl font-semibold">AI Desktop Copilot</h1>
        <p className="mt-3 text-slate-300">Local backend: {backendStatus}</p>
        <div className="mt-8 flex flex-wrap gap-3">
          {" "}
          <button
            className="rounded-lg border border-slate-600 px-4 py-2"
            onClick={() => void window.desktopApi.showOverlay()}
            type="button"
          >
            Show overlay
          </button>
          <button
            className="rounded-lg border border-cyan-400 px-4 py-2 text-cyan-200 disabled:opacity-50"
            disabled={backendStatus !== "connected" || isCapturingScreen}
            onClick={() => void captureScreen()}
            type="button"
          >
            {isCapturingScreen ? "Preparing capture..." : "Analyze screen text"}
          </button>
          <button
            className="rounded-lg border border-emerald-400 px-4 py-2 text-emerald-200 disabled:opacity-50"
            disabled={backendStatus !== "connected"}
            onClick={() => void toggleSystemAudio()}
            type="button"
          >
            {isCapturingSystemAudio ? "Stop system audio" : "Start system audio"}
          </button>
        </div>
        <p className="mt-3 text-sm text-slate-400">{message}</p>
        {transcript ? (
          <section className="mt-5 rounded-2xl border border-slate-700 bg-slate-950/70 p-4">
            <p className="text-xs font-medium tracking-[0.16em] text-cyan-300">
              LIVE TRANSCRIPT
            </p>
            <p className="mt-2 whitespace-pre-wrap text-sm text-slate-200">
              {transcript}
            </p>
          </section>
        ) : null}
        <p className="mt-3 text-xs text-slate-500">
          System audio captures all sound playing through the selected Windows output
          device. Use only with participant consent.
        </p>

        <div className="mt-8 grid gap-5 rounded-2xl bg-slate-800/80 p-5">
          <label className="grid gap-2 text-sm" htmlFor="opacity">
            Overlay opacity: {Math.round(preferences.opacity * 100)}%
            <input
              id="opacity"
              max="1"
              min="0.3"
              onChange={(event) =>
                updatePreferences({
                  ...preferences,
                  opacity: Number(event.target.value),
                })
              }
              step="0.01"
              type="range"
              value={preferences.opacity}
            />
          </label>
          <label className="grid gap-2 text-sm" htmlFor="font-size">
            Overlay font size: {preferences.fontSize}px
            <input
              id="font-size"
              max="24"
              min="12"
              onChange={(event) =>
                updatePreferences({
                  ...preferences,
                  fontSize: Number(event.target.value),
                })
              }
              type="range"
              value={preferences.fontSize}
            />
          </label>
        </div>
      </section>
    </main>
  );
};
