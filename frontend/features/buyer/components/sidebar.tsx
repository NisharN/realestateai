"use client";

import { Building2, Home, MapPin, Mic, Sparkles } from "lucide-react";
import type { Strings } from "../i18n";

const AREAS = ["Downtown Dubai", "Dubai Marina", "Palm Jumeirah", "Business Bay"];
const BUDGETS = ["1-3M", "3-5M", "5M+"];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">{title}</h3>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

const itemClass = "w-full text-start px-3 py-2 text-sm text-muted-foreground hover:bg-surface rounded-lg transition flex items-center gap-2";

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
    <aside className="w-80 bg-card border-e border-border hidden lg:flex flex-col">
      <div className="p-4 border-b border-border">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-brand-gradient rounded-xl flex items-center justify-center">
            <Building2 className="w-5 h-5 text-brand-foreground" />
          </div>
          <div>
            <h1 className="font-bold text-foreground">{t.appName}</h1>
            <p className="text-xs text-muted-foreground">{t.poweredBy}</p>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {needsHuman && (
          <div className="mb-4 p-3 rounded-xl bg-success-soft border border-success/20 text-start" role="status">
            <div className="flex items-center gap-2 text-green-800 font-semibold text-sm mb-1">
              <Sparkles className="w-4 h-4" />
              {t.specialistRequested}
            </div>
            <p className="text-xs text-green-800">{t.specialistBody}</p>
          </div>
        )}

        <Section title={t.quickFilters}>
          {AREAS.map((area) => (
            <button key={area} type="button" onClick={() => onSend(t.showIn(area))} className={itemClass}>
              <MapPin className="w-3 h-3" />
              {area}
            </button>
          ))}
        </Section>

        <Section title={t.propertyTypes}>
          {t.propertyTypeList.map((type) => (
            <button key={type} type="button" onClick={() => onSend(t.wantType(type))} className={itemClass}>
              <Home className="w-3 h-3" />
              {type}
            </button>
          ))}
        </Section>

        <Section title={t.budgetTiers}>
          {BUDGETS.map((b) => (
            <button key={b} type="button" onClick={() => onSend(t.budgetBetween(b))} className={itemClass}>
              <span className="inline-block w-3 text-center text-muted-foreground">•</span>
              <span dir="ltr">AED {b}</span>
            </button>
          ))}
        </Section>
      </div>

      <div className="p-4 border-t border-border">
        <button
          type="button"
          onClick={onVoice}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-brand-gradient text-brand-foreground rounded-xl font-medium hover:opacity-90 transition"
        >
          <Mic className="w-4 h-4" />
          {t.voice}
        </button>
      </div>
    </aside>
  );
}
