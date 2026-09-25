"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { leadsApi, type AreaAnswer, type LeadIngestInput } from "@/lib/api";
import { STRINGS, detectLanguage } from "./i18n";
import { EMPTY_INTAKE, toProperty, type IntakeForm, type Language, type Message, type Property } from "./types";

let seq = 0;
const nextId = () => `${Date.now()}-${++seq}`;

const assistantMessage = (content: string, extra: Partial<Message> = {}): Message => ({
  id: nextId(),
  role: "assistant",
  content,
  timestamp: new Date(),
  ...extra,
});

export function toIngestInput(form: IntakeForm, language: Language, message?: string): LeadIngestInput {
  return {
    source: "website",
    preferred_language: language,
    first_name: form.first_name || undefined,
    phone: form.phone || undefined,
    email: form.email || undefined,
    budget_min: form.budget_min ? Number(form.budget_min) : undefined,
    budget_max: form.budget_max ? Number(form.budget_max) : undefined,
    property_type: form.property_type,
    area_preference: form.area_preference
      ? form.area_preference.split(",").map((s) => s.trim()).filter(Boolean)
      : [],
    timeline: form.timeline,
    message: message || undefined,
  };
}

export function useBuyerChat(initialLanguage: Language = "en") {
  const [language, setLanguageState] = useState<Language>(initialLanguage);
  const [messages, setMessages] = useState<Message[]>([
    { ...assistantMessage(STRINGS[initialLanguage].welcome), id: "welcome" },
  ]);
  const [isLoading, setIsLoading] = useState(false);
  const [leadId, setLeadId] = useState<string | null>(null);
  const [needsHuman, setNeedsHuman] = useState(false);
  const [ended, setEnded] = useState(false);
  const [showIntake, setShowIntake] = useState(true);
  const [intake, setIntake] = useState<IntakeForm>(EMPTY_INTAKE);
  const [mapProperties, setMapProperties] = useState<Property[]>([]);

  const t = STRINGS[language];

  const setLanguage = useCallback((lang: Language) => {
    setLanguageState(lang);
    setMessages((prev) =>
      prev.map((m) => (m.id === "welcome" ? { ...m, content: STRINGS[lang].welcome } : m)),
    );
  }, []);

  useEffect(() => {
    if (typeof document === "undefined") return;
    document.documentElement.lang = language;
    document.documentElement.dir = language === "ar" ? "rtl" : "ltr";
    return () => {
      document.documentElement.lang = "en";
      document.documentElement.dir = "ltr";
    };
  }, [language]);

  const push = useCallback((m: Message) => setMessages((prev) => [...prev, m]), []);

  const continueChat = useCallback(
    async (id: string, text: string, propertyId?: string) => {
      const result = await leadsApi.sendMessage(id, propertyId ? { text, property_id: propertyId } : { text });
      if (result.error || !result.data) {
        push(assistantMessage(t.backendError(result.error ?? "unknown")));
        return;
      }
      const data = result.data;
      const properties = (data.matched_properties || []).map(toProperty);
      if (properties.length) setMapProperties(properties);
      if (data.language === "ar" || data.language === "en") setLanguageState(data.language);
      push(
        assistantMessage(data.response, {
          properties: properties.length ? properties : undefined,
          area: data.area ?? undefined,
          needsHuman: data.needs_human,
        }),
      );
      if (data.needs_human) setNeedsHuman(true);
      if (data.ended) setEnded(true);
    },
    [push, t],
  );

  const sendMessage = useCallback(
    async (text: string, propertyId?: string): Promise<boolean> => {
      const trimmed = text.trim();
      if (!trimmed || isLoading) return false;
      const lang = detectLanguage(trimmed) === "ar" ? "ar" : language;
      if (lang !== language) setLanguageState(lang);
      push({ id: nextId(), role: "user", content: trimmed, timestamp: new Date() });
      setIsLoading(true);
      try {
        if (!leadId) {
          const ingest = await leadsApi.ingest(toIngestInput(intake, lang));
          if (!ingest.data) {
            push(assistantMessage(t.backendError(ingest.error ?? "unknown")));
            return false;
          }
          const id = ingest.data.lead_id;
          setLeadId(id);
          setShowIntake(false);
          await continueChat(id, trimmed);
          return true;
        }
        await continueChat(leadId, trimmed, propertyId);
        return true;
      } finally {
        setIsLoading(false);
      }
    },
    [continueChat, intake, isLoading, language, leadId, push, t],
  );

  const submitIntake = useCallback(
    async (firstMessage: string) => {
      setIsLoading(true);
      try {
        const result = await leadsApi.ingest(toIngestInput(intake, language));
        if (result.error || !result.data) {
          push(assistantMessage(t.registerError(result.error ?? "unknown")));
          return;
        }
        const id = result.data.lead_id;
        setLeadId(id);
        setShowIntake(false);
        if (firstMessage.trim()) {
          push({ id: nextId(), role: "user", content: firstMessage.trim(), timestamp: new Date() });
          await continueChat(id, firstMessage.trim());
        } else {
          push(assistantMessage(t.registered));
        }
      } finally {
        setIsLoading(false);
      }
    },
    [continueChat, intake, language, push, t],
  );

  const leadIdRef = useRef<string | null>(null);
  leadIdRef.current = leadId;
  const leadPromiseRef = useRef<Promise<string | null> | null>(null);

  /** Lead the voice socket binds to; registers one from the intake form on first use. */
  const ensureLead = useCallback(async (): Promise<string | null> => {
    if (leadIdRef.current) return leadIdRef.current;
    if (leadPromiseRef.current) return leadPromiseRef.current;
    leadPromiseRef.current = (async () => {
      const result = await leadsApi.ingest(toIngestInput(intake, language));
      if (result.error || !result.data) {
        push(assistantMessage(t.registerError(result.error ?? "unknown")));
        return null;
      }
      const id = result.data.lead_id;
      leadIdRef.current = id;
      setLeadId(id);
      setShowIntake(false);
      return id;
    })().finally(() => {
      leadPromiseRef.current = null;
    });
    return leadPromiseRef.current;
  }, [intake, language, push, t]);

  const onVoiceTranscript = useCallback(
    (text: string) => {
      push({ id: nextId(), role: "user", content: text, timestamp: new Date() });
    },
    [push],
  );

  const onVoiceReply = useCallback(
    (text: string, properties?: Property[], area?: AreaAnswer, lang?: Language) => {
      push(
        assistantMessage(text, {
          properties: properties && properties.length ? properties : undefined,
          area,
        }),
      );
      if (properties && properties.length) setMapProperties(properties);
      if (lang) setLanguageState(lang);
    },
    [push],
  );

  return {
    t,
    language,
    setLanguage,
    messages,
    isLoading,
    leadId,
    needsHuman,
    ended,
    showIntake,
    setShowIntake,
    intake,
    setIntake,
    mapProperties,
    setMapProperties,
    sendMessage,
    submitIntake,
    onVoiceReply,
    onVoiceTranscript,
    ensureLead,
  };
}
