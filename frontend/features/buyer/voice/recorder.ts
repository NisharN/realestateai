import type { VoiceError, VoiceRuntimeConfig } from "./types";

export interface Utterance {
  blob: Blob;
  mime: string;
  durationMs: number;
}

export interface RecorderCallbacks {
  onLevel?: (level: number) => void;
  onSpeechStart?: () => void;
  /** Fired once per start(): auto-stop (VAD / max duration) or explicit stop(). */
  onUtterance: (u: Utterance) => void;
  onError: (e: VoiceError) => void;
}

const PREFERRED_MIMES = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];

export function pickMimeType(formats: string[]): string {
  if (typeof MediaRecorder === "undefined") return "";
  const allowed = new Set(formats.map((f) => f.split(";")[0]));
  for (const m of PREFERRED_MIMES) {
    if (allowed.has(m.split(";")[0]) && MediaRecorder.isTypeSupported(m)) return m;
  }
  return "";
}

export function mapMicError(err: unknown): VoiceError {
  const name = err instanceof Error ? err.name : "";
  const detail = err instanceof Error ? err.message : undefined;
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
    case "PermissionDeniedError":
      return { code: "mic_denied", detail };
    case "NotFoundError":
    case "DevicesNotFoundError":
    case "OverconstrainedError":
      return { code: "mic_not_found", detail };
    case "NotReadableError":
    case "AbortError":
    case "TrackStartError":
      return { code: "mic_busy", detail };
    default:
      return { code: "unknown", detail };
  }
}

export function micSupported(): boolean {
  return (
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== "undefined"
  );
}

/**
 * One utterance = one start()/stop() cycle. Energy-based VAD (RMS over an
 * AnalyserNode) ends the utterance after `vad_silence_ms` of silence once
 * speech was heard, or after `max_utterance_s` regardless.
 */
export class MicRecorder {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private audioCtx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private raf: number | null = null;
  private maxTimer: ReturnType<typeof setTimeout> | null = null;
  private chunks: Blob[] = [];
  private startedAt = 0;
  private heardSpeech = false;
  private silentSince: number | null = null;
  private delivered = false;
  private mime = "";

  constructor(private config: VoiceRuntimeConfig, private cb: RecorderCallbacks) {}

  get active(): boolean {
    return this.recorder?.state === "recording";
  }

  async start(): Promise<boolean> {
    if (this.active) return true;
    if (!micSupported()) {
      this.cb.onError({ code: "mic_unsupported" });
      return false;
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (err) {
      this.cb.onError(mapMicError(err));
      return false;
    }
    this.mime = pickMimeType(this.config.audio_formats);
    try {
      this.recorder = this.mime ? new MediaRecorder(this.stream, { mimeType: this.mime }) : new MediaRecorder(this.stream);
    } catch (err) {
      this.releaseStream();
      this.cb.onError(mapMicError(err));
      return false;
    }
    this.mime = this.recorder.mimeType || this.mime || "audio/webm";
    this.chunks = [];
    this.delivered = false;
    this.heardSpeech = false;
    this.silentSince = null;
    this.startedAt = performance.now();

    this.recorder.ondataavailable = (e) => {
      if (e.data.size > 0) this.chunks.push(e.data);
    };
    this.recorder.onstop = () => this.deliver();
    this.recorder.onerror = () => {
      this.cleanup();
      this.cb.onError({ code: "mic_busy" });
    };
    this.recorder.start(250);
    this.startVad();
    this.maxTimer = setTimeout(() => this.stop(), this.config.max_utterance_s * 1000);
    return true;
  }

  /** Ends the utterance; the blob is delivered through onUtterance. */
  stop(): void {
    if (this.recorder && this.recorder.state !== "inactive") {
      this.recorder.stop();
    } else {
      this.cleanup();
    }
  }

  /** Discards the current utterance without delivering it. */
  cancel(): void {
    this.delivered = true;
    if (this.recorder && this.recorder.state !== "inactive") this.recorder.stop();
    this.cleanup();
  }

  private startVad(): void {
    if (!this.stream || typeof AudioContext === "undefined") return;
    try {
      this.audioCtx = new AudioContext();
      const src = this.audioCtx.createMediaStreamSource(this.stream);
      this.analyser = this.audioCtx.createAnalyser();
      this.analyser.fftSize = 1024;
      src.connect(this.analyser);
    } catch {
      return;
    }
    const buf = new Float32Array(this.analyser.fftSize);
    const tick = () => {
      if (!this.analyser) return;
      this.analyser.getFloatTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
      const rms = Math.sqrt(sum / buf.length);
      this.cb.onLevel?.(Math.min(1, rms * 8));
      const now = performance.now();
      if (rms >= this.config.vad_threshold) {
        if (!this.heardSpeech) {
          this.heardSpeech = true;
          this.cb.onSpeechStart?.();
        }
        this.silentSince = null;
      } else if (this.heardSpeech) {
        this.silentSince ??= now;
        if (now - this.silentSince >= this.config.vad_silence_ms) {
          this.stop();
          return;
        }
      }
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  private deliver(): void {
    const durationMs = performance.now() - this.startedAt;
    const blob = new Blob(this.chunks, { type: this.mime });
    const heard = this.heardSpeech || !this.analyser;
    const already = this.delivered;
    this.cleanup();
    if (already) return;
    this.delivered = true;
    if (!heard || blob.size === 0) return;
    if (blob.size > this.config.max_audio_bytes) {
      this.cb.onError({ code: "audio_too_large" });
      return;
    }
    this.cb.onUtterance({ blob, mime: this.mime, durationMs });
  }

  private releaseStream(): void {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
  }

  private cleanup(): void {
    if (this.raf !== null) cancelAnimationFrame(this.raf);
    this.raf = null;
    if (this.maxTimer) clearTimeout(this.maxTimer);
    this.maxTimer = null;
    this.analyser = null;
    void this.audioCtx?.close().catch(() => undefined);
    this.audioCtx = null;
    this.releaseStream();
    this.recorder = null;
    this.cb.onLevel?.(0);
  }
}

export async function blobToBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, Array.from(bytes.subarray(i, i + chunk)));
  }
  return btoa(binary);
}
