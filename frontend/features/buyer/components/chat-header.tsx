"use client";

import { Bot, Mic } from "lucide-react";
import type { Strings } from "../i18n";
import type { Language } from "../types";

export function ChatHeader({
  t,
  language,
  leadId,
  onToggleLanguage,
  onVoice,
}: {
  t: Strings;
  language: Language;
  leadId: string | null;
  onToggleLanguage: () => void;
  onVoice: () => void;
}) {
  return (
    <header className="bg-card/80 backdrop-blur border-b border-border px-6 h-16 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <div className="relative">
          <div className="w-10 h-10 bg-brand rounded-full flex items-center justify-center shadow-card">
            <Bot className="w-5 h-5 text-gold" />
          </div>
          <div className="absolute -bottom-0.5 -end-0.5 w-3 h-3 bg-success border-2 border-card rounded-full" />
        </div>
        <div className="leading-tight">
          <h2 className="font-semibold text-foreground">{t.assistant}</h2>
          <p className="text-xs text-success" dir="ltr">
            {leadId ? `${t.lead} ${leadId.slice(0, 8)}…` : t.online}
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onToggleLanguage}
          lang={language === "en" ? "ar" : "en"}
          aria-label="Switch language / تغيير اللغة"
          className="ui-btn-secondary ui-btn-sm"
        >
          {t.switchLanguage}
        </button>
        <button type="button" onClick={onVoice} aria-label={t.voice} className="lg:hidden ui-btn-ghost p-2">
          <Mic className="w-5 h-5" />
        </button>
      </div>
    </header>
  );
}
