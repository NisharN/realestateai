"use client";

import { useState } from "react";
import { AnimatePresence } from "framer-motion";
import dynamic from "next/dynamic";
import { dirFor } from "./i18n";
import type { Property } from "./types";
import { useBuyerChat } from "./use-buyer-chat";
import { ChatHeader } from "./components/chat-header";
import { Composer } from "./components/composer";
import { IntakeFormPanel } from "./components/intake-form";
import { MessageList } from "./components/message-list";
import { Sidebar } from "./components/sidebar";
import { useVoiceAgent } from "./voice/use-voice-agent";

// Leaflet touches `window` at import time — client-only.
const PropertyMap = dynamic(() => import("./maps/property-map").then((m) => m.PropertyMap), {
  ssr: false,
  loading: () => null,
});

export function BuyerChat() {
  const chat = useBuyerChat();
  // Voice is an alternate input/output channel on the same thread: transcripts and
  // replies land in `chat.messages`; the mic lives in the composer (ChatGPT/Claude style).
  const voice = useVoiceAgent(
    {
      ensureLead: chat.ensureLead,
      onUserTranscript: chat.onVoiceTranscript,
      onAgentReply: chat.onVoiceReply,
    },
    chat.language,
  );
  const startVoice = () => void voice.toggle();
  const [mapOpen, setMapOpen] = useState(false);
  const [mapFocus, setMapFocus] = useState<Property | null>(null);

  const openMap = (p: Property, all: Property[]) => {
    setMapFocus(p);
    chat.setMapProperties(all);
    setMapOpen(true);
  };

  return (
    <div className="flex h-screen bg-canvas" dir={dirFor(chat.language)} lang={chat.language}>
      <Sidebar t={chat.t} needsHuman={chat.needsHuman} onSend={chat.sendMessage} onVoice={startVoice} />

      <main className="flex-1 flex flex-col min-w-0">
        <ChatHeader
          t={chat.t}
          language={chat.language}
          leadId={chat.leadId}
          onToggleLanguage={() => chat.setLanguage(chat.language === "en" ? "ar" : "en")}
          onVoice={startVoice}
        />

        <AnimatePresence>
          {chat.showIntake && (
            <IntakeFormPanel
              t={chat.t}
              value={chat.intake}
              onChange={chat.setIntake}
              onSubmit={() => chat.submitIntake("")}
              onSkip={() => chat.setShowIntake(false)}
            />
          )}
        </AnimatePresence>

        <MessageList
          messages={chat.messages}
          isLoading={chat.isLoading}
          t={chat.t}
          lang={chat.language}
          onViewMap={openMap}
          onAsk={chat.sendMessage}
        />

        <Composer
          t={chat.t}
          disabled={chat.isLoading}
          showQuickReplies={chat.messages.length < 3}
          onSend={chat.sendMessage}
          voice={voice}
        />
      </main>

      <AnimatePresence>
        {mapOpen && (
          <PropertyMap
            properties={chat.mapProperties}
            selectedProperty={mapFocus}
            onClose={() => {
              setMapOpen(false);
              setMapFocus(null);
            }}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
