import { useEffect, useRef, useState } from "react";

interface RecognitionAlternativeLike {
  transcript?: string;
}

interface RecognitionResultLike {
  isFinal?: boolean;
  length: number;
  [index: number]: RecognitionAlternativeLike;
}

interface RecognitionEventLike {
  results: ArrayLike<RecognitionResultLike>;
}

interface RecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start(): void;
  stop(): void;
  abort?(): void;
  onresult: ((event: RecognitionEventLike) => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onend: (() => void) | null;
}

type RecognitionCtor = new () => RecognitionLike;

function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const speechWindow = window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  };
  return speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition ?? null;
}

export function DictationButton({
  disabled,
  onTranscript,
  onError,
}: {
  disabled?: boolean;
  onTranscript: (text: string) => void;
  onError?: (detail: string) => void;
}) {
  const [supported] = useState(() => recognitionCtor() !== null);
  const [listening, setListening] = useState(false);
  const active = useRef<RecognitionLike | null>(null);

  useEffect(
    () => () => {
      active.current?.abort?.();
      active.current = null;
    },
    []
  );

  if (!supported) return null;

  const toggle = () => {
    if (listening) {
      active.current?.stop();
      return;
    }
    const Ctor = recognitionCtor();
    if (!Ctor) return;
    try {
      const recognition = new Ctor();
      active.current = recognition;
      recognition.lang = navigator.language || "zh-CN";
      recognition.interimResults = false;
      recognition.continuous = false;
      recognition.onresult = (event) => {
        const chunks: string[] = [];
        for (let i = 0; i < event.results.length; i += 1) {
          const result = event.results[i];
          if (result?.isFinal === false) continue;
          const transcript = result?.[0]?.transcript?.trim();
          if (transcript) chunks.push(transcript);
        }
        if (chunks.length) onTranscript(chunks.join(" "));
      };
      recognition.onerror = (event) => {
        setListening(false);
        onError?.(event.error ? `听写失败：${event.error}` : "听写失败");
      };
      recognition.onend = () => {
        active.current = null;
        setListening(false);
      };
      setListening(true);
      recognition.start();
    } catch (error) {
      active.current = null;
      setListening(false);
      onError?.(`听写启动失败：${error instanceof Error ? error.message : String(error)}`);
    }
  };

  return (
    <button
      type="button"
      className={`v2-icon-btn v2-dictation-btn ${listening ? "active" : ""}`}
      disabled={disabled}
      onClick={toggle}
      aria-label={listening ? "停止浏览器听写" : "开始浏览器听写"}
      title={listening ? "停止浏览器听写" : "开始浏览器听写"}
      data-testid="dictation-btn"
    >
      {listening ? "■" : "◉"}
    </button>
  );
}
