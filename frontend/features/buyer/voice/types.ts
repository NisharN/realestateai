export type VoiceStatus = "idle" | "connecting" | "listening" | "sending" | "thinking" | "speaking" | "error";

export type VoiceErrorCode =
  | "mic_denied"
  | "mic_not_found"
  | "mic_unsupported"
  | "mic_busy"
  | "stt_unavailable"
  | "stt_failed"
  | "tts_failed"
  | "connection_lost"
  | "audio_too_large"
  | "unknown";

export interface VoiceError {
  code: VoiceErrorCode;
  detail?: string;
}

/** Mirror of backend `VoiceConfig` (app/modules/voice/config.py). */
export interface VoiceRuntimeConfig {
  providers: { stt: string; tts: string; stt_available: boolean; tts_available: boolean };
  heartbeat_s: number;
  thinking_after_s: number;
  low_confidence: number;
  vad_silence_ms: number;
  vad_threshold: number;
  max_utterance_s: number;
  max_audio_bytes: number;
  max_text_chars: number;
  hands_free_default: boolean;
  audio_formats: string[];
  faults: string[];
}

export const DEFAULT_VOICE_CONFIG: VoiceRuntimeConfig = {
  providers: { stt: "none", tts: "browser", stt_available: false, tts_available: true },
  heartbeat_s: 20,
  thinking_after_s: 1.2,
  low_confidence: 0.6,
  vad_silence_ms: 900,
  vad_threshold: 0.015,
  max_utterance_s: 30,
  max_audio_bytes: 2 * 1024 * 1024,
  max_text_chars: 2000,
  hands_free_default: true,
  audio_formats: ["audio/webm", "audio/ogg", "audio/wav", "audio/mp4"],
  faults: [],
};
