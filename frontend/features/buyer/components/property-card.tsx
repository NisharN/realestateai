"use client";

import { useState } from "react";
import { Bath, Bed, Heart, Image as ImageIcon, MapPin, Maximize } from "lucide-react";
import { fmtAED, type Strings } from "../i18n";
import { cn, type Language, type Property } from "../types";

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
    <article
      className="group/card flex flex-col overflow-hidden rounded-xl border border-border bg-card transition-shadow hover:shadow-card-hover"
      data-testid="property-card"
    >
      <div className="relative aspect-[16/10] bg-muted">
        {image && !imageBroken ? (
          <img src={image} alt={property.title} loading="lazy" decoding="async" className="absolute inset-0 h-full w-full object-cover" onError={() => setImageBroken(true)} />
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-xs text-muted-foreground">
            <ImageIcon className="h-5 w-5" />
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
          className="absolute end-2 top-2 flex h-8 w-8 items-center justify-center rounded-full bg-card/90 shadow-card backdrop-blur transition hover:bg-card disabled:cursor-default"
        >
          <Heart className={cn("h-4 w-4", isLiked ? "fill-danger text-danger" : "text-foreground/70")} />
        </button>
        {property.match_score != null && (
          <span className="tabular absolute start-2 top-2 rounded-md bg-ink/85 px-2 py-0.5 text-[11px] font-medium text-white backdrop-blur">
            {property.match_score}% {t.match}
          </span>
        )}
      </div>

      <div className="flex flex-1 flex-col p-3.5">
        <p className="tabular text-[17px] font-semibold leading-none text-foreground">{fmtAED(property.price, lang)}</p>
        <h3 className="mt-1.5 line-clamp-2 text-[13px] font-medium leading-snug text-foreground">{property.title}</h3>
        <p className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
          <MapPin className="h-3 w-3" />
          {property.area}
        </p>

        <dl className="tabular mt-3 flex items-center gap-3 text-xs text-muted-foreground">
          <div className="flex items-center gap-1">
            <Bed className="h-3.5 w-3.5" />
            <dd>{property.bedrooms} {t.br}</dd>
          </div>
          <div className="flex items-center gap-1">
            <Bath className="h-3.5 w-3.5" />
            <dd>{property.bathrooms} {t.ba}</dd>
          </div>
          <div className="flex items-center gap-1">
            <Maximize className="h-3.5 w-3.5" />
            <dd>{property.size_sqft.toLocaleString("en-US")} {t.sqft}</dd>
          </div>
        </dl>

        {property.amenities.length > 0 && (
          <p className="mt-2 truncate text-xs text-muted-foreground">{property.amenities.slice(0, 3).join(" · ")}</p>
        )}

        <div className="mt-auto flex items-center gap-2 pt-3">
          <button
            type="button"
            disabled={busy}
            onClick={() => void onAsk(t.askAboutText(property.title), property.id)}
            className="ui-btn-primary ui-btn-sm flex-1"
          >
            {t.askAbout}
          </button>
          <button
            type="button"
            aria-label={t.viewOnMap}
            onClick={() => onViewMap(property)}
            disabled={!hasCoords}
            className="ui-btn-secondary ui-btn-sm px-2.5"
          >
            <MapPin className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </article>
  );
}
