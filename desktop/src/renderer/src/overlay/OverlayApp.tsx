import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type ReactElement,
} from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import type {
  BackendConnectionStatus,
  BackendEvent,
  OverlayPreferences,
} from "../../../shared/desktopApi";

const defaultPreferences: OverlayPreferences = { opacity: 0.92, fontSize: 16 };

type ChatMessage = Readonly<{
  id: string;
  role: "assistant" | "user";
  content: string;
}>;

type AssistanceMode = "meeting" | "mock-interview";

const buildMockInterviewPrompt = (question: string): string =>
  "This is an explicit mock-interview practice exercise. Answer the " +
  "interviewer's latest question as me, in a concise and natural first-person " +
  "voice. Use my prepared resume profile as the only source for personal " +
  "facts, qualifications, skills, projects, education, and experience. " +
  "Do not call yourself an AI assistant and do not invent missing details. " +
  `If the resume does not support an answer, say that honestly.\n\n${question}`;

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
    const dimensions = track?.getSettings();
    const width = dimensions?.width ?? video.videoWidth;
    const height = dimensions?.height ?? video.videoHeight;
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

const isResumeKnowledgeRequest = (value: string): boolean =>
  /\b(resume|profile|experience|project|skills?|education|background|career|rag|introduce|answer)\b/i.test(
    value,
  );

const getDelta = (event: BackendEvent): string | undefined => {
  const delta = event.payload.delta;
  return typeof delta === "string" ? delta : undefined;
};

/** Keep transport or OCR duplication from appearing in the streamed UI. */
const collapseAdjacentDuplicateWords = (value: string): string => {
  let normalized = value;
  let previous: string | undefined;
  const duplicateWord = /\b([A-Za-z0-9][A-Za-z0-9'-]*)\b(\s+)\1\b/gi;
  while (normalized !== previous) {
    previous = normalized;
    normalized = normalized.replace(duplicateWord, "$1");
  }
  return normalized;
};

/** Compact, draggable ChatGPT-style meeting-assistance overlay. */
export const OverlayApp = (): ReactElement => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState<BackendConnectionStatus>("connecting");
  const [preferences, setPreferences] = useState(defaultPreferences);
  const [isListening, setIsListening] = useState(false);
  const [systemAudioSessionId, setSystemAudioSessionId] = useState<string>();
  const [transcript, setTranscript] = useState("");
  const [activeSessionId, setActiveSessionId] = useState<string>();
  const [profileReady, setProfileReady] = useState(false);
  const [assistanceMode, setAssistanceMode] = useState<AssistanceMode>("meeting");
  const lastAutoAnsweredTranscript = useRef("");

  const appendAssistantMessage = (sessionId: string, delta: string): void => {
    setMessages((current) => {
      let index = -1;
      current.forEach((message, messageIndex) => {
        if (message.id === sessionId && message.role === "assistant") {
          index = messageIndex;
        }
      });
      if (index === -1) {
        return [...current, { id: sessionId, role: "assistant", content: delta }];
      }
      const next = [...current];
      next[index] = {
        ...next[index],
        content: collapseAdjacentDuplicateWords(next[index].content + delta),
      };
      return next;
    });
  };

  useEffect(() => {
    void window.desktopApi.getBackendStatus().then(setStatus);
    void window.desktopApi.getCandidateProfileReady().then(setProfileReady);
    const stopStatus = window.desktopApi.onBackendStatus(setStatus);
    const stopProfileStatus =
      window.desktopApi.onCandidateProfileStatus(setProfileReady);
    const stopPreferences = window.desktopApi.onOverlayPreferences(setPreferences);
    const stopEvents = window.desktopApi.onBackendEvent((event) => {
      if (event.event === "llm.token") {
        const delta = getDelta(event);
        if (delta) {
          appendAssistantMessage(
            event.sessionId,
            collapseAdjacentDuplicateWords(delta),
          );
          setActiveSessionId(event.sessionId);
        }
      }
      if (event.event === "speech.final" && typeof event.payload.text === "string") {
        const label =
          event.payload.source === "system-audio" ? "Other speaker" : "Speaker";
        setTranscript(
          (current) =>
            `${current}${current ? "\n" : ""}${label}: ${event.payload.text}`,
        );
      }
      if (event.event === "system_audio.started") {
        setIsListening(true);
      }
      if (event.event === "system_audio.stopped") {
        setIsListening(false);
        setSystemAudioSessionId(undefined);
      }
      if (event.event === "llm.completed" && event.sessionId === activeSessionId) {
        setActiveSessionId(undefined);
      }
      if (event.event === "protocol.error") {
        const code = event.payload.code;
        if (typeof code === "string") {
          setMessages((current) => [
            ...current,
            {
              id: `error-${event.requestId}`,
              role: "assistant",
              content: `Error: ${code}`,
            },
          ]);
        }
      }
    });
    return () => {
      stopStatus();
      stopProfileStatus();
      stopPreferences();
      stopEvents();
    };
  }, [activeSessionId]);

  const sendChat = useCallback(
    async (
      instruction: string,
      includeCandidateProfile = profileReady,
      visibleMessage = instruction,
    ): Promise<void> => {
      const normalizedInstruction = instruction.trim();
      if (!normalizedInstruction) {
        return;
      }
      if (
        !profileReady &&
        (includeCandidateProfile || isResumeKnowledgeRequest(normalizedInstruction))
      ) {
        setMessages((current) => [
          ...current,
          {
            id: `profile-not-ready-${Date.now()}`,
            role: "assistant",
            content:
              "Resume knowledge is not loaded. In Dashboard, upload and parse your PDF, then select Start session before asking about your profile.",
          },
        ]);
        return;
      }
      const sessionId = await window.desktopApi.startSession(
        normalizedInstruction,
        includeCandidateProfile,
      );
      setMessages((current) => [
        ...current,
        { id: `user-${sessionId}`, role: "user", content: visibleMessage },
        { id: sessionId, role: "assistant", content: "" },
      ]);
      setActiveSessionId(sessionId);
      setDraft("");
    },
    [profileReady],
  );

  useEffect(() => {
    if (assistanceMode !== "mock-interview" || !profileReady) {
      return;
    }
    const latest = transcript.split("\n").filter(Boolean).at(-1);
    if (
      !latest?.startsWith("Other speaker:") ||
      latest === lastAutoAnsweredTranscript.current
    ) {
      return;
    }
    lastAutoAnsweredTranscript.current = latest;
    void sendChat(buildMockInterviewPrompt(latest), true, latest).catch(
      (error: unknown) => {
        setMessages((current) => [
          ...current,
          {
            id: `error-${Date.now()}`,
            role: "assistant",
            content:
              error instanceof Error
                ? error.message
                : "Unable to generate the practice answer.",
          },
        ]);
      },
    );
  }, [assistanceMode, profileReady, sendChat, transcript]);
  const onSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    void sendChat(draft).catch((error: unknown) => {
      setMessages((current) => [
        ...current,
        {
          id: `error-${Date.now()}`,
          role: "assistant",
          content: error instanceof Error ? error.message : "Unable to send message.",
        },
      ]);
    });
  };

  const onComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>): void => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  };

  const toggleListening = async (): Promise<void> => {
    try {
      if (isListening && systemAudioSessionId) {
        await window.desktopApi.stopSystemAudio(systemAudioSessionId);
        return;
      }
      const sessionId = await window.desktopApi.startSystemAudio();
      setSystemAudioSessionId(sessionId);
      setIsListening(true);
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          id: `error-${Date.now()}`,
          role: "assistant",
          content:
            error instanceof Error ? error.message : "Unable to start listening.",
        },
      ]);
    }
  };

  const analyzeScreen = async (): Promise<void> => {
    try {
      setMessages((current) => [
        ...current,
        {
          id: `screen-${Date.now()}`,
          role: "user",
          content: "Analyze and solve the selected screen.",
        },
      ]);
      const image = await captureDisplay();
      await window.desktopApi.sendScreenCapture(image, "image/jpeg");
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          id: `error-${Date.now()}`,
          role: "assistant",
          content: error instanceof Error ? error.message : "Unable to analyze screen.",
        },
      ]);
    }
  };

  return (
    <main className="overlay-shell" style={{ fontSize: preferences.fontSize }}>
      <section className="overlay-card">
        <header className="drag-region overlay-header">
          <button
            className="overlay-hide-button no-drag"
            onClick={() => void window.desktopApi.hideOverlay()}
            type="button"
          >
            Hide
          </button>
          <span className="overlay-status">{status}</span>
          <span
            className={
              profileReady ? "profile-context-status ready" : "profile-context-status"
            }
          >
            Resume knowledge: {profileReady ? "Ready" : "Not loaded"}
          </span>
          <div className="no-drag overlay-header-actions">
            <button
              aria-label="Exit application"
              className="overlay-icon-button"
              onClick={() => void window.desktopApi.quit()}
              type="button"
            >
              Exit
            </button>
          </div>
        </header>
        <nav
          className="no-drag overlay-toolbar"
          aria-label="Meeting assistance controls"
        >
          <button
            className={
              assistanceMode === "meeting"
                ? "overlay-control active"
                : "overlay-control"
            }
            onClick={() => setAssistanceMode("meeting")}
            type="button"
          >
            Meeting
          </button>
          <button
            className={
              assistanceMode === "mock-interview"
                ? "overlay-control active"
                : "overlay-control"
            }
            disabled={!profileReady}
            onClick={() => {
              lastAutoAnsweredTranscript.current =
                transcript.split("\n").filter(Boolean).at(-1) ?? "";
              setAssistanceMode("mock-interview");
            }}
            title={
              profileReady
                ? "Practice answers grounded in the loaded resume"
                : "Upload and parse a resume before starting mock interview practice"
            }
            type="button"
          >
            Mock Interview
          </button>
          <button
            className={isListening ? "overlay-control active" : "overlay-control"}
            onClick={() => void toggleListening()}
            type="button"
          >
            {isListening ? "Stop Listening" : "Start Listening"}
          </button>

          <button
            className="overlay-control"
            onClick={() => void analyzeScreen()}
            type="button"
          >
            Analyse Screen
          </button>

          <button
            className="overlay-control"
            onClick={() => {
              setMessages([]);
              setTranscript("");
            }}
            type="button"
          >
            Clear
          </button>
        </nav>
        <section aria-label="Chat" className="overlay-chat">
          <div className="overlay-messages">
            {messages.map((message) => (
              <article className={`chat-message ${message.role}`} key={message.id}>
                <span className="chat-role">
                  {message.role === "user" ? "You" : "Copilot"}
                </span>
                {message.content ? (
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    rehypePlugins={[rehypeHighlight]}
                  >
                    {message.content}
                  </ReactMarkdown>
                ) : (
                  <span className="chat-typing">Thinkingâ€¦</span>
                )}
              </article>
            ))}
          </div>
          <form className="no-drag overlay-composer" onSubmit={onSubmit}>
            <textarea
              aria-label="Message Copilot"
              disabled={status !== "connected"}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={onComposerKeyDown}
              placeholder="Ask about your profile, screen, transcript, or a taskâ€¦"
              value={draft}
            />
            <button disabled={!draft.trim() || status !== "connected"} type="submit">
              Send
            </button>
          </form>
        </section>
      </section>
    </main>
  );
};
