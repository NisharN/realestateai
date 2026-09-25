import type { VoiceError } from "./types";

export interface PlaybackItem {
  /** base64-encoded audio from the server (preferred). */
  audio?: string;
  audioFormat?: string;
  /** Text for browser speech synthesis when no server audio exists. */
  text: string;
  lang: "en" | "ar";
}

export interface PlaybackCallbacks {
  onStart: () => void;
  onEnd: () => void;
  onError: (e: VoiceError) => void;
}

export function browserTtsAvailable(lang: "en" | "ar"): boolean {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return false;
  const voices = window.speechSynthesis.getVoices();
  if (voices.length === 0) return false;
  const prefix = lang === "ar" ? "ar" : "en";
  return voices.some((v) => v.lang.toLowerCase().startsWith(prefix));
}

/** Generous upper bound for how long an utterance may take (~4 chars/s + slack). */
export function speechBudgetMs(text: string): number {
  return Math.min(120_000, 8_000 + text.length * 250);
}

/**
 * Plays one reply at a time. Server audio first; browser TTS as fallback.
 * Every path (ended, error, no voices, stop()) settles exactly once via
 * onEnd/onError so the UI can never be left in "speaking".
 */
export class PlaybackQueue {
  private el: HTMLAudioElement | null = null;
  private utterance: SpeechSynthesisUtterance | null = null;
  private settled = true;
  private watchdog: ReturnType<typeof setTimeout> | null = null;

  constructor(private cb: PlaybackCallbacks) {}

  get playing(): boolean {
    return !this.settled;
  }

  play(item: PlaybackItem): void {
    this.stop();
    this.settled = false;
    if (item.audio) {
      this.playServerAudio(item);
      return;
    }
    this.speakBrowser(item);
  }

  stop(): void {
    if (this.el) {
      this.el.onended = null;
      this.el.onerror = null;
      this.el.pause();
      this.el.src = "";
      this.el = null;
    }
    if (typeof window !== "undefined" && "speechSynthesis" in window && this.utterance) {
      this.utterance.onend = null;
      this.utterance.onerror = null;
      window.speechSynthesis.cancel();
    }
    this.utterance = null;
    this.clearWatchdog();
    if (!this.settled) {
      this.settled = true;
      this.cb.onEnd();
    }
  }

  private finish(err?: VoiceError): void {
    if (this.settled) return;
    this.settled = true;
    this.clearWatchdog();
    this.el = null;
    this.utterance = null;
    if (err) this.cb.onError(err);
    else this.cb.onEnd();
  }

  private clearWatchdog(): void {
    if (this.watchdog) clearTimeout(this.watchdog);
    this.watchdog = null;
  }

  private playServerAudio(item: PlaybackItem): void {
    const el = new Audio(`data:${item.audioFormat || "audio/wav"};base64,${item.audio}`);
    this.el = el;
    el.onended = () => this.finish();
    el.onerror = () => {
      this.el = null;
      this.settled = true;
      this.speakBrowser(item, true);
    };
    el.play()
      .then(() => this.cb.onStart())
      .catch(() => {
        this.el = null;
        this.settled = true;
        this.speakBrowser(item, true);
      });
  }

  private speakBrowser(item: PlaybackItem, afterServerFailure = false): void {
    this.settled = false;
    if (typeof window === "undefined" || !("speechSynthesis" in window)) {
      this.finish({ code: "tts_failed", detail: afterServerFailure ? "server audio failed; no speechSynthesis" : "no speechSynthesis" });
      return;
    }
    if (!browserTtsAvailable(item.lang)) {
      this.finish({ code: "tts_failed", detail: "no browser voices" });
      return;
    }
    const u = new SpeechSynthesisUtterance(item.text);
    u.lang = item.lang === "ar" ? "ar-AE" : "en-GB";
    const voice = window.speechSynthesis.getVoices().find((v) => v.lang.toLowerCase().startsWith(item.lang));
    if (voice) u.voice = voice;
    u.onstart = () => {
      this.clearWatchdog();
      // Engines can stall after onstart without ever firing onend/onerror.
      this.watchdog = setTimeout(() => {
        if (this.settled) return;
        window.speechSynthesis.cancel();
        this.finish({ code: "tts_failed", detail: "synthesis did not finish" });
      }, speechBudgetMs(item.text));
      this.cb.onStart();
    };
    u.onend = () => this.finish();
    u.onerror = (e) => {
      if (e.error === "interrupted" || e.error === "canceled") this.finish();
      else this.finish({ code: "tts_failed", detail: e.error });
    };
    this.utterance = u;
    // Some engines never fire onstart/onend when they silently fail.
    this.watchdog = setTimeout(() => {
      if (!this.settled && !window.speechSynthesis.speaking) this.finish({ code: "tts_failed", detail: "synthesis did not start" });
    }, 4000);
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  }
}
