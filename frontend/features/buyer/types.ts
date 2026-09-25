import type { AreaAnswer, PropertyCardDto } from "@/lib/api";

export type Language = "en" | "ar";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  properties?: Property[];
  area?: AreaAnswer;
  needsHuman?: boolean;
  timestamp: Date;
}

/** Everything here is stored inventory / offline gazetteer data — never invented client-side. */
export interface Property {
  id: string;
  title: string;
  area: string;
  price: number;
  bedrooms: number;
  bathrooms: number;
  size_sqft: number;
  images: string[];
  map_lat: number | null;
  map_lng: number | null;
  amenities: string[];
  match_score?: number;
}

export interface IntakeForm {
  first_name: string;
  phone: string;
  email: string;
  budget_min: string;
  budget_max: string;
  property_type: string;
  area_preference: string;
  timeline: string;
}

export const EMPTY_INTAKE: IntakeForm = {
  first_name: "",
  phone: "",
  email: "",
  budget_min: "",
  budget_max: "",
  property_type: "apartment",
  area_preference: "",
  timeline: "1-3_months",
};

export const toProperty = (p: PropertyCardDto): Property => ({
  id: String(p.property_id),
  title: p.title,
  area: p.area ?? "Dubai",
  price: p.price ?? 0,
  bedrooms: p.bedrooms ?? 0,
  bathrooms: p.bathrooms ?? 0,
  size_sqft: p.size_sqft ?? 0,
  images: p.image ? [p.image] : [],
  map_lat: p.lat,
  map_lng: p.lng,
  amenities: p.match_reasons ?? [],
});

export const cn = (...classes: (string | boolean | undefined | null)[]) =>
  classes.filter(Boolean).join(" ");
