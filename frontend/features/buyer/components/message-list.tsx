"use client";

import { useEffect, useRef } from "react";
import { Building2 } from "lucide-react";
import type { Strings } from "../i18n";
import { cn, type Language, type Message, type Property } from "../types";
import { AreaCard } from "./area-card";
import { PropertyCard } from "./property-card";

function AssistantMark() {
  return (
    <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-ink" aria-hidden>
      <Building2 className="h-3.5 w-3.5 text-white" />
    </div>
  );
}

function MessageBubble({
  message,
  first,
  t,
  lang,
  onViewMap,
  onAsk,
  busy,
}: {
  message: Message;
  first: boolean;
  t: Strings;
  lang: Language;
  onViewMap: (p: Property, all: Property[]) => void;
  onAsk: (text: string, propertyId: string) => Promise<boolean>;
  busy: boolean;
}) {
  const isUser = message.role === "user";
  const lines = message.content.split("\n");
  const time = message.timestamp.toLocaleTimeString(lang === "ar" ? "ar-AE" : [], { hour: "2-digit", minute: "2-digit" });

  if (isUser) {
    return (
      <div className="group flex justify-end" data-role={message.role}>
        <div className="max-w-[78%]">
          <div dir="auto" className="rounded-2xl rounded-ee-md bg-ink px-4 py-2.5 text-[15px] leading-relaxed text-white">
            {lines.map((line, i) => (
              <span key={i}>
                {line}
                {i < lines.length - 1 && <br />}
              </span>
            ))}
          </div>
          <p className="mt-1 text-end text-[11px] text-muted-foreground transition-colors [@media(hover:hover)]:text-muted-foreground/0 [@media(hover:hover)]:group-hover:text-muted-foreground" dir="ltr">
            {time}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="group flex gap-3" data-role={message.role}>
      <AssistantMark />
      <div className="min-w-0 flex-1 space-y-4">
        <div dir="auto" className="max-w-[68ch] text-[15px] leading-[1.65] text-foreground">
          {lines.map((line, i) => (
            <span
              key={i}
              className={cn(first && i === 0 && line.trim() && "font-display text-[22px] leading-[1.3] text-foreground")}
            >
              {line}
              {i < lines.length - 1 && <br />}
            </span>
          ))}
        </div>

        {message.area && <AreaCard area={message.area} t={t} lang={lang} />}

        {message.properties && message.properties.length > 0 && (
          <div className="grid gap-3 md:grid-cols-2">
            {message.properties.map((prop) => (
              <PropertyCard
                key={prop.id}
                property={prop}
                t={t}
                lang={lang}
                onViewMap={(p) => onViewMap(p, message.properties || [])}
                onAsk={onAsk}
                busy={busy}
              />
            ))}
          </div>
        )}

        <p className="text-[11px] text-muted-foreground transition-colors [@media(hover:hover)]:text-muted-foreground/0 [@media(hover:hover)]:group-hover:text-muted-foreground" dir="ltr">
          {time}
        </p>
      </div>
    </div>
  );
}

export function MessageList({
  messages,
  isLoading,
  t,
  lang,
  onViewMap,
  onAsk,
}: {
  messages: Message[];
  isLoading: boolean;
  t: Strings;
  lang: Language;
  onViewMap: (p: Property, all: Property[]) => void;
  onAsk: (text: string, propertyId: string) => Promise<boolean>;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-8 sm:px-6" role="log" aria-live="polite">
      <div className="mx-auto max-w-3xl space-y-7">
        {messages.map((m, i) => (
          <MessageBubble key={m.id} message={m} first={i === 0 && m.role === "assistant"} t={t} lang={lang} onViewMap={onViewMap} onAsk={onAsk} busy={isLoading} />
        ))}

        {isLoading && (
          <div className="flex items-center gap-3 text-sm text-muted-foreground" role="status">
            <AssistantMark />
            <span className="sr-only">{t.thinking}</span>
            <span className="flex items-center gap-1" aria-hidden="true">
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:-0.3s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60 [animation-delay:-0.15s]" />
              <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground/60" />
            </span>
          </div>
        )}
        <div ref={endRef} />
      </div>
    </div>
  );
}
