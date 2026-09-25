"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import dynamic from "next/dynamic";
import { Bath, Bed, Heart, Image as ImageIcon, MapPin, Maximize } from "lucide-react";
import { fmtAED, type Strings } from "../i18n";
import { cn, type Language, type Property } from "../types";

const InlineMap = dynamic(() => import("../maps/inline-map").then((m) => m.InlineMap), {
  ssr: false,
  loading: () => null,
});

export function PropertyCard({
  property,
  t,
  lang,
  onViewMap,
  onAsk,
  busy = false,
}: {
  property: Property;
  t: Strings;
  lang: Language;
  onViewMap: (p: Property) => void;
  onAsk: (text: string, propertyId: string) => Promise<boolean>;
  busy?: boolean;
}) {
  const [imageBroken, setImageBroken] = useState(false);
  const [isLiked, setIsLiked] = useState(false);
  const image = property.images[0];
  const hasCoords = property.map_lat != null && property.map_lng != null;

  return (
    <motion.article
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-card rounded-2xl shadow-card hover:shadow-card-hover overflow-hidden border border-border max-w-md transition"
      data-testid="property-card"
    >
      <div className="relative h-48 bg-muted">
        {image && !imageBroken ? (
          <img src={image} alt={property.title} className="w-full h-full object-cover" onError={() => setImageBroken(true)} />
        ) : (
          <div className="w-full h-full flex flex-col items-center justify-center text-muted-foreground text-xs gap-1">
            <ImageIcon className="w-6 h-6" />
            {t.noPhoto}
          </div>
        )}
        <button
          type="button"
          aria-pressed={isLiked}
          aria-label={t.likeThis(property.title)}
          disabled={busy || isLiked}
          onClick={async () => {
            if (await onAsk(t.likeThis(property.title), property.id)) setIsLiked(true);
          }}
          className="absolute top-3 end-3 p-2 bg-card/90 backdrop-blur rounded-full hover:bg-card transition disabled:cursor-default"
        >
          <Heart className={cn("w-4 h-4", isLiked ? "fill-red-500 text-red-500" : "text-muted-foreground")} />
        </button>
        {property.match_score != null && (
          <div className="absolute top-3 start-3 px-2.5 py-1 bg-ink/80 backdrop-blur text-gold text-xs font-semibold rounded-full tabular">
            {property.match_score}% {t.match}
          </div>
        )}
      </div>

      <div className="p-4">
        <h3 className="font-semibold text-foreground text-[15px] leading-snug mb-1">{property.title}</h3>
        <div className="flex items-center gap-1 text-muted-foreground text-xs mb-3">
          <MapPin className="w-3 h-3" />
          {property.area}
        </div>

        <div className="flex items-center gap-4 text-xs text-muted-foreground mb-3">
          <span className="flex items-center gap-1">
            <Bed className="w-3 h-3" />
            {property.bedrooms} {t.br}
          </span>
          <span className="flex items-center gap-1">
            <Bath className="w-3 h-3" />
            {property.bathrooms} {t.ba}
          </span>
          <span className="flex items-center gap-1">
            <Maximize className="w-3 h-3" />
            {property.size_sqft.toLocaleString("en-US")} {t.sqft}
          </span>
        </div>

        {hasCoords && (
          <div className="mb-3">
            <InlineMap
              pins={[{ id: property.id, lat: property.map_lat!, lng: property.map_lng!, label: property.title, sublabel: property.area }]}
              height={120}
            />
          </div>
        )}

        {property.amenities.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-3">
            {property.amenities.slice(0, 3).map((a) => (
              <span key={a} className="px-2 py-0.5 bg-muted text-muted-foreground text-xs rounded-full">
                {a}
              </span>
            ))}
          </div>
        )}

        <div className="flex items-center justify-between">
          <span className="text-lg font-semibold text-foreground tabular">{fmtAED(property.price, lang)}</span>
          <div className="flex gap-2">
            <button
              type="button"
              aria-label={t.viewOnMap}
              onClick={() => onViewMap(property)}
              disabled={!hasCoords}
              className="p-2 text-muted-foreground hover:text-brand hover:bg-brand/10 rounded-lg transition disabled:opacity-40 disabled:hover:bg-transparent"
            >
              <MapPin className="w-4 h-4" />
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void onAsk(t.askAboutText(property.title), property.id)}
              className="px-3 py-1.5 bg-brand text-brand-foreground text-xs font-medium rounded-lg hover:bg-brand-2 transition disabled:opacity-40"
            >
              {t.askAbout}
            </button>
          </div>
        </div>
      </div>
    </motion.article>
  );
}
