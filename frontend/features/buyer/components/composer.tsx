"use client";

import { useState } from "react";
import { ArrowUp, Loader2, Mic, Square, X } from "lucide-react";
import type { Strings } from "../i18n";
import { cn } from "../types";
import type { VoiceAgent } from "../voice/use-voice-agent";

function statusLabel(t: Strings, voice: VoiceAgent): string | null {
  switch (voice.status) {
    case "connecting":
      return t.connecting;
    case "listening":
      return t.listening;
    case "sending":
      return t.sending;
    case "thinking":
      return t.thinking;
    case "speaking":
      return t.speaking;
    default:
      return null;
  }
}

function MicButton({ t, voice, disabled }: { t: Strings; voice: VoiceAgent; disabled: boolean }) {
  const busy = voice.status === "connecting" || voice.status === "sending" || voice.status === "thinking";
  const listening = voice.status === "listening";
  const speaking = voice.status === "speaking";
  const label = listening ? t.listening : speaking ? t.speaking : t.tapMic;
  return (
    <button
      type="button"
      onClick={() => void voice.toggle()}
      disabled={disabled || voice.status === "connecting" || voice.status === "sending"}
      aria-label={label}
      aria-pressed={listening}
      data-voice-status={voice.status}
      className={cn(
        "relative shrink-0 w-9 h-9 rounded-full flex items-center justify-center transition",
        listening && "bg-danger text-white",
        speaking && "bg-brand text-brand-foreground",
        !listening && !speaking && "text-muted-foreground hover:text-foreground hover:bg-muted",
        (disabled || busy) && "opacity-60",
      )}
    >
      {listening && (
        <span
          aria-hidden
          className="absolute inset-0 rounded-full bg-danger/35"
          style={{ transform: `scale(${1 + voice.level * 0.9})`, transition: "transform 80ms linear" }}
        />
      )}
      <span className="relative">
        {busy ? <Loader2 className="w-5 h-5 animate-spin" /> : speaking ? <Square className="w-4 h-4" /> : <Mic className="w-5 h-5" />}
      </span>
    </button>
  );
}

export function Composer({
  t,
  disabled,
  showQuickReplies,
  onSend,
  voice,
}: {
  t: Strings;
  disabled: boolean;
  showQuickReplies: boolean;
  onSend: (text: string) => void;
  voice: VoiceAgent;
}) {
  const [input, setInput] = useState("");
  const canSend = Boolean(input.trim()) && !disabled;
  const status = statusLabel(t, voice);
  const voiceActive = voice.status !== "idle" && voice.status !== "error";

  const submit = () => {
    if (!canSend) return;
    if (voiceActive) voice.bargeIn();
    onSend(input);
    setInput("");
  };

  return (
    <div className="relative z-20 bg-gradient-to-t from-canvas via-canvas to-transparent pt-2">
      {showQuickReplies && (
        <div className="px-4 pt-1 sm:px-6">
          <div className="flex flex-wrap gap-2 max-w-3xl mx-auto">
            {t.quickReplies.map((reply) => (
              <button
                key={reply}
                type="button"
                onClick={() => onSend(reply)}
                className="px-3 py-1.5 bg-card border border-border text-foreground/80 text-[13px] rounded-full hover:border-ink/30 hover:text-foreground transition"
              >
                {reply}
              </button>
            ))}
          </div>
        </div>
      )}

      {(status || voice.error) && (
        <div className="px-4 pt-3 sm:px-6">
          <div className="max-w-3xl mx-auto flex items-center gap-2 text-xs" role="status" aria-live="polite">
            {voice.error ? (
              <div className="flex-1 flex items-center gap-2 px-3 py-2 rounded-lg bg-warning-soft text-warning border border-warning/20">
                <span className="flex-1">{t.voiceErrors[voice.error.code] ?? t.voiceErrors.unknown}</span>
                <button type="button" onClick={voice.dismissError} aria-label={t.close} className="p-1 rounded-md hover:bg-warning/10">
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ) : (
              <>
                <span className="flex items-center gap-2 text-muted-foreground">
                  {voice.status === "listening" && <span className="w-2 h-2 rounded-full bg-danger animate-pulse" />}
                  {(voice.status === "thinking" || voice.status === "sending" || voice.status === "connecting") && (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  )}
                  {status}
                </span>
                <span className="flex-1" />
                <label className="flex items-center gap-1.5 text-muted-foreground cursor-pointer select-none">
                  <input type="checkbox" checked={voice.handsFree} onChange={(e) => voice.setHandsFree(e.target.checked)} className="accent-brand" />
                  {t.handsFree}
                </label>
                <button type="button" onClick={voice.stopAll} className="px-2 py-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-surface transition">
                  {t.stopVoice}
                </button>
              </>
            )}
          </div>
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="px-4 pb-4 pt-3 sm:px-6"
      >
        <div
          className={cn(
            "flex items-end gap-1.5 max-w-3xl mx-auto rounded-2xl border bg-card px-2 py-1.5 shadow-composer transition focus-within:border-ink/30",
            voice.status === "listening" ? "border-danger/50" : "border-border",
          )}
        >
          <textarea
            value={input}
            dir="auto"
            rows={1}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder={voice.status === "listening" ? t.listening : t.inputPlaceholder}
            aria-label={t.inputPlaceholder}
            className="flex-1 max-h-40 min-h-[2.5rem] resize-none bg-transparent border-0 px-3 py-2 text-[15px] focus:outline-none placeholder:text-muted-foreground/80"
          />

          <MicButton t={t} voice={voice} disabled={disabled && !voiceActive} />

          <button
            type="submit"
            disabled={!canSend}
            aria-label={t.send}
            className={cn(
              "shrink-0 w-9 h-9 rounded-full flex items-center justify-center transition",
              canSend ? "bg-ink text-white hover:bg-ink/90" : "bg-muted text-muted-foreground/60",
            )}
          >
            <ArrowUp className="w-5 h-5" />
          </button>
        </div>
      </form>
    </div>
  );
}
