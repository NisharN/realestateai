"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Bot, Mic, MicOff, X } from "lucide-react";
import { VoiceWebSocket, type AreaAnswer, type VoiceServerMessage } from "@/lib/api";
import type { Strings } from "../i18n";
import { cn, toProperty, type Language, type Property } from "../types";

type Status = "idle" | "listening" | "connecting" | "sending" | "thinking" | "speaking";
type ReplyMessage = Extract<VoiceServerMessage, { type: "reply" }>;

export function VoiceModal({
  isOpen,
  onClose,
  leadId,
  t,
  onAgentMessage,
}: {
  isOpen: boolean;
  onClose: () => void;
  leadId: string | null;
  t: Strings;
  onAgentMessage: (text: string, properties?: Property[], area?: AreaAnswer, language?: Language) => void;
}) {
  const onAgentMessageRef = useRef(onAgentMessage);
  onAgentMessageRef.current = onAgentMessage;
  const [transcript, setTranscript] = useState("");
  const [response, setResponse] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [recording, setRecording] = useState(false);
  const wsRef = useRef<VoiceWebSocket | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const stopPlayback = useCallback(() => {
    audioRef.current?.pause();
    audioRef.current = null;
    if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
  }, []);

  // Barge-in: stop whatever Ali is saying (server turn + local playback).
  const stopSpeaking = useCallback(() => {
    wsRef.current?.interrupt();
    stopPlayback();
  }, [stopPlayback]);

  const speak = useCallback((msg: ReplyMessage) => {
    if (msg.audio) {
      const el = new Audio(`data:${msg.audio_format || "audio/wav"};base64,${msg.audio}`);
      audioRef.current = el;
      el.onended = () => setStatus("idle");
      el.play().catch(() => setStatus("idle"));
      setStatus("speaking");
      return;
    }
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      const u = new SpeechSynthesisUtterance(msg.spoken_text || msg.reply);
      if (msg.language) u.lang = msg.language === "ar" ? "ar-AE" : "en-GB";
      u.onend = () => setStatus("idle");
      window.speechSynthesis.speak(u);
      setStatus("speaking");
      return;
    }
    setStatus("idle");
  }, []);

  useEffect(() => {
    if (!recording || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let animationId: number;
    const styles = getComputedStyle(document.documentElement);
    const c1 = `hsl(${styles.getPropertyValue("--brand")})`;
    const c2 = `hsl(${styles.getPropertyValue("--brand-2")})`;

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const bars = 30;
      const barWidth = canvas.width / bars;
      for (let i = 0; i < bars; i++) {
        const height = Math.random() * canvas.height * 0.8;
        const x = i * barWidth;
        const y = (canvas.height - height) / 2;
        const gradient = ctx.createLinearGradient(0, y, 0, y + height);
        gradient.addColorStop(0, c1);
        gradient.addColorStop(1, c2);
        ctx.fillStyle = gradient;
        ctx.fillRect(x + 2, y, barWidth - 4, height);
      }
      animationId = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(animationId);
  }, [recording]);

  useEffect(() => {
    if (!isOpen) return;
    if (!leadId) {
      setStatus("idle");
      return;
    }
    setStatus("connecting");
    const ws = new VoiceWebSocket(
      leadId,
      (data) => {
        switch (data.type) {
          case "ready":
            setStatus("idle");
            if (data.resumed && data.history?.length) {
              const last = data.history[data.history.length - 1];
              if (last.role === "assistant") setResponse(last.text);
            }
            break;
          case "transcript":
            setTranscript(data.text);
            break;
          case "thinking":
            setStatus("thinking");
            break;
          case "reply":
            setResponse(data.reply);
            onAgentMessageRef.current(
              data.reply,
              (data.properties || []).map(toProperty),
              data.area ?? undefined,
              data.language,
            );
            if (!data.interrupted) speak(data);
            break;
          case "cancelled":
          case "error":
            setStatus("idle");
            break;
        }
      },
      () => setStatus("idle"),
    );
    ws.connect();
    wsRef.current = ws;
    setStatus("idle");
    return () => {
      ws.disconnect();
      wsRef.current = null;
      stopPlayback();
    };
  }, [isOpen, leadId, speak, stopPlayback]);

  const startRecording = async () => {
    stopSpeaking();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      mr.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        const bytes = new Uint8Array(await blob.arrayBuffer());
        let binary = "";
        for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
        if (wsRef.current) {
          wsRef.current.sendAudio(btoa(binary));
          setStatus("sending");
        }
      };
      mr.start();
      mediaRecorderRef.current = mr;
      setRecording(true);
      setStatus("listening");
    } catch {
      setStatus("idle");
      setRecording(false);
    }
  };

  const stopRecording = () => {
    mediaRecorderRef.current?.stop();
    setRecording(false);
  };

  const sendText = (txt: string) => {
    if (!txt.trim()) return;
    stopSpeaking();
    setTranscript(txt);
    if (wsRef.current) {
      wsRef.current.sendText(txt);
      setStatus("sending");
    }
  };

  if (!isOpen) return null;

  const statusText =
    status === "listening"
      ? t.listening
      : status === "connecting"
        ? t.connecting
        : status === "sending" || status === "thinking"
          ? t.thinking
          : status === "speaking"
            ? t.speaking
            : leadId
              ? t.tapMic
              : t.needSession;
  const disabled = !leadId || status === "connecting";

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={t.voiceTitle}
    >
      <motion.div
        initial={{ scale: 0.9, y: 20 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.9, y: 20 }}
        className="bg-card rounded-3xl p-8 w-full max-w-md text-center relative"
      >
        <button type="button" aria-label={t.close} onClick={onClose} className="absolute top-4 end-4 p-2 text-muted-foreground hover:text-foreground">
          <X className="w-5 h-5" />
        </button>

        <div className="mb-6">
          <div className="w-20 h-20 mx-auto mb-4 bg-brand-gradient rounded-full flex items-center justify-center">
            <Bot className="w-10 h-10 text-brand-foreground" />
          </div>
          <h2 className="text-xl font-bold text-foreground">{t.voiceTitle}</h2>
          <p className="text-muted-foreground text-sm mt-1" aria-live="polite">
            {statusText}
          </p>
        </div>

        <canvas ref={canvasRef} width={300} height={80} className="mx-auto mb-6 rounded-xl bg-surface" />

        {transcript && (
          <div className="mb-4 p-3 bg-surface rounded-xl text-start">
            <p className="text-xs text-muted-foreground mb-1">{t.youSaid}</p>
            <p className="text-sm text-foreground">{transcript}</p>
          </div>
        )}

        {response && (
          <div className="mb-4 p-3 bg-brand/10 rounded-xl text-start">
            <p className="text-xs text-brand mb-1">{t.assistant}:</p>
            <p className="text-sm text-foreground">{response}</p>
          </div>
        )}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            const form = e.currentTarget;
            const v = String(new FormData(form).get("voice-text") || "");
            if (v.trim()) sendText(v);
            form.reset();
          }}
          className="mb-4"
        >
          <input
            name="voice-text"
            placeholder={t.orType}
            className="w-full px-3 py-2 text-sm border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-ring/30"
          />
        </form>

        <button
          type="button"
          onClick={() => (recording ? stopRecording() : startRecording())}
          disabled={disabled}
          aria-label={t.voice}
          className={cn(
            "w-16 h-16 rounded-full flex items-center justify-center transition-all shadow-lg mx-auto",
            recording ? "bg-red-500 hover:bg-red-600 shadow-red-200" : "bg-brand hover:opacity-90 shadow-brand/30",
            disabled && "opacity-50 cursor-not-allowed",
          )}
        >
          {recording ? <MicOff className="w-7 h-7 text-brand-foreground" /> : <Mic className="w-7 h-7 text-brand-foreground" />}
        </button>
      </motion.div>
    </motion.div>
  );
}
