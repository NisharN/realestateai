"use client";

import { motion } from "framer-motion";
import dynamic from "next/dynamic";
import { MapPin } from "lucide-react";
import type { AreaAnswer } from "@/lib/api";
import { fmtAED, type Strings } from "../i18n";
import type { Language } from "../types";

const InlineMap = dynamic(() => import("../maps/inline-map").then((m) => m.InlineMap), {
  ssr: false,
  loading: () => null,
});

export function AreaCard({ area, t, lang }: { area: AreaAnswer; t: Strings; lang: Language }) {
  const name = lang === "ar" && area.name_ar ? area.name_ar : area.name_en;
  const travelName = (x: { to_name_en: string; to_name_ar: string }) =>
    lang === "ar" && x.to_name_ar ? x.to_name_ar : x.to_name_en;

  return (
    <motion.article
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-card rounded-2xl shadow-lg overflow-hidden border border-border max-w-md"
      data-testid="area-card"
    >
      <InlineMap
        pins={[{ id: area.community_id, lat: area.lat, lng: area.lng, label: area.name_en, sublabel: area.name_ar }]}
        travel={area.travel.map((x) => ({
          to_id: x.to_id,
          to_lat: x.to_lat,
          to_lng: x.to_lng,
          label: travelName(x),
          minutes: x.minutes,
          approx: x.approx,
        }))}
        height={180}
        interactive
      />
      <div className="p-4">
        <div className="flex items-center gap-1 text-foreground font-semibold text-sm mb-2">
          <MapPin className="w-3.5 h-3.5 text-brand" />
          {name}
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground mb-3">
          <span>{t.listings(area.listing_count)}</span>
          {area.median_price != null && (
            <span>
              {t.median} {fmtAED(Math.round(area.median_price), lang)}
            </span>
          )}
          {area.median_price_psf != null && (
            <span>
              {Math.round(area.median_price_psf).toLocaleString("en-US")} {t.aedPerSqft}
            </span>
          )}
        </div>
        {area.travel.length > 0 && (
          <ul className="space-y-1 text-xs text-muted-foreground">
            {area.travel.map((x) => (
              <li key={x.to_id} className="flex justify-between gap-2">
                <span>{travelName(x)}</span>
                <span className="font-medium text-foreground whitespace-nowrap">
                  {x.approx ? "≈ " : ""}
                  {x.minutes} {t.min} · {x.km} {t.km}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </motion.article>
  );
}
