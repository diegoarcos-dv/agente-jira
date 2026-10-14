import { useEffect, useRef } from "react";

const MIME_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
];

function supportedMimeType(): string | undefined {
  if (typeof MediaRecorder.isTypeSupported !== "function") return undefined;
  return MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type));
}

export function useVoiceRecorder({
  maxDurationSeconds,
  onStopped,
  onError,
}: {
  maxDurationSeconds: number;
  onStopped: (audio: Blob) => void;
  onError: (message: string) => void;
}) {
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<number | null>(null);
  const stopWatchdogRef = useRef<number | null>(null);
  const onStoppedRef = useRef(onStopped);
  const onErrorRef = useRef(onError);

  onStoppedRef.current = onStopped;
  onErrorRef.current = onError;

  function releaseStream() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    recorderRef.current = null;
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = null;
    if (stopWatchdogRef.current !== null) window.clearTimeout(stopWatchdogRef.current);
    stopWatchdogRef.current = null;
  }

  function requestStop(recorder: MediaRecorder): boolean {
    if (recorder.state !== "recording") return false;
    if (stopWatchdogRef.current !== null) window.clearTimeout(stopWatchdogRef.current);
    stopWatchdogRef.current = window.setTimeout(() => {
      if (recorderRef.current !== recorder) return;
      recorder.ondataavailable = null;
      recorder.onerror = null;
      recorder.onstop = null;
      releaseStream();
      onErrorRef.current("La grabación no pudo cerrarse. Inténtalo de nuevo.");
    }, 3_000);
    try {
      recorder.stop();
      return true;
    } catch {
      releaseStream();
      onErrorRef.current("La grabación no pudo cerrarse. Inténtalo de nuevo.");
      return false;
    }
  }

  async function start() {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      throw new Error("Este navegador no permite grabar audio.");
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = supportedMimeType();
    const recorder = mimeType
      ? new MediaRecorder(stream, { mimeType })
      : new MediaRecorder(stream);
    chunksRef.current = [];
    streamRef.current = stream;
    recorderRef.current = recorder;
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data);
    };
    recorder.onerror = () => {
      releaseStream();
      onErrorRef.current("La grabación de audio se interrumpió.");
    };
    recorder.onstop = () => {
      const type = recorder.mimeType || mimeType || "audio/webm";
      const audio = new Blob(chunksRef.current, { type });
      releaseStream();
      if (audio.size === 0) {
        onErrorRef.current("No se capturó audio. Inténtalo de nuevo.");
        return;
      }
      onStoppedRef.current(audio);
    };
    recorder.start();
    timerRef.current = window.setTimeout(() => {
      requestStop(recorder);
    }, maxDurationSeconds * 1000);
  }

  function stop(): boolean {
    const recorder = recorderRef.current;
    return recorder ? requestStop(recorder) : false;
  }

  useEffect(
    () => () => {
      const recorder = recorderRef.current;
      if (recorder) {
        recorder.ondataavailable = null;
        recorder.onerror = null;
        recorder.onstop = null;
        if (recorder.state === "recording") {
          try {
            recorder.stop();
          } catch {
            // La limpieza del stream sigue siendo suficiente al desmontar.
          }
        }
      }
      releaseStream();
    },
    [],
  );

  return { start, stop };
}
