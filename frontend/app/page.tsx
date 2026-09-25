"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import dynamic from "next/dynamic";
import {
  leadsApi,
  propertiesApi,
  VoiceWebSocket,
  type AreaAnswer,
  type PropertyCardDto,
  type VoiceServerMessage,
} from "@/lib/api";
import {
  Send,
  Mic,
  MicOff,
  MapPin,
  Home,
  Bed,
  Bath,
  Maximize,
  Phone,
  Calendar,
  Heart,
  X,
  ChevronRight,
  Building2,
  Globe,
  Bot,
  User,
  Loader2,
  Image as ImageIcon,
  Video,
  Sparkles,
} from "lucide-react";

// Leaflet / react-leaflet are client-only (they touch `window` at import time).
// Load them lazily so SSR can succeed.
const PropertyMap = dynamic(() => import("./_property-map").then((m) => m.PropertyMap), {
  ssr: false,
  loading: () => null,
});
const InlineMap = dynamic(() => import("./_inline-map").then((m) => m.InlineMap), {
  ssr: false,
  loading: () => null,
});

// ─── Types ──────────────────────────────────────────────────────────────────
interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  properties?: Property[];
  area?: AreaAnswer;
  needsHuman?: boolean;
  timestamp: Date;
}

// Mirrors backend AreaProfile: every number here is stored inventory / offline gazetteer data.
interface Property {
  id: string;
  title: string;
  area: string;
  price: number;
  bedrooms: number;
  bathrooms: number;
  size_sqft: number;
  images: string[];
  video_url?: string;
  map_lat: number | null;
  map_lng: number | null;
  amenities: string[];
  match_score?: number;
}

// ─── Helpers ────────────────────────────────────────────────────────────────
const cn = (...classes: (string | boolean | undefined | null)[]) =>
  classes.filter(Boolean).join(" ");

const fmtAED = (n: number) => `AED ${n.toLocaleString()}`;

const toProperty = (p: PropertyCardDto): Property => ({
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

// ─── Property Card ──────────────────────────────────────────────────────────
function PropertyCard({
  property,
  onViewMap,
}: {
  property: Property;
  onViewMap: (p: Property) => void;
}) {
  const [currentImage, setCurrentImage] = useState(0);
  const [isLiked, setIsLiked] = useState(false);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-white rounded-2xl shadow-lg overflow-hidden border border-gray-100 max-w-md"
    >
      <div className="relative h-48 bg-gray-100">
        <img
          src={property.images[currentImage]}
          alt={property.title}
          className="w-full h-full object-cover"
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).src =
              "https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?w=800";
          }}
        />
        <div className="absolute top-3 right-3 flex gap-2">
          <button
            onClick={() => setIsLiked(!isLiked)}
            className="p-2 bg-white/90 backdrop-blur rounded-full hover:bg-white transition"
          >
            <Heart
              className={cn(
                "w-4 h-4",
                isLiked ? "fill-red-500 text-red-500" : "text-gray-600"
              )}
            />
          </button>
        </div>
        {property.images.length > 1 && (
          <div className="absolute bottom-3 left-1/2 -translate-x-1/2 flex gap-1">
            {property.images.map((_, i) => (
              <button
                key={i}
                onClick={() => setCurrentImage(i)}
                className={cn(
                  "w-2 h-2 rounded-full transition",
                  i === currentImage ? "bg-white" : "bg-white/50"
                )}
              />
            ))}
          </div>
        )}
        {property.match_score != null && (
          <div className="absolute top-3 left-3 px-2 py-1 bg-green-500 text-white text-xs font-semibold rounded-full">
            {property.match_score}% Match
          </div>
        )}
      </div>

      <div className="p-4">
        <h3 className="font-semibold text-gray-900 text-sm mb-1">{property.title}</h3>
        <div className="flex items-center gap-1 text-gray-500 text-xs mb-3">
          <MapPin className="w-3 h-3" />
          {property.area}
        </div>

        <div className="flex items-center gap-4 text-xs text-gray-600 mb-3">
          <span className="flex items-center gap-1">
            <Bed className="w-3 h-3" />
            {property.bedrooms} BR
          </span>
          <span className="flex items-center gap-1">
            <Bath className="w-3 h-3" />
            {property.bathrooms} BA
          </span>
          <span className="flex items-center gap-1">
            <Maximize className="w-3 h-3" />
            {property.size_sqft.toLocaleString()} sqft
          </span>
        </div>

        {property.map_lat != null && property.map_lng != null && (
          <div className="mb-3">
            <InlineMap
              pins={[{ id: property.id, lat: property.map_lat, lng: property.map_lng, label: property.title, sublabel: property.area }]}
              height={120}
            />
          </div>
        )}

        <div className="flex flex-wrap gap-1 mb-3">
          {property.amenities.slice(0, 3).map((a) => (
            <span
              key={a}
              className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded-full"
            >
              {a}
            </span>
          ))}
        </div>

        <div className="flex items-center justify-between">
          <span className="text-lg font-bold text-gray-900">{fmtAED(property.price)}</span>
          <div className="flex gap-2">
            <button
              onClick={() => onViewMap(property)}
              disabled={property.map_lat == null || property.map_lng == null}
              className="p-2 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition disabled:opacity-40 disabled:hover:bg-transparent"
            >
              <MapPin className="w-4 h-4" />
            </button>
            <button className="px-3 py-1.5 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 transition">
              View
            </button>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

// ─── Area Answer Card ───────────────────────────────────────────────────────
function AreaCard({ area }: { area: AreaAnswer }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-white rounded-2xl shadow-lg overflow-hidden border border-gray-100 max-w-md"
    >
      <InlineMap
        pins={[{ id: area.community_id, lat: area.lat, lng: area.lng, label: area.name_en, sublabel: area.name_ar }]}
        travel={area.travel.map((t) => ({
          to_id: t.to_id,
          to_lat: t.to_lat,
          to_lng: t.to_lng,
          label: t.to_name_en,
          minutes: t.minutes,
          approx: t.approx,
        }))}
        height={180}
        interactive
      />
      <div className="p-4">
        <div className="flex items-center gap-1 text-gray-900 font-semibold text-sm mb-2">
          <MapPin className="w-3.5 h-3.5 text-blue-600" />
          {area.name_en}
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs text-gray-600 mb-3">
          <span>{area.listing_count} listings in inventory</span>
          {area.median_price != null && <span>Median {fmtAED(Math.round(area.median_price))}</span>}
          {area.median_price_psf != null && <span>{Math.round(area.median_price_psf).toLocaleString()} AED/sqft</span>}
        </div>
        {area.travel.length > 0 && (
          <ul className="space-y-1 text-xs text-gray-600">
            {area.travel.map((t) => (
              <li key={t.to_id} className="flex justify-between">
                <span>{t.to_name_en}</span>
                <span className="font-medium text-gray-800">
                  {t.approx ? "≈ " : ""}
                  {t.minutes} min · {t.km} km
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </motion.div>
  );
}

// ─── Voice Modal ────────────────────────────────────────────────────────────
function VoiceModal({
  isOpen,
  onClose,
  leadId,
  onAgentMessage,
}: {
  isOpen: boolean;
  onClose: () => void;
  leadId: string | null;
  onAgentMessage: (text: string, properties?: Property[], area?: AreaAnswer) => void;
}) {
  const onAgentMessageRef = useRef(onAgentMessage);
  onAgentMessageRef.current = onAgentMessage;
  const [transcript, setTranscript] = useState("");
  const [response, setResponse] = useState("");
  const [status, setStatus] = useState<"idle" | "listening" | "connecting" | "sending" | "thinking" | "speaking">("idle");
  const [recording, setRecording] = useState(false);
  const wsRef = useRef<VoiceWebSocket | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Barge-in: stop whatever Ali is saying (server turn + local playback).
  const stopSpeaking = useCallback(() => {
    wsRef.current?.interrupt();
    audioRef.current?.pause();
    audioRef.current = null;
    if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
  }, []);

  const speak = useCallback((msg: Extract<VoiceServerMessage, { type: "reply" }>) => {
    if (msg.audio) {
      const el = new Audio(`data:${msg.audio_format || "audio/wav"};base64,${msg.audio}`);
      audioRef.current = el;
      el.onended = () => setStatus("idle");
      el.play().catch(() => setStatus("idle"));
      setStatus("speaking");
      return;
    }
    // Last resort: browser speech synthesis of the deterministic spoken_text.
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      const u = new SpeechSynthesisUtterance(msg.spoken_text || msg.reply);
      u.onend = () => setStatus("idle");
      window.speechSynthesis.speak(u);
      setStatus("speaking");
      return;
    }
    setStatus("idle");
  }, []);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Audio visualization
  useEffect(() => {
    if (!recording || !canvasRef.current) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d")!;
    let animationId: number;

    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const bars = 30;
      const barWidth = canvas.width / bars;

      for (let i = 0; i < bars; i++) {
        const height = Math.random() * canvas.height * 0.8;
        const x = i * barWidth;
        const y = (canvas.height - height) / 2;

        const gradient = ctx.createLinearGradient(0, y, 0, y + height);
        gradient.addColorStop(0, "#3b82f6");
        gradient.addColorStop(1, "#8b5cf6");

        ctx.fillStyle = gradient;
        ctx.fillRect(x + 2, y, barWidth - 4, height);
      }

      animationId = requestAnimationFrame(draw);
    };

    draw();
    return () => cancelAnimationFrame(animationId);
  }, [recording]);

  // Auto-connect WebSocket when modal opens and we have a lead
  useEffect(() => {
    if (!isOpen) return;
    if (!leadId) {
      setStatus("idle");
      return;
    }

    setStatus("connecting");
    const ws = new VoiceWebSocket(
      leadId,
      (data) => {
        switch (data.type) {
          case "ready":
            setStatus("idle");
            if (data.resumed && data.history?.length) {
              const last = data.history[data.history.length - 1];
              if (last.role === "assistant") setResponse(last.text);
            }
            break;
          case "transcript":
            setTranscript(data.text);
            break;
          case "thinking":
            setStatus("thinking");
            break;
          case "reply":
            setResponse(data.reply);
            onAgentMessageRef.current(data.reply, (data.properties || []).map(toProperty), data.area ?? undefined);
            if (!data.interrupted) speak(data);
            break;
          case "cancelled":
          case "error":
            setStatus("idle");
            break;
        }
      },
      () => {
        setStatus("idle");
      }
    );
    ws.connect();
    wsRef.current = ws;
    setStatus("idle");

    return () => {
      ws.disconnect();
      wsRef.current = null;
    };
  }, [isOpen, leadId, speak]);

  const startRecording = async () => {
    stopSpeaking();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        const buf = await blob.arrayBuffer();
        const bytes = new Uint8Array(buf);
        let binary = "";
        for (let i = 0; i < bytes.byteLength; i++) {
          binary += String.fromCharCode(bytes[i]);
        }
        const b64 = btoa(binary);
        if (wsRef.current) {
          wsRef.current.sendAudio(b64);
          setStatus("sending");
        }
      };
      mr.start();
      mediaRecorderRef.current = mr;
      setRecording(true);
      setStatus("listening");
    } catch {
      // Mic blocked — fall back to text mode
      setStatus("idle");
      setRecording(false);
    }
  };

  const stopRecording = () => {
    mediaRecorderRef.current?.stop();
    setRecording(false);
  };

  const sendText = (txt: string) => {
    if (!txt.trim()) return;
    stopSpeaking();
    setTranscript(txt);
    if (wsRef.current) {
      wsRef.current.sendText(txt);
      setStatus("sending");
    }
  };

  if (!isOpen) return null;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
    >
      <motion.div
        initial={{ scale: 0.9, y: 20 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.9, y: 20 }}
        className="bg-white rounded-3xl p-8 w-full max-w-md text-center relative"
      >
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-2 text-gray-400 hover:text-gray-600"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="mb-6">
          <div className="w-20 h-20 mx-auto mb-4 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center">
            <Bot className="w-10 h-10 text-white" />
          </div>
          <h2 className="text-xl font-bold text-gray-900">Voice Conversation</h2>
          <p className="text-gray-500 text-sm mt-1">
            {status === "listening"
              ? "Listening..."
              : status === "connecting"
                ? "Connecting..."
                : status === "sending" || status === "thinking"
                  ? "Ali is thinking..."
                  : status === "speaking"
                    ? "Ali is speaking — tap the mic to interrupt"
                    : leadId
                    ? "Tap the mic or type below"
                    : "Send a chat message first to start a session"}
          </p>
        </div>

        <canvas
          ref={canvasRef}
          width={300}
          height={80}
          className="mx-auto mb-6 rounded-xl bg-gray-50"
        />

        {transcript && (
          <div className="mb-4 p-3 bg-gray-50 rounded-xl text-left">
            <p className="text-xs text-gray-500 mb-1">You said:</p>
            <p className="text-sm text-gray-800">{transcript}</p>
          </div>
        )}

        {response && (
          <div className="mb-4 p-3 bg-blue-50 rounded-xl text-left">
            <p className="text-xs text-blue-500 mb-1">Ali:</p>
            <p className="text-sm text-gray-800">{response}</p>
          </div>
        )}

        {/* Text fallback input — always available */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const fd = new FormData(e.currentTarget);
            const v = String(fd.get("voice-text") || "");
            if (v.trim()) sendText(v);
            (e.currentTarget as HTMLFormElement).reset();
          }}
          className="mb-4"
        >
          <input
            name="voice-text"
            placeholder="Or type here..."
            className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20"
          />
        </form>

        <button
          onClick={() => (recording ? stopRecording() : startRecording())}
          disabled={!leadId || status === "connecting"}
          className={cn(
            "w-16 h-16 rounded-full flex items-center justify-center transition-all shadow-lg mx-auto",
            recording
              ? "bg-red-500 hover:bg-red-600 shadow-red-200"
              : "bg-blue-600 hover:bg-blue-700 shadow-blue-200",
            (!leadId || status === "connecting") && "opacity-50 cursor-not-allowed"
          )}
        >
          {recording ? (
            <MicOff className="w-7 h-7 text-white" />
          ) : (
            <Mic className="w-7 h-7 text-white" />
          )}
        </button>
      </motion.div>
    </motion.div>
  );
}

// ─── Main Chat Interface ────────────────────────────────────────────────────
export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      role: "assistant",
      content:
        "Hello! I'm Ali, your Dubai property assistant. 🏠\n\nI can help you find apartments, villas, and penthouses across Dubai. What are you looking for?",
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [language, setLanguage] = useState<"en" | "ar">("en");
  const [showMap, setShowMap] = useState(false);
  const [mapProperty, setMapProperty] = useState<Property | null>(null);
  const [showVoice, setShowVoice] = useState(false);
  const [leadId, setLeadId] = useState<string | null>(null);
  const [mapProperties, setMapProperties] = useState<Property[]>([]);
  const [needsHuman, setNeedsHuman] = useState(false);
  const [showIngestForm, setShowIngestForm] = useState(true);
  const [ingestForm, setIngestForm] = useState({
    first_name: "",
    phone: "",
    email: "",
    budget_min: "",
    budget_max: "",
    property_type: "apartment",
    area_preference: "",
    timeline: "1-3_months",
  });
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const submitIngest = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    const result = await leadsApi.ingest({
      source: "website",
      first_name: ingestForm.first_name || undefined,
      phone: ingestForm.phone || undefined,
      email: ingestForm.email || undefined,
      preferred_language: language,
      budget_min: ingestForm.budget_min ? Number(ingestForm.budget_min) : undefined,
      budget_max: ingestForm.budget_max ? Number(ingestForm.budget_max) : undefined,
      property_type: ingestForm.property_type,
      area_preference: ingestForm.area_preference
        ? ingestForm.area_preference.split(",").map((s) => s.trim()).filter(Boolean)
        : [],
      timeline: ingestForm.timeline,
      message: input || undefined,
    });
    setIsLoading(false);

    if (result.error) {
      setMessages((prev) => [
        ...prev,
        {
          id: String(Date.now()),
          role: "assistant",
          content: `Sorry, I couldn't register you: ${result.error}`,
          timestamp: new Date(),
        },
      ]);
      return;
    }

    if (result.data) {
      const id = (result.data as { lead_id: string }).lead_id;
      setLeadId(id);
      setShowIngestForm(false);

      // First conversation turn: re-send the message so the agent greets + qualifies
      const firstMsg = input.trim();
      if (firstMsg) {
        await continueChat(id, firstMsg);
      } else {
        setMessages((prev) => [
          ...prev,
          {
            id: String(Date.now()),
            role: "assistant",
            content:
              "Thanks! I've registered you. Now tell me — are you looking to buy, rent, or invest, and in which area?",
            timestamp: new Date(),
          },
        ]);
      }
    }
  };

  const continueChat = useCallback(async (id: string, text: string) => {
    const result = await leadsApi.sendMessage(id, { text });
    if (result.error || !result.data) {
      setMessages((prev) => [
        ...prev,
        {
          id: String(Date.now() + 1),
          role: "assistant",
          content: `Backend error: ${result.error ?? "unknown"}`,
          timestamp: new Date(),
        },
      ]);
      return;
    }
    const data = result.data as {
      response: string;
      needs_human: boolean;
      matched_properties: PropertyCardDto[];
      area?: AreaAnswer | null;
    };

    const properties: Property[] = (data.matched_properties || []).map(toProperty);

    if (properties.length) setMapProperties(properties);

    setMessages((prev) => [
      ...prev,
      {
        id: String(Date.now() + 1),
        role: "assistant",
        content: data.response,
        properties: properties.length ? properties : undefined,
        area: data.area ?? undefined,
        needsHuman: data.needs_human,
        timestamp: new Date(),
      },
    ]);
    if (data.needs_human) setNeedsHuman(true);
  }, []);

  const sendMessage = async (text: string) => {
    if (!text.trim()) return;

    const userMsg: Message = {
      id: String(Date.now()),
      role: "user",
      content: text,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsLoading(true);

    // First-time path: if we don't have a lead yet, auto-ingest with the
    // collected form values (or anonymous defaults) and immediately continue.
    if (!leadId) {
      const ingest = await leadsApi.ingest({
        source: "website",
        preferred_language: language,
        ...ingestForm,
        first_name: ingestForm.first_name || undefined,
        phone: ingestForm.phone || undefined,
        email: ingestForm.email || undefined,
        budget_min: ingestForm.budget_min ? Number(ingestForm.budget_min) : undefined,
        budget_max: ingestForm.budget_max ? Number(ingestForm.budget_max) : undefined,
        area_preference: ingestForm.area_preference
          ? ingestForm.area_preference.split(",").map((s) => s.trim()).filter(Boolean)
          : [],
        message: text,
      });

      if (ingest.data) {
        const id = (ingest.data as { lead_id: string }).lead_id;
        setLeadId(id);
        setShowIngestForm(false);
        await continueChat(id, text);
      } else {
        setMessages((prev) => [
          ...prev,
          {
            id: String(Date.now() + 1),
            role: "assistant",
            content: `Sorry, I couldn't reach the backend: ${ingest.error ?? "unknown"}`,
            timestamp: new Date(),
          },
        ]);
      }
      setIsLoading(false);
      return;
    }

    await continueChat(leadId, text);
    setIsLoading(false);
  };

  const quickReplies = [
    { label: "Buy apartment", icon: Home },
    { label: "Rent villa", icon: Building2 },
    { label: "Invest off-plan", icon: Globe },
    { label: "Downtown Dubai", icon: null },
    { label: "Dubai Marina", icon: null },
    { label: "Palm Jumeirah", icon: null },
  ];

  const onAgentMessageFromVoice = useCallback((text: string, properties?: Property[], area?: AreaAnswer) => {
    setMessages((prev) => [
      ...prev,
      {
        id: String(Date.now()),
        role: "assistant",
        content: text,
        properties: properties && properties.length ? properties : undefined,
        area,
        timestamp: new Date(),
      },
    ]);
    if (properties && properties.length) setMapProperties(properties);
  }, []);

  return (
    <div className="flex h-[calc(100vh-3.5rem)] bg-gray-50">
      {/* ─── Sidebar ─── */}
      <div className="w-80 bg-white border-r border-gray-200 hidden lg:flex flex-col">
        <div className="p-4 border-b border-gray-100">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-blue-600 to-purple-600 rounded-xl flex items-center justify-center">
              <Building2 className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="font-bold text-gray-900">Dubai Real Estate AI</h1>
              <p className="text-xs text-gray-500">Powered by Ali</p>
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {needsHuman && (
            <div className="mb-4 p-3 rounded-xl bg-green-50 border border-green-100 text-left">
              <div className="flex items-center gap-2 text-green-700 font-semibold text-sm mb-1">
                <Sparkles className="w-4 h-4" />
                Specialist requested
              </div>
              <p className="text-xs text-green-700">
                A broker has been assigned and will reach out within 30 minutes.
              </p>
            </div>
          )}

          <div className="mb-4">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
              Quick Filters
            </h3>
            <div className="space-y-1">
              {["Downtown Dubai", "Dubai Marina", "Palm Jumeirah", "Business Bay"].map(
                (area) => (
                  <button
                    key={area}
                    onClick={() => sendMessage(`Show me properties in ${area}`)}
                    className="w-full text-left px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 rounded-lg transition"
                  >
                    <MapPin className="w-3 h-3 inline mr-2" />
                    {area}
                  </button>
                )
              )}
            </div>
          </div>

          <div className="mb-4">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
              Property Types
            </h3>
            <div className="space-y-1">
              {["Apartment", "Villa", "Penthouse", "Townhouse"].map((type) => (
                <button
                  key={type}
                  onClick={() => sendMessage(`I want a ${type.toLowerCase()}`)}
                  className="w-full text-left px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 rounded-lg transition"
                >
                  <Home className="w-3 h-3 inline mr-2" />
                  {type}
                </button>
              ))}
            </div>
          </div>

          <div className="mb-4">
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
              Budget Tiers
            </h3>
            <div className="space-y-1">
              {[
                { label: "AED 1-3M", min: 1_000_000, max: 3_000_000 },
                { label: "AED 3-5M", min: 3_000_000, max: 5_000_000 },
                { label: "AED 5M+", min: 5_000_000, max: 50_000_000 },
              ].map((b) => (
                <button
                  key={b.label}
                  onClick={() =>
                    sendMessage(`My budget is between ${b.label.replace("AED ", "")} AED`)
                  }
                  className="w-full text-left px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 rounded-lg transition"
                >
                  <span className="inline-block w-3 h-3 mr-2 text-center text-gray-400">•</span>
                  {b.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="p-4 border-t border-gray-100">
          <button
            onClick={() => setShowVoice(true)}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-xl font-medium hover:opacity-90 transition"
          >
            <Mic className="w-4 h-4" />
            Voice Conversation
          </button>
        </div>
      </div>

      {/* ─── Main Chat Area ─── */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <div className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="relative">
              <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center">
                <Bot className="w-5 h-5 text-white" />
              </div>
              <div className="absolute -bottom-0.5 -right-0.5 w-3 h-3 bg-green-500 border-2 border-white rounded-full" />
            </div>
            <div>
              <h2 className="font-semibold text-gray-900">Ali</h2>
              <p className="text-xs text-green-600">
                {leadId ? `Lead ${leadId.slice(0, 8)}…` : "Online"}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setLanguage(language === "en" ? "ar" : "en")}
              className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-lg transition"
            >
              {language === "en" ? "العربية" : "English"}
            </button>
            <button
              onClick={() => setShowVoice(true)}
              className="lg:hidden p-2 text-gray-600 hover:bg-gray-100 rounded-lg transition"
            >
              <Mic className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Optional inline lead-capture form for first-time visitors */}
        <AnimatePresence>
          {showIngestForm && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="bg-blue-50 border-b border-blue-100 px-6 py-4 overflow-hidden"
            >
              <form onSubmit={submitIngest} className="max-w-4xl">
                <div className="text-xs font-semibold text-blue-700 uppercase tracking-wider mb-2 flex items-center gap-2">
                  <Sparkles className="w-3 h-3" /> Tell us about you (optional — speeds up matching)
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  <input
                    placeholder="First name"
                    value={ingestForm.first_name}
                    onChange={(e) =>
                      setIngestForm({ ...ingestForm, first_name: e.target.value })
                    }
                    className="px-3 py-2 text-sm border border-blue-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                  />
                  <input
                    placeholder="Phone"
                    value={ingestForm.phone}
                    onChange={(e) => setIngestForm({ ...ingestForm, phone: e.target.value })}
                    className="px-3 py-2 text-sm border border-blue-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                  />
                  <input
                    placeholder="Budget (AED)"
                    type="number"
                    value={ingestForm.budget_max}
                    onChange={(e) =>
                      setIngestForm({ ...ingestForm, budget_max: e.target.value })
                    }
                    className="px-3 py-2 text-sm border border-blue-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                  />
                  <input
                    placeholder="Areas (comma-separated)"
                    value={ingestForm.area_preference}
                    onChange={(e) =>
                      setIngestForm({ ...ingestForm, area_preference: e.target.value })
                    }
                    className="px-3 py-2 text-sm border border-blue-200 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                  />
                </div>
                <div className="flex items-center justify-between mt-2">
                  <p className="text-xs text-blue-600">
                    You can skip this — just type below and we'll register you as a lead.
                  </p>
                  <button
                    type="button"
                    onClick={() => setShowIngestForm(false)}
                    className="text-xs text-blue-700 hover:underline"
                  >
                    Skip
                  </button>
                </div>
              </form>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
          <AnimatePresence>
            {messages.map((msg) => (
              <motion.div
                key={msg.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className={cn(
                  "flex gap-3",
                  msg.role === "user" ? "flex-row-reverse" : "flex-row"
                )}
              >
                <div
                  className={cn(
                    "w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0",
                    msg.role === "user"
                      ? "bg-gray-200"
                      : "bg-gradient-to-br from-blue-500 to-purple-600"
                  )}
                >
                  {msg.role === "user" ? (
                    <User className="w-4 h-4 text-gray-600" />
                  ) : (
                    <Bot className="w-4 h-4 text-white" />
                  )}
                </div>

                <div className={cn("max-w-[80%] space-y-3", msg.role === "user" ? "items-end" : "items-start")}>
                  <div
                    className={cn(
                      "px-4 py-2.5 rounded-2xl text-sm leading-relaxed",
                      msg.role === "user"
                        ? "bg-blue-600 text-white rounded-br-md"
                        : "bg-white border border-gray-200 text-gray-800 rounded-bl-md shadow-sm"
                    )}
                  >
                    {msg.content.split("\n").map((line, i) => (
                      <span key={i}>
                        {line}
                        {i < msg.content.split("\n").length - 1 && <br />}
                      </span>
                    ))}
                  </div>

                  {msg.area && <AreaCard area={msg.area} />}

                  {msg.properties && msg.properties.length > 0 && (
                    <div className="space-y-3">
                      {msg.properties.map((prop) => (
                        <PropertyCard
                          key={prop.id}
                          property={prop}
                          onViewMap={(p) => {
                            setMapProperty(p);
                            setMapProperties(msg.properties || []);
                            setShowMap(true);
                          }}
                        />
                      ))}
                    </div>
                  )}

                  <span className="text-xs text-gray-400 px-1">
                    {msg.timestamp.toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>

          {isLoading && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex items-center gap-2 text-gray-400 text-sm"
            >
              <Loader2 className="w-4 h-4 animate-spin" />
              Ali is thinking...
            </motion.div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Quick Replies */}
        {messages.length < 3 && (
          <div className="px-4 pb-2">
            <div className="flex flex-wrap gap-2">
              {quickReplies.map((reply) => (
                <button
                  key={reply.label}
                  onClick={() => sendMessage(reply.label)}
                  className="px-3 py-1.5 bg-white border border-gray-200 text-gray-600 text-xs rounded-full hover:bg-gray-50 hover:border-gray-300 transition"
                >
                  {reply.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Input */}
        <div className="bg-white border-t border-gray-200 px-4 py-3">
          <div className="flex items-center gap-2 max-w-4xl mx-auto">
            <button
              onClick={() => setShowVoice(true)}
              className="p-2.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded-xl transition"
            >
              <Mic className="w-5 h-5" />
            </button>

            <div className="flex-1 relative">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && sendMessage(input)}
                placeholder="Ask about properties, areas, prices..."
                className="w-full px-4 py-3 bg-gray-100 border-0 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:bg-white transition"
              />
            </div>

            <button
              onClick={() => sendMessage(input)}
              disabled={!input.trim() || isLoading}
              className={cn(
                "p-2.5 rounded-xl transition",
                input.trim() && !isLoading
                  ? "bg-blue-600 text-white hover:bg-blue-700"
                  : "bg-gray-100 text-gray-400"
              )}
            >
              <Send className="w-5 h-5" />
            </button>
          </div>
        </div>
      </div>

      {/* ─── Modals ─── */}
      <AnimatePresence>
        {showMap && (
          <PropertyMap
            properties={mapProperties}
            selectedProperty={mapProperty}
            onClose={() => {
              setShowMap(false);
              setMapProperty(null);
            }}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showVoice && (
          <VoiceModal
            isOpen={showVoice}
            onClose={() => setShowVoice(false)}
            leadId={leadId}
            onAgentMessage={onAgentMessageFromVoice}
          />
        )}
      </AnimatePresence>
    </div>
  );
}