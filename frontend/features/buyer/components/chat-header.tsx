"use client";

import { Languages, Mic } from "lucide-react";
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
    <header className="flex h-14 items-center justify-between border-b border-border bg-canvas/90 px-4 backdrop-blur sm:px-6">
      <div className="flex items-center gap-2.5 leading-tight">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full rounded-full bg-success/50" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-success" />
        </span>
        <div>
          <h2 className="text-sm font-medium text-foreground">{t.assistant}</h2>
          <p className="text-[11px] text-muted-foreground" dir="ltr">
            {leadId ? `${t.lead} ${leadId.slice(0, 8)}` : t.online}
          </p>
        </div>
      </div>

      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={onToggleLanguage}
          lang={language === "en" ? "ar" : "en"}
          aria-label="Switch language / تغيير اللغة"
          className="ui-btn-ghost ui-btn-sm"
        >
          <Languages className="h-3.5 w-3.5" />
          {t.switchLanguage}
        </button>
        <button type="button" onClick={onVoice} aria-label={t.voice} className="lg:hidden ui-btn-ghost p-2">
          <Mic className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}
