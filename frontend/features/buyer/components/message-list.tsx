"use client";

import { useEffect, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Bot, Loader2, User } from "lucide-react";
import type { Strings } from "../i18n";
import { cn, type Language, type Message, type Property } from "../types";
import { AreaCard } from "./area-card";
import { PropertyCard } from "./property-card";

function MessageBubble({
  message,
  t,
  lang,
  onViewMap,
  onAsk,
}: {
  message: Message;
  t: Strings;
  lang: Language;
  onViewMap: (p: Property, all: Property[]) => void;
  onAsk: (text: string) => void;
}) {
  const isUser = message.role === "user";
  const lines = message.content.split("\n");
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn("flex gap-3", isUser ? "flex-row-reverse" : "flex-row")}
      data-role={message.role}
    >
      <div
        className={cn(
          "w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0",
          isUser ? "bg-muted" : "bg-brand-gradient",
        )}
      >
        {isUser ? <User className="w-4 h-4 text-muted-foreground" /> : <Bot className="w-4 h-4 text-brand-foreground" />}
      </div>

      <div className={cn("max-w-[80%] space-y-3 flex flex-col", isUser ? "items-end" : "items-start")}>
        <div
          dir="auto"
          className={cn(
            "px-4 py-2.5 rounded-2xl text-sm leading-relaxed",
            isUser
              ? "bg-brand text-brand-foreground rounded-ee-md"
              : "bg-card border border-border text-foreground rounded-es-md shadow-sm",
          )}
        >
          {lines.map((line, i) => (
            <span key={i}>
              {line}
              {i < lines.length - 1 && <br />}
            </span>
          ))}
        </div>

        {message.area && <AreaCard area={message.area} t={t} lang={lang} />}

        {message.properties && message.properties.length > 0 && (
          <div className="space-y-3">
            {message.properties.map((prop) => (
              <PropertyCard
                key={prop.id}
                property={prop}
                t={t}
                lang={lang}
                onViewMap={(p) => onViewMap(p, message.properties || [])}
                onAsk={onAsk}
              />
            ))}
          </div>
        )}

        <span className="text-xs text-muted-foreground px-1" dir="ltr">
          {message.timestamp.toLocaleTimeString(lang === "ar" ? "ar-AE" : [], { hour: "2-digit", minute: "2-digit" })}
        </span>
      </div>
    </motion.div>
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
  onAsk: (text: string) => void;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4" role="log" aria-live="polite">
      <AnimatePresence>
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} t={t} lang={lang} onViewMap={onViewMap} onAsk={onAsk} />
        ))}
      </AnimatePresence>

      {isLoading && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex items-center gap-2 text-muted-foreground text-sm">
          <Loader2 className="w-4 h-4 animate-spin" />
          {t.thinking}
        </motion.div>
      )}
      <div ref={endRef} />
    </div>
  );
}
