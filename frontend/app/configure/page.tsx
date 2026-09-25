"use client";

import { useState, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Users,
  Plus,
  X,
  Database,
  UploadCloud,
  Rss,
  Plug,
  Globe2,
  MessageCircle,
  Check,
  ArrowRight,
  ArrowLeft,
  Loader2,
  Rocket,
  PartyPopper,
} from "lucide-react";
import {
  workspaceApi,
  type TeamMember,
  type DataSourceConfig,
  type ChannelConfig,
} from "@/lib/api";

// ─── Static config ──────────────────────────────────────────────────────────
const STEPS = ["Team & roles", "Data pipeline", "Channels", "Review & launch"] as const;

const SOURCE_META: Record<
  string,
  { label: string; icon: any; description: string; kind: "upload" | "test" }
> = {
  broker_csv: {
    label: "Broker CSV upload",
    icon: UploadCloud,
    description: "Upload a listings spreadsheet directly.",
    kind: "upload",
  },
  crm_export: {
    label: "CRM export",
    icon: Database,
    description: "Import a CRM export file (same importer as CSV).",
    kind: "upload",
  },
  approved_feed: {
    label: "Approved partner feed",
    icon: Rss,
    description: "A provider-approved JSON listings feed.",
    kind: "test",
  },
  rapidapi_uae: {
    label: "RapidAPI (UAE real estate)",
    icon: Plug,
    description: "Provider-backed supplemental listings.",
    kind: "test",
  },
  propertyfinder: {
    label: "Property Finder (live)",
    icon: Globe2,
    description: "The one portal that's reliably live-scrapable today.",
    kind: "test",
  },
};

const DEFAULT_SOURCES: DataSourceConfig[] = [
  { source: "broker_csv", enabled: false, status: "not_configured" },
  { source: "crm_export", enabled: false, status: "not_configured" },
  { source: "approved_feed", enabled: false, status: "not_configured" },
  { source: "rapidapi_uae", enabled: false, status: "not_configured" },
  { source: "propertyfinder", enabled: false, status: "not_configured" },
];

const EMPTY_MEMBER: TeamMember = {
  name: "",
  email: "",
  phone: "",
  role: "agent",
  languages: ["en"],
  specialization: [],
  max_leads: 20,
};

// ─── Small building blocks ─────────────────────────────────────────────────

function StepProgress({ step }: { step: number }) {
  return (
    <div className="mb-10">
      <div className="flex justify-between mb-2">
        {STEPS.map((label, i) => (
          <div
            key={label}
            className={
              "text-xs font-medium flex items-center gap-1.5 " +
              (i <= step ? "text-brand" : "text-muted-foreground/70")
            }
          >
            <span
              className={
                "w-5 h-5 rounded-full flex items-center justify-center text-[10px] " +
                (i < step
                  ? "bg-brand text-white"
                  : i === step
                  ? "bg-brand/10 text-brand border border-blue-400"
                  : "bg-muted text-muted-foreground/70")
              }
            >
              {i < step ? <Check className="w-3 h-3" /> : i + 1}
            </span>
            <span className="hidden md:inline">{label}</span>
          </div>
        ))}
      </div>
      <div className="h-1.5 bg-muted rounded-full overflow-hidden">
        <motion.div
          className="h-full bg-gradient-to-r from-brand to-brand-2 rounded-full"
          initial={false}
          animate={{ width: `${(step / (STEPS.length - 1)) * 100}%` }}
          transition={{ type: "spring", stiffness: 200, damping: 30 }}
        />
      </div>
    </div>
  );
}

const stepVariants = {
  enter: { opacity: 0, x: 24 },
  center: { opacity: 1, x: 0 },
  exit: { opacity: 0, x: -24 },
};

// ─── Step 1: Team & roles ───────────────────────────────────────────────────

function TeamStep({
  workspaceName,
  setWorkspaceName,
  team,
  setTeam,
}: {
  workspaceName: string;
  setWorkspaceName: (v: string) => void;
  team: TeamMember[];
  setTeam: (v: TeamMember[]) => void;
}) {
  const [draft, setDraft] = useState<TeamMember>(EMPTY_MEMBER);

  const addMember = () => {
    if (!draft.name.trim()) return;
    setTeam([...team, draft]);
    setDraft(EMPTY_MEMBER);
  };

  const removeMember = (idx: number) => {
    setTeam(team.filter((_, i) => i !== idx));
  };

  return (
    <div className="space-y-6">
      <div>
        <label className="block text-sm font-medium text-foreground/80 mb-1">
          Workspace name
        </label>
        <input
          value={workspaceName}
          onChange={(e) => setWorkspaceName(e.target.value)}
          placeholder="e.g. Golden Sands Realty"
          className="w-full px-4 py-2.5 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-brand/20"
        />
        <p className="text-xs text-muted-foreground/70 mt-1">
          This becomes the name of the broker/agency instance you're configuring.
        </p>
      </div>

      <div className="bg-muted/50 rounded-2xl p-5 border border-border">
        <div className="flex items-center gap-2 mb-4 text-sm font-semibold text-foreground">
          <Users className="w-4 h-4 text-brand" />
          Team roster
        </div>

        <AnimatePresence initial={false}>
          {team.map((m, i) => (
            <motion.div
              key={`${m.name}-${i}`}
              layout
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="flex items-center justify-between bg-card rounded-xl border border-border px-4 py-2.5 mb-2"
            >
              <div>
                <p className="text-sm font-medium text-foreground">
                  {m.name} <span className="text-muted-foreground/70 font-normal">— {m.role}</span>
                </p>
                <p className="text-xs text-muted-foreground">
                  {m.languages.join(", ")}
                  {m.specialization.length > 0 && ` · ${m.specialization.join(", ")}`}
                </p>
              </div>
              <button
                onClick={() => removeMember(i)}
                className="p-1.5 text-muted-foreground/70 hover:text-red-500 hover:bg-danger-soft rounded-lg transition"
              >
                <X className="w-4 h-4" />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mt-3">
          <input
            placeholder="Name"
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            className="col-span-2 px-3 py-2 text-sm border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-brand/20"
          />
          <select
            value={draft.role}
            onChange={(e) => setDraft({ ...draft, role: e.target.value as TeamMember["role"] })}
            className="px-3 py-2 text-sm border border-border rounded-lg bg-card focus:outline-none"
          >
            <option value="agent">Agent</option>
            <option value="broker">Broker</option>
            <option value="team_lead">Team lead</option>
          </select>
          <input
            placeholder="Languages (en,ar)"
            value={draft.languages.join(",")}
            onChange={(e) =>
              setDraft({
                ...draft,
                languages: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
              })
            }
            className="px-3 py-2 text-sm border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-brand/20"
          />
          <input
            placeholder="Areas (comma-sep)"
            value={draft.specialization.join(",")}
            onChange={(e) =>
              setDraft({
                ...draft,
                specialization: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
              })
            }
            className="px-3 py-2 text-sm border border-border rounded-lg bg-card focus:outline-none focus:ring-2 focus:ring-brand/20"
          />
        </div>
        <button
          onClick={addMember}
          disabled={!draft.name.trim()}
          className="mt-3 flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-brand bg-brand/5 hover:bg-brand/10 rounded-lg transition disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <Plus className="w-3.5 h-3.5" /> Add to roster
        </button>
      </div>
    </div>
  );
}

// ─── Step 2: Data pipeline ──────────────────────────────────────────────────

function PipelineStep({
  sources,
  setSources,
}: {
  sources: DataSourceConfig[];
  setSources: (v: DataSourceConfig[]) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadTarget, setUploadTarget] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const updateSource = (source: string, patch: Partial<DataSourceConfig>) => {
    setSources(sources.map((s) => (s.source === source ? { ...s, ...patch } : s)));
  };

  const handleToggle = async (source: string) => {
    const current = sources.find((s) => s.source === source)!;
    if (current.enabled) {
      updateSource(source, { enabled: false, status: "not_configured" });
      return;
    }

    const meta = SOURCE_META[source];
    if (meta.kind === "upload") {
      setUploadTarget(source);
      fileInputRef.current?.click();
      return;
    }

    setBusy(source);
    updateSource(source, { status: "testing" });
    const result = await workspaceApi.testDataSource(source);
    setBusy(null);
    const data = result.data;
    if (data && data.ok) {
      updateSource(source, { enabled: true, status: "connected" });
      setToast(data.message);
    } else {
      updateSource(source, { enabled: false, status: "error" });
      setToast(result.error || "Test failed");
    }
    setTimeout(() => setToast(null), 3500);
  };

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || !uploadTarget) return;

    setBusy(uploadTarget);
    updateSource(uploadTarget, { status: "testing" });
    const result = await workspaceApi.importCsv(file, uploadTarget);
    setBusy(null);
    if (result.data) {
      updateSource(uploadTarget, {
        enabled: true,
        status: "connected",
        meta: { last_import: result.data },
      });
      setToast(
        `Imported ${(result.data as any).saved ?? 0} listing(s) from ${file.name}`
      );
    } else {
      updateSource(uploadTarget, { enabled: false, status: "error" });
      setToast(result.error || "Import failed");
    }
    setUploadTarget(null);
    setTimeout(() => setToast(null), 3500);
  };

  const enabledCount = sources.filter((s) => s.enabled).length;

  return (
    <div>
      <input ref={fileInputRef} type="file" accept=".csv" className="hidden" onChange={handleFile} />

      <p className="text-sm text-muted-foreground mb-5">
        Turn on the sources this workspace uses to build its property inventory. Bayut and
        Dubizzle live scraping are deferred by default (both are anti-bot protected) — lead
        with CSV/CRM import, an approved feed, or RapidAPI instead.
      </p>

      <div className="grid sm:grid-cols-2 gap-3 mb-8">
        {sources.map((s) => {
          const meta = SOURCE_META[s.source];
          const Icon = meta.icon;
          const isBusy = busy === s.source;
          return (
            <motion.button
              key={s.source}
              onClick={() => handleToggle(s.source)}
              whileTap={{ scale: 0.98 }}
              className={
                "text-left p-4 rounded-2xl border transition relative overflow-hidden " +
                (s.enabled
                  ? "border-blue-300 bg-brand/5/60"
                  : "border-border border-border bg-card hover:border-border")
              }
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2.5">
                  <div
                    className={
                      "w-9 h-9 rounded-xl flex items-center justify-center " +
                      (s.enabled ? "bg-brand text-white" : "bg-muted text-muted-foreground")
                    }
                  >
                    <Icon className="w-4 h-4" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-foreground">{meta.label}</p>
                    <p className="text-xs text-muted-foreground">{meta.description}</p>
                  </div>
                </div>
                {isBusy ? (
                  <Loader2 className="w-4 h-4 text-blue-500 animate-spin shrink-0" />
                ) : s.enabled ? (
                  <Check className="w-4 h-4 text-brand shrink-0" />
                ) : null}
              </div>
            </motion.button>
          );
        })}
      </div>

      {/* Animated pipeline visualization */}
      <div className="bg-muted/50 rounded-2xl border border-border p-6">
        <p className="text-xs font-semibold text-muted-foreground/70 uppercase tracking-wider mb-4">
          Pipeline preview
        </p>
        <div className="flex items-center gap-3 overflow-x-auto pb-2">
          {sources
            .filter((s) => s.enabled)
            .map((s, i) => (
              <motion.div
                key={s.source}
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                className="flex items-center gap-3 shrink-0"
              >
                <div className="px-3 py-2 bg-card border border-blue-200 rounded-xl text-xs font-medium text-brand whitespace-nowrap">
                  {SOURCE_META[s.source].label}
                </div>
                <motion.div
                  className="w-8 h-0.5 bg-blue-300 origin-left"
                  initial={{ scaleX: 0 }}
                  animate={{ scaleX: 1 }}
                  transition={{ delay: 0.1 * i }}
                />
              </motion.div>
            ))}
          <div className="px-4 py-2.5 bg-gradient-to-br from-brand to-brand-2 text-white rounded-xl text-xs font-semibold whitespace-nowrap shrink-0">
            Unified property inventory
          </div>
        </div>
        {enabledCount === 0 && (
          <p className="text-xs text-muted-foreground/70 mt-3">
            Turn on at least one source above to see it flow into inventory.
          </p>
        )}
      </div>

      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            className="mt-4 text-xs px-3 py-2 bg-brand text-white rounded-lg inline-block"
          >
            {toast}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ─── Step 3: Channels ───────────────────────────────────────────────────────

function ChannelsStep({
  channels,
  setChannels,
}: {
  channels: ChannelConfig;
  setChannels: (v: ChannelConfig) => void;
}) {
  const toggleLang = (lang: string) => {
    const has = channels.languages.includes(lang);
    setChannels({
      ...channels,
      languages: has
        ? channels.languages.filter((l) => l !== lang)
        : [...channels.languages, lang],
    });
  };

  return (
    <div className="space-y-6">
      <div className="bg-muted/50 rounded-2xl border border-border p-5">
        <div className="flex items-center gap-2 mb-3 text-sm font-semibold text-foreground">
          <MessageCircle className="w-4 h-4 text-success" />
          WhatsApp number
        </div>
        <input
          value={channels.whatsapp_number || ""}
          onChange={(e) => setChannels({ ...channels, whatsapp_number: e.target.value })}
          placeholder="+971 5X XXX XXXX"
          className="w-full px-4 py-2.5 border border-border rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-brand/20"
        />
        <p className="text-xs text-amber-600 mt-2">
          POC note: this stores the number for the workspace config. No real WhatsApp message
          sends yet — that's the next real integration, not simulated here.
        </p>
      </div>

      <div className="bg-muted/50 rounded-2xl border border-border p-5">
        <div className="flex items-center gap-2 mb-3 text-sm font-semibold text-foreground">
          <Globe2 className="w-4 h-4 text-brand" />
          Languages
        </div>
        <div className="flex gap-2">
          {["en", "ar"].map((lang) => (
            <button
              key={lang}
              onClick={() => toggleLang(lang)}
              className={
                "px-4 py-2 rounded-xl text-sm font-medium border transition " +
                (channels.languages.includes(lang)
                  ? "bg-brand text-white border-blue-600"
                  : "bg-card text-muted-foreground border-border hover:border-border")
              }
            >
              {lang === "en" ? "English" : "العربية"}
            </button>
          ))}
        </div>
      </div>

      <div className="bg-muted/50 rounded-2xl border border-border p-5 flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-foreground">Web chat widget</p>
          <p className="text-xs text-muted-foreground">The chat UI you're using right now.</p>
        </div>
        <button
          onClick={() =>
            setChannels({ ...channels, web_widget_enabled: !channels.web_widget_enabled })
          }
          className={
            "w-11 h-6 rounded-full relative transition-colors " +
            (channels.web_widget_enabled ? "bg-brand" : "bg-gray-300")
          }
        >
          <motion.div
            className="w-5 h-5 bg-card rounded-full absolute top-0.5"
            animate={{ left: channels.web_widget_enabled ? 22 : 2 }}
            transition={{ type: "spring", stiffness: 500, damping: 30 }}
          />
        </button>
      </div>
    </div>
  );
}

// ─── Step 4: Review & launch ────────────────────────────────────────────────

function ReviewStep({
  workspaceName,
  team,
  sources,
  channels,
  onLaunch,
  launching,
  launched,
}: {
  workspaceName: string;
  team: TeamMember[];
  sources: DataSourceConfig[];
  channels: ChannelConfig;
  onLaunch: () => void;
  launching: boolean;
  launched: string | null;
}) {
  if (launched) {
    return (
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        className="text-center py-10"
      >
        <motion.div
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          transition={{ type: "spring", stiffness: 260, damping: 18, delay: 0.1 }}
          className="w-16 h-16 mx-auto mb-4 bg-green-100 rounded-full flex items-center justify-center"
        >
          <PartyPopper className="w-8 h-8 text-success" />
        </motion.div>
        <h3 className="text-lg font-semibold text-foreground">
          {workspaceName || "Your workspace"} is live
        </h3>
        <p className="text-sm text-muted-foreground mt-1">Workspace ID: {launched}</p>
        <p className="text-xs text-muted-foreground/70 mt-4 max-w-sm mx-auto">
          Leads coming through Chat now route through this configuration. Remember: this is a
          POC — leads/properties aren't scoped per-workspace yet (see Docs).
        </p>
      </motion.div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="bg-muted/50 rounded-2xl border border-border p-5">
        <p className="text-xs font-semibold text-muted-foreground/70 uppercase tracking-wider mb-2">
          Workspace
        </p>
        <p className="text-sm font-medium text-foreground">{workspaceName || "(untitled)"}</p>
      </div>

      <div className="bg-muted/50 rounded-2xl border border-border p-5">
        <p className="text-xs font-semibold text-muted-foreground/70 uppercase tracking-wider mb-2">
          Team ({team.length})
        </p>
        {team.length === 0 ? (
          <p className="text-sm text-muted-foreground/70">No team members added.</p>
        ) : (
          <ul className="text-sm text-foreground/80 space-y-1">
            {team.map((m, i) => (
              <li key={i}>
                {m.name} — {m.role} ({m.languages.join("/")})
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="bg-muted/50 rounded-2xl border border-border p-5">
        <p className="text-xs font-semibold text-muted-foreground/70 uppercase tracking-wider mb-2">
          Data sources
        </p>
        {sources.filter((s) => s.enabled).length === 0 ? (
          <p className="text-sm text-muted-foreground/70">None enabled yet.</p>
        ) : (
          <ul className="text-sm text-foreground/80 space-y-1">
            {sources
              .filter((s) => s.enabled)
              .map((s) => (
                <li key={s.source}>{SOURCE_META[s.source].label}</li>
              ))}
          </ul>
        )}
      </div>

      <div className="bg-muted/50 rounded-2xl border border-border p-5">
        <p className="text-xs font-semibold text-muted-foreground/70 uppercase tracking-wider mb-2">
          Channels
        </p>
        <p className="text-sm text-foreground/80">
          WhatsApp: {channels.whatsapp_number || "not set"} · Languages:{" "}
          {channels.languages.join(", ") || "none"} · Web widget:{" "}
          {channels.web_widget_enabled ? "on" : "off"}
        </p>
      </div>

      <button
        onClick={onLaunch}
        disabled={launching || !workspaceName.trim()}
        className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-gradient-to-r from-brand to-brand-2 text-white rounded-xl font-medium hover:opacity-90 transition disabled:opacity-40 disabled:cursor-not-allowed"
      >
        {launching ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <Rocket className="w-4 h-4" />
        )}
        {launching ? "Launching..." : "Launch workspace"}
      </button>
    </div>
  );
}

// ─── Main page ──────────────────────────────────────────────────────────────

export default function ConfigurePage() {
  const [step, setStep] = useState(0);
  const [workspaceName, setWorkspaceName] = useState("");
  const [team, setTeam] = useState<TeamMember[]>([]);
  const [sources, setSources] = useState<DataSourceConfig[]>(DEFAULT_SOURCES);
  const [channels, setChannels] = useState<ChannelConfig>({
    whatsapp_number: "",
    whatsapp_connected: false,
    languages: ["en", "ar"],
    web_widget_enabled: true,
  });
  const [launching, setLaunching] = useState(false);
  const [launched, setLaunched] = useState<string | null>(null);

  const handleLaunch = async () => {
    setLaunching(true);
    const created = await workspaceApi.create({
      name: workspaceName,
      team,
      data_sources: sources,
      channels,
    });
    if (created.data) {
      await workspaceApi.launch(created.data.id);
      setLaunched(created.data.id);
    }
    setLaunching(false);
  };

  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-muted/50 py-10 px-4">
      <div className="max-w-3xl mx-auto bg-card rounded-3xl border border-border shadow-card p-8">
        <div className="mb-6">
          <h1 className="text-xl font-bold text-foreground">Configure a workspace</h1>
          <p className="text-sm text-muted-foreground mt-1">
            The guided setup a new broker or agency goes through — team, data pipeline,
            channels — instead of an engineer configuring it by hand.
          </p>
        </div>

        <StepProgress step={step} />

        <AnimatePresence mode="wait">
          <motion.div
            key={step}
            variants={stepVariants}
            initial="enter"
            animate="center"
            exit="exit"
            transition={{ duration: 0.2 }}
          >
            {step === 0 && (
              <TeamStep
                workspaceName={workspaceName}
                setWorkspaceName={setWorkspaceName}
                team={team}
                setTeam={setTeam}
              />
            )}
            {step === 1 && <PipelineStep sources={sources} setSources={setSources} />}
            {step === 2 && <ChannelsStep channels={channels} setChannels={setChannels} />}
            {step === 3 && (
              <ReviewStep
                workspaceName={workspaceName}
                team={team}
                sources={sources}
                channels={channels}
                onLaunch={handleLaunch}
                launching={launching}
                launched={launched}
              />
            )}
          </motion.div>
        </AnimatePresence>

        {!launched && (
          <div className="flex items-center justify-between mt-8 pt-6 border-t border-border">
            <button
              onClick={() => setStep((s) => Math.max(0, s - 1))}
              disabled={step === 0}
              className="flex items-center gap-1.5 px-4 py-2 text-sm text-muted-foreground hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <ArrowLeft className="w-4 h-4" /> Back
            </button>
            {step < STEPS.length - 1 && (
              <button
                onClick={() => setStep((s) => Math.min(STEPS.length - 1, s + 1))}
                className="flex items-center gap-1.5 px-5 py-2.5 bg-brand text-white text-sm font-medium rounded-xl hover:bg-brand-2 transition"
              >
                Next <ArrowRight className="w-4 h-4" />
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
