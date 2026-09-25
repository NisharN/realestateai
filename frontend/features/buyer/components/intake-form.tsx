"use client";

import { motion } from "framer-motion";
import { Sparkles } from "lucide-react";
import type { Strings } from "../i18n";
import type { IntakeForm } from "../types";

const inputClass =
  "px-3 py-2 text-sm border border-brand/30 rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-ring/30";

export function IntakeFormPanel({
  t,
  value,
  onChange,
  onSubmit,
  onSkip,
}: {
  t: Strings;
  value: IntakeForm;
  onChange: (next: IntakeForm) => void;
  onSubmit: () => void;
  onSkip: () => void;
}) {
  return (
    <motion.div
      initial={{ height: 0, opacity: 0 }}
      animate={{ height: "auto", opacity: 1 }}
      exit={{ height: 0, opacity: 0 }}
      className="bg-brand/5 border-b border-brand/10 px-6 py-4 overflow-hidden"
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit();
        }}
        className="max-w-4xl"
        aria-label={t.intakeTitle}
      >
        <div className="text-xs font-semibold text-brand uppercase tracking-wider mb-2 flex items-center gap-2">
          <Sparkles className="w-3 h-3" /> {t.intakeTitle}
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <input
            aria-label={t.firstName}
            placeholder={t.firstName}
            autoComplete="given-name"
            value={value.first_name}
            onChange={(e) => onChange({ ...value, first_name: e.target.value })}
            className={inputClass}
          />
          <input
            aria-label={t.phone}
            placeholder={t.phone}
            autoComplete="tel"
            inputMode="tel"
            dir="ltr"
            value={value.phone}
            onChange={(e) => onChange({ ...value, phone: e.target.value })}
            className={inputClass}
          />
          <input
            aria-label={t.budgetAED}
            placeholder={t.budgetAED}
            type="number"
            inputMode="numeric"
            dir="ltr"
            value={value.budget_max}
            onChange={(e) => onChange({ ...value, budget_max: e.target.value })}
            className={inputClass}
          />
          <input
            aria-label={t.areas}
            placeholder={t.areas}
            value={value.area_preference}
            onChange={(e) => onChange({ ...value, area_preference: e.target.value })}
            className={inputClass}
          />
        </div>
        <div className="flex items-center justify-between mt-2 gap-2">
          <p className="text-xs text-brand">{t.intakeSkipHint}</p>
          <button type="button" onClick={onSkip} className="text-xs text-brand hover:underline">
            {t.skip}
          </button>
        </div>
      </form>
    </motion.div>
  );
}
