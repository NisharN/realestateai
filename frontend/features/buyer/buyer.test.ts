import { describe, expect, it } from "vitest";
import { STRINGS, detectLanguage, dirFor, fmtAED } from "./i18n";
import { EMPTY_INTAKE, toProperty } from "./types";
import { toIngestInput } from "./use-buyer-chat";

describe("buyer i18n", () => {
  it("detects Arabic script including mixed input", () => {
    expect(detectLanguage("hello")).toBe("en");
    expect(detectLanguage("ابحث عن شقة")).toBe("ar");
    expect(detectLanguage("I want شقة in Marina")).toBe("ar");
  });

  it("maps language to document direction", () => {
    expect(dirFor("en")).toBe("ltr");
    expect(dirFor("ar")).toBe("rtl");
  });

  it("has every string in both languages", () => {
    expect(Object.keys(STRINGS.ar).sort()).toEqual(Object.keys(STRINGS.en).sort());
  });

  it("formats AED with western digits in both languages", () => {
    expect(fmtAED(2500000, "en")).toBe("AED 2,500,000");
    expect(fmtAED(2500000, "ar")).toBe("2,500,000 درهم");
  });
});

describe("buyer DTO mapping", () => {
  it("keeps null coordinates as null (never invents a location)", () => {
    const p = toProperty({
      property_id: "p1",
      title: "2BR",
      price: null,
      area: null,
      bedrooms: 2,
      bathrooms: null,
      size_sqft: null,
      image: null,
      lat: null,
      lng: null,
      match_reasons: [],
    });
    expect(p.map_lat).toBeNull();
    expect(p.map_lng).toBeNull();
    expect(p.images).toEqual([]);
    expect(p.area).toBe("Dubai");
  });

  it("builds the ingest payload from the intake form", () => {
    const input = toIngestInput(
      { ...EMPTY_INTAKE, phone: "+971501234567", budget_max: "2500000", area_preference: "Marina, JVC" },
      "ar",
      "hi",
    );
    expect(input).toMatchObject({
      source: "website",
      preferred_language: "ar",
      phone: "+971501234567",
      budget_max: 2500000,
      area_preference: ["Marina", "JVC"],
      message: "hi",
    });
    expect(input.first_name).toBeUndefined();
    expect(input.budget_min).toBeUndefined();
  });
});
