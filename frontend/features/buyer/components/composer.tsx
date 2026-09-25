"use client";

import { useState } from "react";
import { Mic, Send } from "lucide-react";
import type { Strings } from "../i18n";
import { cn } from "../types";

export function Composer({
  t,
  disabled,
  showQuickReplies,
  onSend,
  onVoice,
}: {
  t: Strings;
  disabled: boolean;
  showQuickReplies: boolean;
  onSend: (text: string) => void;
  onVoice: () => void;
}) {
  const [input, setInput] = useState("");
  const canSend = Boolean(input.trim()) && !disabled;

  const submit = () => {
    if (!canSend) return;
    onSend(input);
    setInput("");
  };

  return (
    <>
      {showQuickReplies && (
        <div className="px-4 pb-2">
          <div className="flex flex-wrap gap-2">
            {t.quickReplies.map((reply) => (
              <button
                key={reply}
                type="button"
                onClick={() => onSend(reply)}
                className="px-3.5 py-1.5 bg-card border border-border text-foreground/80 text-xs font-medium rounded-full shadow-card hover:border-brand/30 hover:text-brand transition"
              >
                {reply}
              </button>
            ))}
          </div>
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="px-4 pb-4 pt-2"
      >
        <div className="flex items-center gap-1.5 max-w-4xl mx-auto rounded-2xl border border-border bg-card p-1.5 shadow-card focus-within:border-brand/40 focus-within:ring-2 focus-within:ring-brand/15 transition">
          <button type="button" onClick={onVoice} aria-label={t.voice} className="p-2.5 text-muted-foreground hover:text-brand hover:bg-brand/10 rounded-xl transition">
            <Mic className="w-5 h-5" />
          </button>

          <input
            type="text"
            value={input}
            dir="auto"
            onChange={(e) => setInput(e.target.value)}
            placeholder={t.inputPlaceholder}
            aria-label={t.inputPlaceholder}
            className="flex-1 px-2 py-2.5 bg-transparent border-0 text-sm focus:outline-none placeholder:text-muted-foreground/70"
          />

          <button
            type="submit"
            disabled={!canSend}
            aria-label={t.send}
            className={cn(
              "p-2.5 rounded-xl transition",
              canSend ? "bg-brand text-brand-foreground hover:bg-brand-2 shadow-card" : "bg-muted text-muted-foreground",
            )}
          >
            <Send className="w-5 h-5 rtl:-scale-x-100" />
          </button>
        </div>
      </form>
    </>
  );
}
