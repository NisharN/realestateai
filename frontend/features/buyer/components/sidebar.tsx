"use client";

import { Building2, Home, MapPin, Mic, Sparkles, Wallet } from "lucide-react";
import type { Strings } from "../i18n";

const AREAS = ["Downtown Dubai", "Dubai Marina", "Palm Jumeirah", "Business Bay"];
const BUDGETS = ["1-3M", "3-5M", "5M+"];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-1 px-2.5 text-[11px] font-medium text-muted-foreground/80">{title}</h3>
      <div className="space-y-px">{children}</div>
    </div>
  );
}

const itemClass =
  "w-full text-start px-2.5 py-1.5 text-[13px] text-muted-foreground hover:bg-ink/[0.04] hover:text-foreground rounded-md transition-colors flex items-center gap-2.5";

export function Sidebar({
  t,
  needsHuman,
  onSend,
  onVoice,
}: {
  t: Strings;
  needsHuman: boolean;
  onSend: (text: string) => void;
  onVoice: () => void;
}) {
  return (
    <aside className="hidden lg:flex w-64 shrink-0 flex-col border-e border-border bg-surface">
      <div className="flex h-14 items-center gap-2.5 px-4">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-ink">
          <Building2 className="h-3.5 w-3.5 text-white" />
        </div>
        <div className="leading-tight">
          <h1 className="text-[13px] font-semibold tracking-tight text-foreground">{t.appName}</h1>
          <p className="text-[11px] text-muted-foreground">{t.poweredBy}</p>
        </div>
      </div>

      <div className="flex-1 space-y-5 overflow-y-auto px-3 py-3">
        {needsHuman && (
          <div className="mx-0.5 rounded-lg border border-success/25 bg-success-soft p-3 text-start" role="status">
            <div className="mb-1 flex items-center gap-2 text-[13px] font-medium text-success">
              <Sparkles className="h-3.5 w-3.5" />
              {t.specialistRequested}
            </div>
            <p className="text-xs leading-relaxed text-success/80">{t.specialistBody}</p>
          </div>
        )}

        <Section title={t.quickFilters}>
          {AREAS.map((area) => (
            <button key={area} type="button" onClick={() => onSend(t.showIn(area))} className={itemClass}>
              <MapPin className="h-3.5 w-3.5 text-muted-foreground/70" />
              {area}
            </button>
          ))}
        </Section>

        <Section title={t.propertyTypes}>
          {t.propertyTypeList.map((type) => (
            <button key={type} type="button" onClick={() => onSend(t.wantType(type))} className={itemClass}>
              <Home className="h-3.5 w-3.5 text-muted-foreground/70" />
              {type}
            </button>
          ))}
        </Section>

        <Section title={t.budgetTiers}>
          {BUDGETS.map((b) => (
            <button key={b} type="button" onClick={() => onSend(t.budgetBetween(b))} className={itemClass}>
              <Wallet className="h-3.5 w-3.5 text-muted-foreground/70" />
              <span dir="ltr">AED {b}</span>
            </button>
          ))}
        </Section>
      </div>

      <div className="border-t border-border p-3">
        <button
          type="button"
          onClick={onVoice}
          className="flex w-full items-center gap-2.5 rounded-md border border-border bg-card px-2.5 py-2 text-[13px] text-foreground transition-colors hover:bg-muted"
        >
          <Mic className="h-4 w-4 text-brand" />
          {t.voice}
        </button>
      </div>
    </aside>
  );
}
