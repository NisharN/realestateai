import { afterEach, describe, expect, it, vi } from "vitest";
import { PlaybackQueue, speechBudgetMs } from "./playback";
import { blobToBase64, mapMicError, MicRecorder, pickMimeType } from "./recorder";

class FakeUtterance {
  text: string;
  lang = "";
  voice: unknown = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: ((e: { error: string }) => void) | null = null;
  constructor(text: string) {
    this.text = text;
  }
}

function installSpeech(voices: { lang: string }[], behaviour: "ok" | "error" | "silent" | "stall") {
  const spoken: FakeUtterance[] = [];
  const synth = {
    speaking: false,
    getVoices: () => voices,
    cancel: vi.fn(),
    speak: (u: FakeUtterance) => {
      spoken.push(u);
      if (behaviour === "ok") {
        u.onstart?.();
        setTimeout(() => u.onend?.(), 0);
      } else if (behaviour === "error") {
        setTimeout(() => u.onerror?.({ error: "synthesis-failed" }), 0);
      } else if (behaviour === "stall") {
        synth.speaking = true;
        u.onstart?.();
      }
    },
  };
  vi.stubGlobal("speechSynthesis", synth);
  vi.stubGlobal("SpeechSynthesisUtterance", FakeUtterance);
  return { spoken, synth };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("mapMicError", () => {
  it("maps browser getUserMedia errors to visible codes", () => {
    const err = (name: string) => Object.assign(new Error("x"), { name });
    expect(mapMicError(err("NotAllowedError")).code).toBe("mic_denied");
    expect(mapMicError(err("NotFoundError")).code).toBe("mic_not_found");
    expect(mapMicError(err("NotReadableError")).code).toBe("mic_busy");
    expect(mapMicError(err("Weird")).code).toBe("unknown");
  });
});

describe("pickMimeType", () => {
  it("returns the first server-accepted container the recorder supports", () => {
    vi.stubGlobal("MediaRecorder", { isTypeSupported: (m: string) => m.startsWith("audio/webm") });
    expect(pickMimeType(["audio/webm", "audio/ogg"])).toBe("audio/webm;codecs=opus");
    expect(pickMimeType(["audio/ogg"])).toBe("");
  });
});

describe("blobToBase64", () => {
  it("round-trips bytes", async () => {
    const b64 = await blobToBase64(new Blob([new Uint8Array([0, 1, 2, 250, 255])]));
    expect(Array.from(atob(b64), (c) => c.charCodeAt(0))).toEqual([0, 1, 2, 250, 255]);
  });
});

describe("PlaybackQueue browser fallback", () => {
  it("settles with onEnd after a successful utterance", async () => {
    installSpeech([{ lang: "en-GB" }], "ok");
    const cb = { onStart: vi.fn(), onEnd: vi.fn(), onError: vi.fn() };
    const q = new PlaybackQueue(cb);
    q.play({ text: "hello", lang: "en" });
    expect(cb.onStart).toHaveBeenCalled();
    await new Promise((r) => setTimeout(r, 5));
    expect(cb.onEnd).toHaveBeenCalledTimes(1);
    expect(cb.onError).not.toHaveBeenCalled();
    expect(q.playing).toBe(false);
  });

  it("reports tts_failed on utterance error instead of hanging in speaking", async () => {
    installSpeech([{ lang: "en-US" }], "error");
    const cb = { onStart: vi.fn(), onEnd: vi.fn(), onError: vi.fn() };
    new PlaybackQueue(cb).play({ text: "hello", lang: "en" });
    await new Promise((r) => setTimeout(r, 5));
    expect(cb.onError).toHaveBeenCalledWith(expect.objectContaining({ code: "tts_failed" }));
    expect(cb.onEnd).not.toHaveBeenCalled();
  });

  it("fails fast when no voice exists for the language", () => {
    installSpeech([{ lang: "en-GB" }], "ok");
    const cb = { onStart: vi.fn(), onEnd: vi.fn(), onError: vi.fn() };
    new PlaybackQueue(cb).play({ text: "مرحبا", lang: "ar" });
    expect(cb.onError).toHaveBeenCalledWith(expect.objectContaining({ code: "tts_failed" }));
  });

  it("stop() during playback settles once via onEnd (barge-in)", () => {
    const { synth } = installSpeech([{ lang: "en-GB" }], "silent");
    const cb = { onStart: vi.fn(), onEnd: vi.fn(), onError: vi.fn() };
    const q = new PlaybackQueue(cb);
    q.play({ text: "long reply", lang: "en" });
    q.stop();
    q.stop();
    expect(synth.cancel).toHaveBeenCalled();
    expect(cb.onEnd).toHaveBeenCalledTimes(1);
  });

  it("watchdog reports engines that never start", () => {
    vi.useFakeTimers();
    installSpeech([{ lang: "en-GB" }], "silent");
    const cb = { onStart: vi.fn(), onEnd: vi.fn(), onError: vi.fn() };
    new PlaybackQueue(cb).play({ text: "x", lang: "en" });
    vi.advanceTimersByTime(4100);
    expect(cb.onError).toHaveBeenCalledWith(expect.objectContaining({ code: "tts_failed" }));
  });

  it("completion watchdog settles an utterance that starts but never ends", () => {
    vi.useFakeTimers();
    const { synth } = installSpeech([{ lang: "en-GB" }], "stall");
    const cb = { onStart: vi.fn(), onEnd: vi.fn(), onError: vi.fn() };
    new PlaybackQueue(cb).play({ text: "hello there", lang: "en" });
    expect(cb.onStart).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(speechBudgetMs("hello there") - 1);
    expect(cb.onError).not.toHaveBeenCalled();
    vi.advanceTimersByTime(2);
    expect(synth.cancel).toHaveBeenCalled();
    expect(cb.onError).toHaveBeenCalledWith(expect.objectContaining({ code: "tts_failed", detail: "synthesis did not finish" }));
    expect(cb.onEnd).not.toHaveBeenCalled();
  });
});

describe("MicRecorder start cancellation", () => {
  it("does not activate a microphone granted after stop()", async () => {
    const tracks = [{ stop: vi.fn() }];
    let grant: (s: unknown) => void = () => undefined;
    vi.stubGlobal("navigator", {
      mediaDevices: {
        getUserMedia: () => new Promise((resolve) => (grant = resolve)),
      },
    });
    vi.stubGlobal("MediaRecorder", Object.assign(vi.fn(), { isTypeSupported: () => true }));
    const cb = { onUtterance: vi.fn(), onError: vi.fn() };
    const rec = new MicRecorder(() => ({ audio_formats: ["audio/webm"], max_utterance_s: 30, vad_silence_ms: 900, vad_threshold: 0.01 }) as never, cb);
    const started = rec.start();
    rec.stop();
    grant({ getTracks: () => tracks });
    expect(await started).toBe(false);
    expect(tracks[0].stop).toHaveBeenCalled();
    expect(rec.active).toBe(false);
    expect(cb.onError).not.toHaveBeenCalled();
  });
});
