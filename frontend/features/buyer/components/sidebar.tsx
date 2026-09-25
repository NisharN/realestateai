"use client";

import { Building2, Home, MapPin, Mic, Sparkles } from "lucide-react";
import type { Strings } from "../i18n";

const AREAS = ["Downtown Dubai", "Dubai Marina", "Palm Jumeirah", "Business Bay"];
const BUDGETS = ["1-3M", "3-5M", "5M+"];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <h3 className="text-[11px] font-semibold text-white/40 uppercase tracking-[0.14em] mb-2 px-3">{title}</h3>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

const itemClass =
  "w-full text-start px-3 py-2 text-sm text-white/70 hover:bg-white/10 hover:text-white rounded-lg transition flex items-center gap-2.5";

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
    <aside className="w-80 bg-ink-gradient text-white hidden lg:flex flex-col">
      <div className="px-5 h-16 flex items-center border-b border-white/10">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 bg-gold/90 rounded-xl flex items-center justify-center shadow-pop">
            <Building2 className="w-[18px] h-[18px] text-ink" />
          </div>
          <div className="leading-tight">
            <h1 className="font-semibold text-sm tracking-tight">{t.appName}</h1>
            <p className="text-[11px] text-white/45">{t.poweredBy}</p>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-5">
        {needsHuman && (
          <div className="mb-5 mx-1 p-3 rounded-xl bg-success/15 border border-success/30 text-start" role="status">
            <div className="flex items-center gap-2 text-success font-semibold text-sm mb-1">
              <Sparkles className="w-4 h-4" />
              {t.specialistRequested}
            </div>
            <p className="text-xs text-white/70">{t.specialistBody}</p>
          </div>
        )}

        <Section title={t.quickFilters}>
          {AREAS.map((area) => (
            <button key={area} type="button" onClick={() => onSend(t.showIn(area))} className={itemClass}>
              <MapPin className="w-3.5 h-3.5 text-gold/80" />
              {area}
            </button>
          ))}
        </Section>

        <Section title={t.propertyTypes}>
          {t.propertyTypeList.map((type) => (
            <button key={type} type="button" onClick={() => onSend(t.wantType(type))} className={itemClass}>
              <Home className="w-3.5 h-3.5 text-gold/80" />
              {type}
            </button>
          ))}
        </Section>

        <Section title={t.budgetTiers}>
          {BUDGETS.map((b) => (
            <button key={b} type="button" onClick={() => onSend(t.budgetBetween(b))} className={itemClass}>
              <span className="inline-block w-3 text-center text-gold">•</span>
              <span dir="ltr">AED {b}</span>
            </button>
          ))}
        </Section>
      </div>

      <div className="p-4 border-t border-white/10">
        <button
          type="button"
          onClick={onVoice}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-gold text-ink rounded-xl font-semibold hover:brightness-105 transition shadow-pop"
        >
          <Mic className="w-4 h-4" />
          {t.voice}
        </button>
      </div>
    </aside>
  );
}
