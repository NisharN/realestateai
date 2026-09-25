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
                className="px-3 py-1.5 bg-card border border-border text-muted-foreground text-xs rounded-full hover:bg-surface transition"
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
        className="bg-card border-t border-border px-4 py-3"
      >
        <div className="flex items-center gap-2 max-w-4xl mx-auto">
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
            className="flex-1 px-4 py-3 bg-surface border-0 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-ring/30 focus:bg-card transition"
          />

          <button
            type="submit"
            disabled={!canSend}
            aria-label={t.send}
            className={cn(
              "p-2.5 rounded-xl transition",
              canSend ? "bg-brand text-brand-foreground hover:opacity-90" : "bg-muted text-muted-foreground",
            )}
          >
            <Send className="w-5 h-5 rtl:-scale-x-100" />
          </button>
        </div>
      </form>
    </>
  );
}
