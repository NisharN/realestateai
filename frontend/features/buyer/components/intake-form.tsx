"use client";

import { motion } from "framer-motion";
import { UserRound } from "lucide-react";
import type { Strings } from "../i18n";
import type { IntakeForm } from "../types";

const inputClass = "ui-input text-sm";

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
      className="border-b border-border bg-surface px-6 py-3 overflow-hidden"
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit();
        }}
        className="max-w-4xl"
        aria-label={t.intakeTitle}
      >
        <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <UserRound className="h-3.5 w-3.5" /> {t.intakeTitle}
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
          <p className="text-xs text-muted-foreground">{t.intakeSkipHint}</p>
          <button type="button" onClick={onSkip} className="text-xs text-foreground underline-offset-2 hover:underline">
            {t.skip}
          </button>
        </div>
      </form>
    </motion.div>
  );
}
