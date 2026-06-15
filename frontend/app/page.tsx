"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
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
  Play,
  Image as ImageIcon,
  Video,
} from "lucide-react";
import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Fix for Leaflet marker icons in Next.js/React
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png';
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';

L.Marker.prototype.options.icon = L.icon({
  iconUrl: markerIcon.src || markerIcon,
  iconRetinaUrl: markerIcon2x.src || markerIcon2x,
  shadowUrl: markerShadow.src || markerShadow,
});

// Types
interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  properties?: Property[];
  timestamp: Date;
}

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
  map_lat: number;
  map_lng: number;
  amenities: string[];
  match_score?: number;
}

// Mock data for demo
const MOCK_PROPERTIES: Property[] = [
  {
    id: "prop-1",
    title: "Burj Vista Tower 1 - Luxury 2BR",
    area: "Downtown Dubai",
    price: 3200000,
    bedrooms: 2,
    bathrooms: 2,
    size_sqft: 1200,
    images: [
      "https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?w=800",
      "https://images.unsplash.com/photo-1502672260266-1c1ef2d93688?w=800",
    ],
    video_url: "https://example.com/video1",
    map_lat: 25.1972,
    map_lng: 55.2744,
    amenities: ["Gym", "Pool", "Concierge", "Parking"],
    match_score: 95,
  },
  {
    id: "prop-2",
    title: "Address Boulevard - 3BR Penthouse",
    area: "Downtown Dubai",
    price: 8500000,
    bedrooms: 3,
    bathrooms: 3,
    size_sqft: 2500,
    images: [
      "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=800",
    ],
    map_lat: 25.2048,
    map_lng: 55.2708,
    amenities: ["Private Pool", "Smart Home", "Valet", "Spa"],
    match_score: 88,
  },
  {
    id: "prop-3",
    title: "Marina Gate - Sea View 1BR",
    area: "Dubai Marina",
    price: 1800000,
    bedrooms: 1,
    bathrooms: 1,
    size_sqft: 800,
    images: [
      "https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=800",
    ],
    map_lat: 25.0895,
    map_lng: 55.1515,
    amenities: ["Beach Access", "Gym", "Parking"],
    match_score: 82,
  },
];

// Utility
const cn = (...classes: (string | boolean | undefined)[]) =>
  classes.filter(Boolean).join(" ");

// Components
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
      {/* Image Carousel */}
      <div className="relative h-48 bg-gray-100">
        <img
          src={property.images[currentImage]}
          alt={property.title}
          className="w-full h-full object-cover"
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
        {property.match_score && (
          <div className="absolute top-3 left-3 px-2 py-1 bg-green-500 text-white text-xs font-semibold rounded-full">
            {property.match_score}% Match
          </div>
        )}
      </div>

      {/* Content */}
      <div className="p-4">
        <h3 className="font-semibold text-gray-900 text-sm mb-1">
          {property.title}
        </h3>
        <div className="flex items-center gap-1 text-gray-500 text-xs mb-3">
          <MapPin className="w-3 h-3" />
          {property.area}
        </div>

        <div className="flex items-center gap-4 text-xs text-gray-600 mb-3">
          <span className="flex items-center gap-1">
            <Bed className="w-3 h-3" />
            {property.bedrooms} BR
          </span
          <span className="flex items-center gap-1">
            <Bath className="w-3 h-3" />
            {property.bathrooms} BA
          </span
          <span className="flex items-center gap-1">
            <Maximize className="w-3 h-3" />
            {property.size_sqft.toLocaleString()} sqft
          </span
        </div>

        <div className="flex flex-wrap gap-1 mb-3">
          {property.amenities.slice(0, 3).map((a) => (
            <span
              key={a}
              className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded-full"
            >
              {a}
            </span
          ))}
        </div>

        <div className="flex items-center justify-between">
          <span className="text-lg font-bold text-gray-900">
            AED {property.price.toLocaleString()}
          </span
          <div className="flex gap-2">
            <button
              onClick={() => onViewMap(property)}
              className="p-2 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition"
            >
              <MapPin className="w-4 h-4" />
            </button>
            <button className="px-3 py-1.5 bg-blue-600 text-white text-xs font-medium rounded-lg hover:bg-blue-700 transition">
              View
            </button>
          </div
        </div
      </div
    </motion.div>
  );
}

function PropertyMap({
  properties,
  selectedProperty,
  onClose,
}: {
  properties: Property[];
  selectedProperty: Property | null;
  onClose: () => void;
}) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) return null;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
    >
      <motion.div
        initial={{ scale: 0.9 }}
        animate={{ scale: 1 }}
        exit={{ scale: 0.9 }}
        className="bg-white rounded-2xl overflow-hidden w-full max-w-4xl h-[80vh] relative"
      >
        <button
          onClick={onClose}
          className="absolute top-4 right-4 z-[1000] p-2 bg-white/90 backdrop-blur rounded-full shadow-lg hover:bg-white transition"
        >
          <X className="w-5 h-5" />
        </button>

        <MapContainer
          center={[selectedProperty?.map_lat || 25.2048, selectedProperty?.map_lng || 55.2708]}
          zoom={12}
          style={{ width: "100%", height: "100%" }}
        >
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          />
          {properties.map((p) => (
            <Marker key={p.id} position={[p.map_lat, p.map_lng]}>
              <Popup>
                <div className="w-64">
                  <img
                    src={p.images[0]}
                    alt={p.title}
                    className="w-full h-32 object-cover rounded-lg"
                  />
                  <div className="p-3">
                    <h4 className="font-semibold text-sm">{p.title}</h4>
                    <p className="text-blue-600 font-bold text-sm mt-1">
                      AED {p.price.toLocaleString()}
                    </p>
                  </div>
                </div>
              </Popup>
            </Marker>
          ))}
        </MapContainer>
      </motion.div>
    </motion.div>
  );
}

function VoiceModal({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const [isListening, setIsListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [response, setResponse] = useState("");
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Audio visualization
  useEffect(() => {
    if (!isListening || !canvasRef.current) return;

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
  }, [isListening]);

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
        className="bg-white rounded-3xl p-8 w-full max-w-md text-center"
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
            {isListening ? "Listening..." : "Tap the microphone to start"}
          </p>
        </div>

        {/* Audio Visualizer */}
        <canvas
          ref={canvasRef}
          width={300}
          height={80}
          className="mx-auto mb-6 rounded-xl"
        />

        {/* Transcript */}
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

        {/* Controls */}
        <button
          onClick={() => {
            setIsListening(!isListening);
            if (!isListening) {
              setTranscript("I'm looking for a 2 bedroom apartment in Downtown Dubai");
              setTimeout(() => {
                setResponse(
                  "Great choice! I found 3 properties in Downtown Dubai. Let me show you..."
                );
                setIsListening(false);
              }, 3000);
            }
          }}
          className={cn(
            "w-16 h-16 rounded-full flex items-center justify-center transition-all",
            isListening
              ? "bg-red-500 hover:bg-red-600 shadow-red-200"
              : "bg-blue-600 hover:bg-blue-700 shadow-blue-200",
            "shadow-lg"
          )}
        >
          {isListening ? (
            <MicOff className="w-7 h-7 text-white" />
          ) : (
            <Mic className="w-7 h-7 text-white" />
          )}
        </button>
      </motion.div>
    </motion.div>
  );
}

// Main Chat Interface
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
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const sendMessage = async (text: string) => {
    if (!text.trim()) return;

    const userMsg: Message = {
      id: Date.now().toString(),
      role: "user",
      content: text,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsLoading(true);

    // Simulate AI response (replace with actual API call)
    setTimeout(() => {
      let response: Message;

      if (text.toLowerCase().includes("downtown") || text.toLowerCase().includes("apartment")) {
        response = {
          id: (Date.now() + 1).toString(),
          role: "assistant",
          content:
            "Perfect! I found some amazing properties in Downtown Dubai. Here are the top matches:",
          properties: MOCK_PROPERTIES,
          timestamp: new Date(),
        };
      } else if (text.toLowerCase().includes("budget") || text.toLowerCase().includes("price")) {
        response = {
          id: (Date.now() + 1).toString(),
          role: "assistant",
          content:
            "What's your budget range? I can filter properties from AED 1M to AED 50M+",
          timestamp: new Date(),
        };
      } else if (text.toLowerCase().includes("visit") || text.toLowerCase().includes("viewing")) {
        response = {
          id: (Date.now() + 1).toString(),
          role: "assistant",
          content:
            "I'd be happy to schedule a site visit! Our specialist will contact you within 30 minutes to confirm the appointment. 📅",
          timestamp: new Date(),
        };
      } else {
        response = {
          id: (Date.now() + 1).toString(),
          role: "assistant",
          content:
            "I understand. To help you better, could you tell me:\n\n1. Are you looking to buy or rent?\n2. Which area in Dubai interests you?\n3. What's your budget range?",
          timestamp: new Date(),
        };
      }

      setMessages((prev) => [...prev, response]);
      setIsLoading(false);
    }, 1500);
  };

  const quickReplies = [
    { label: "Buy", icon: Home },
    { label: "Rent", icon: Building2 },
    { label: "Invest", icon: Globe },
    { label: "AED 1-3M", icon: null },
    { label: "AED 3-5M", icon: null },
    { label: "AED 5M+", icon: null },
  ];

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Sidebar */}
      <div className="w-80 bg-white border-r border-gray-200 hidden lg:flex flex-col">
        <div className="p-4 border-b border-gray-100">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-blue-600 to-purple-600 rounded-xl flex items-center justify-center">
              <Building2 className="w-5 h-5 text-white" />
            </div
            <div
            >
              <h1 className="font-bold text-gray-900">Dubai Real Estate AI</h1>
              <p className="text-xs text-gray-500">Powered by Ali</p>
            </div
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
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
            </div
          </div

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
            </div
          </div
        </div

        <div className="p-4 border-t border-gray-100">
          <button
            onClick={() => setShowVoice(true)}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-xl font-medium hover:opacity-90 transition"
          >
            <Mic className="w-4 h-4" />
            Voice Conversation
          </button>
        </div
      </div

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <div className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="relative">
              <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center">
                <Bot className="w-5 h-5 text-white" />
              </div
              <div className="absolute -bottom-0.5 -right-0.5 w-3 h-3 bg-green-500 border-2 border-white rounded-full" />
            </div
            <div
            >
              <h2 className="font-semibold text-gray-900">Ali</h2>
              <p className="text-xs text-green-600">Online</p>
            </div
          </div

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
            </button
          </div
        </div

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
                {/* Avatar */}
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
                </div

                {/* Message Content */}
                <div
                  className={cn(
                    "max-w-[80%] space-y-3",
                    msg.role === "user" ? "items-end" : "items-start"
                  )}
                >
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
                      </span
                    ))}
                  </div

                  {/* Property Cards */}
                  {msg.properties && msg.properties.length > 0 && (
                    <div className="space-y-3">
                      {msg.properties.map((prop) => (
                        <PropertyCard
                          key={prop.id}
                          property={prop}
                          onViewMap={(p) => {
                            setMapProperty(p);
                            setShowMap(true);
                          }}
                        />
                      ))}
                    </div
                  )}

                  <span className="text-xs text-gray-400 px-1">
                    {msg.timestamp.toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </span
                </div
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
              Ali is typing...
            </motion.div>
          )}

          <div ref={messagesEndRef} />
        </div

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
            </div
          </div
        )}

        {/* Input */}
        <div className="bg-white border-t border-gray-200 px-4 py-3">
          <div className="flex items-center gap-2 max-w-4xl mx-auto">
            <button
              onClick={() => setShowVoice(true)}
              className="p-2.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded-xl transition"
            >
              <Mic className="w-5 h-5" />
            </button

            <div className="flex-1 relative">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && sendMessage(input)}
                placeholder="Ask about properties, areas, prices..."
                className="w-full px-4 py-3 bg-gray-100 border-0 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:bg-white transition"
              />
            </div

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
            </button
          </div
        </div
      </div

      {/* Modals */}
      <AnimatePresence>
        {showMap && (
          <PropertyMap
            properties={MOCK_PROPERTIES}
            selectedProperty={mapProperty}
            onClose={() => {
              setShowMap(false);
              setMapProperty(null);
            }}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showVoice && <VoiceModal isOpen={showVoice} onClose={() => setShowVoice(false)} />}
      </AnimatePresence>
    </div
  );
}
