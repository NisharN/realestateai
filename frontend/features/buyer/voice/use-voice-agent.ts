"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { VoiceWebSocket, type AreaAnswer, type VoiceServerMessage } from "@/lib/api";
import { toProperty, type Language, type Property } from "../types";
import { PlaybackQueue } from "./playback";
import { MicRecorder, blobToBase64, micSupported, type Utterance } from "./recorder";
import { DEFAULT_VOICE_CONFIG, type VoiceError, type VoiceRuntimeConfig, type VoiceStatus } from "./types";

type ReplyMessage = Extract<VoiceServerMessage, { type: "reply" }>;

export interface VoiceAgentHandlers {
  /** Resolve (or create) the lead the socket should bind to. */
  ensureLead: () => Promise<string | null>;
  onUserTranscript: (text: string) => void;
  onAgentReply: (text: string, properties?: Property[], area?: AreaAnswer, language?: Language) => void;
  onLanguage?: (lang: Language) => void;
}

export interface VoiceAgent {
  status: VoiceStatus;
  error: VoiceError | null;
  level: number;
  handsFree: boolean;
  config: VoiceRuntimeConfig;
  supported: boolean;
  /** Mic button: idle→listen, listening→send, speaking/thinking→barge-in then listen. */
  toggle: () => Promise<void>;
  stopAll: () => void;
  setHandsFree: (on: boolean) => void;
  dismissError: () => void;
  /** Typed text from the composer while voice is active: barge in and keep the thread going. */
  bargeIn: () => void;
}

export function useVoiceAgent(handlers: VoiceAgentHandlers, language: Language): VoiceAgent {
  const [status, setStatus] = useState<VoiceStatus>("idle");
  const [error, setError] = useState<VoiceError | null>(null);
  const [level, setLevel] = useState(0);
  const [config, setConfig] = useState<VoiceRuntimeConfig>(DEFAULT_VOICE_CONFIG);
  const [handsFree, setHandsFreeState] = useState(DEFAULT_VOICE_CONFIG.hands_free_default);
  const [supported, setSupported] = useState(false);

  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;
  const languageRef = useRef(language);
  languageRef.current = language;
  const configRef = useRef(config);
  configRef.current = config;
  const handsFreeRef = useRef(handsFree);
  handsFreeRef.current = handsFree;
  const statusRef = useRef<VoiceStatus>("idle");
  const wsRef = useRef<VoiceWebSocket | null>(null);
  const wsLeadRef = useRef<string | null>(null);
  const readyRef = useRef<Promise<void> | null>(null);
  const readyResolveRef = useRef<() => void>(() => undefined);
  const recorderRef = useRef<MicRecorder | null>(null);
  const playbackRef = useRef<PlaybackQueue | null>(null);
  const sessionActiveRef = useRef(false);
  const lastTranscriptTurnRef = useRef<string | null>(null);

  const setStatusSafe = useCallback((s: VoiceStatus) => {
    statusRef.current = s;
    setStatus(s);
  }, []);

  const fail = useCallback(
    (e: VoiceError) => {
      setError(e);
      setStatusSafe("error");
    },
    [setStatusSafe],
  );

  const startListening = useCallback(async (keepError = false): Promise<boolean> => {
    const rec = recorderRef.current;
    if (!rec) return false;
    if (!keepError) setError(null);
    setStatusSafe("listening");
    const ok = await rec.start();
    if (!ok) return false;
    sessionActiveRef.current = true;
    return true;
  }, [setStatusSafe]);

  if (!playbackRef.current) {
    playbackRef.current = new PlaybackQueue({
      onStart: () => setStatusSafe("speaking"),
      onEnd: () => {
        if (statusRef.current !== "speaking") return;
        if (handsFreeRef.current && sessionActiveRef.current) void startListening();
        else setStatusSafe("idle");
      },
      onError: (e) => {
        // Reply text is already in the thread; surface why it was not spoken and keep going.
        setError(e);
        if (handsFreeRef.current && sessionActiveRef.current) void startListening(true);
        else setStatusSafe("idle");
      },
    });
  }

  const sendUtterance = useCallback(
    async (u: Utterance) => {
      const ws = wsRef.current;
      if (!ws) return;
      setStatusSafe("sending");
      const b64 = await blobToBase64(u.blob);
      if (!ws.sendAudio(b64, u.mime)) fail({ code: "connection_lost" });
    },
    [fail, setStatusSafe],
  );

  useEffect(() => {
    setSupported(micSupported());
  }, []);

  useEffect(() => {
    recorderRef.current?.cancel();
    recorderRef.current = new MicRecorder(config, {
      onLevel: setLevel,
      onUtterance: (u) => void sendUtterance(u),
      onError: (e) => {
        sessionActiveRef.current = false;
        fail(e);
      },
    });
  }, [config, fail, sendUtterance]);

  const handleMessage = useCallback(
    (data: VoiceServerMessage) => {
      const h = handlersRef.current;
      switch (data.type) {
        case "ready":
          if (data.config) {
            if (JSON.stringify(data.config) !== JSON.stringify(configRef.current)) setConfig(data.config);
            if (!data.resumed) setHandsFreeState(data.config.hands_free_default);
          }
          readyResolveRef.current();
          if (statusRef.current === "connecting") setStatusSafe("idle");
          break;
        case "transcript":
          lastTranscriptTurnRef.current = data.turn_id;
          h.onUserTranscript(data.text);
          break;
        case "thinking":
          if (statusRef.current === "sending") setStatusSafe("thinking");
          break;
        case "reply": {
          const msg: ReplyMessage = data;
          if (lastTranscriptTurnRef.current !== msg.turn_id && msg.user_text && !msg.stt_error) {
            h.onUserTranscript(msg.user_text);
          }
          lastTranscriptTurnRef.current = null;
          h.onAgentReply(msg.reply, (msg.properties || []).map(toProperty), msg.area ?? undefined, msg.language);
          if (msg.language) h.onLanguage?.(msg.language);
          if (msg.stt_error) {
            fail({ code: configRef.current.providers.stt_available ? "stt_failed" : "stt_unavailable", detail: msg.stt_error });
            sessionActiveRef.current = false;
            break;
          }
          if (msg.interrupted || msg.ended) {
            sessionActiveRef.current = false;
            if (statusRef.current !== "listening") setStatusSafe("idle");
            break;
          }
          playbackRef.current?.play({
            audio: msg.audio,
            audioFormat: msg.audio_format,
            text: msg.spoken_text || msg.reply,
            lang: msg.language ?? languageRef.current,
          });
          break;
        }
        case "cancelled":
          if (statusRef.current === "sending" || statusRef.current === "thinking") setStatusSafe("idle");
          break;
        case "error":
          if (data.code === "audio_too_large") fail({ code: "audio_too_large" });
          else if (!data.recoverable) fail({ code: "connection_lost", detail: data.code });
          else if (statusRef.current !== "listening") setStatusSafe("idle");
          break;
      }
    },
    [fail, setStatusSafe],
  );

  const ensureSocket = useCallback(
    async (leadId: string): Promise<boolean> => {
      if (wsRef.current && wsLeadRef.current === leadId) {
        if (readyRef.current) await readyRef.current;
        if (wsRef.current.connected) return true;
      }
      // No socket, a different lead, or a dead socket (retries exhausted): start a fresh one.
      wsRef.current?.disconnect();
      wsRef.current = null;
      setStatusSafe("connecting");
      readyRef.current = new Promise<void>((resolve) => {
        readyResolveRef.current = resolve;
      });
      const ws = new VoiceWebSocket(
        leadId,
        handleMessage,
        () => undefined,
        (state) => {
          if (state === "failed") {
            sessionActiveRef.current = false;
            recorderRef.current?.cancel();
            playbackRef.current?.stop();
            fail({ code: "connection_lost" });
          } else if (state === "reconnecting" && statusRef.current !== "error") {
            setStatusSafe("connecting");
          }
        },
      );
      wsRef.current = ws;
      wsLeadRef.current = leadId;
      await ws.connect();
      const timeout = new Promise<void>((resolve) => setTimeout(resolve, 8000));
      await Promise.race([readyRef.current, timeout]);
      if (!ws.connected) {
        fail({ code: "connection_lost" });
        return false;
      }
      return true;
    },
    [fail, handleMessage, setStatusSafe],
  );

  const bargeIn = useCallback(() => {
    playbackRef.current?.stop();
    wsRef.current?.interrupt();
  }, []);

  const stopAll = useCallback(() => {
    sessionActiveRef.current = false;
    recorderRef.current?.cancel();
    bargeIn();
    setStatusSafe("idle");
  }, [bargeIn, setStatusSafe]);

  const toggle = useCallback(async () => {
    const current = statusRef.current;
    if (current === "listening") {
      recorderRef.current?.stop();
      return;
    }
    if (current === "connecting" || current === "sending") return;
    if (current === "speaking" || current === "thinking") bargeIn();
    if (!micSupported()) {
      fail({ code: "mic_unsupported" });
      return;
    }
    const leadId = await handlersRef.current.ensureLead();
    if (!leadId) {
      fail({ code: "connection_lost", detail: "no lead" });
      return;
    }
    if (!(await ensureSocket(leadId))) return;
    if (!configRef.current.providers.stt_available) {
      fail({ code: "stt_unavailable" });
      return;
    }
    await startListening();
  }, [bargeIn, ensureSocket, fail, startListening]);

  const setHandsFree = useCallback((on: boolean) => {
    handsFreeRef.current = on;
    setHandsFreeState(on);
    if (!on) sessionActiveRef.current = false;
  }, []);

  const dismissError = useCallback(() => {
    setError(null);
    if (statusRef.current === "error") setStatusSafe("idle");
  }, [setStatusSafe]);

  useEffect(() => {
    return () => {
      recorderRef.current?.cancel();
      playbackRef.current?.stop();
      wsRef.current?.disconnect();
    };
  }, []);

  return {
    status,
    error,
    level,
    handsFree,
    config,
    supported,
    toggle,
    stopAll,
    setHandsFree,
    dismissError,
    bargeIn,
  };
}
