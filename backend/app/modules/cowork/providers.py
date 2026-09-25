"""Connector provider catalog for Co-work Connections.

Each provider describes *how* a real-estate team plugs an external system in:
which credentials it needs, what the platform can do with it (capabilities),
how a connection is health-checked, and — importantly for UAE portals — what
is gated behind partner certification or only available as a one-way feed.

Portal notes (researched, provider-dependent):
- Property Finder: listings & leads via the partner API; requires a
  Property Finder partner/API key issued to a certified broker account.
- Bayut / Dubizzle (same group): listings are *published* through an XML feed
  that the portal crawls; there is no public lead API — leads arrive as
  notification e-mails (parse via Gmail connector) or a portal webhook where
  the account manager enables one.
- CRMs: PropSpace / Pixxi / Bitrix24 / HubSpot / Zoho / Propertybase expose
  REST APIs with API-key or OAuth auth; the standalone UAE CRM is the
  preferred authoritative source once deployed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Category = Literal["crm", "portal", "messaging", "email", "calendar", "ai", "data"]
AuthKind = Literal["api_key", "oauth_token", "webhook_secret", "feed_url", "none"]
Capability = Literal[
    "pull_listings",
    "publish_listings",
    "receive_leads",
    "pull_leads",
    "push_leads",
    "sync_stages",
    "send_message",
    "receive_message",
    "send_email",
    "read_email",
    "create_event",
    "notify",
    "llm",
    "score_leads",
    "send_voice_note",
]


@dataclass(frozen=True)
class ConfigField:
    key: str
    label: str
    secret: bool = False
    required: bool = True
    placeholder: str = ""
    help: str = ""


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    name: str
    category: Category
    description: str
    auth: AuthKind
    capabilities: tuple[Capability, ...]
    fields: tuple[ConfigField, ...] = ()
    inbound_webhook: bool = False
    certification: str | None = None
    docs_url: str | None = None
    test_method: str = "config"
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "auth": self.auth,
            "capabilities": list(self.capabilities),
            "fields": [f.__dict__ for f in self.fields],
            "inbound_webhook": self.inbound_webhook,
            "certification": self.certification,
            "docs_url": self.docs_url,
            "test_method": self.test_method,
            "tags": list(self.tags),
        }


_BASE_URL = ConfigField("base_url", "API base URL", placeholder="https://", help="Public HTTPS host only.")
_API_KEY = ConfigField("api_key", "API key", secret=True)
_ACCESS_TOKEN = ConfigField("access_token", "Access token", secret=True)

PROVIDERS: tuple[ProviderSpec, ...] = (
    # ---- CRMs -------------------------------------------------------------
    ProviderSpec(
        "realestate_crm",
        "Real-estate CRM (standalone)",
        "crm",
        "The purpose-built UAE CRM. Authoritative source for leads, stages, listings and deals.",
        "api_key",
        ("pull_leads", "push_leads", "receive_leads", "sync_stages", "pull_listings"),
        (_BASE_URL, _API_KEY),
        inbound_webhook=True,
        test_method="http_ping",
        tags=("authoritative",),
    ),
    ProviderSpec(
        "propspace",
        "PropSpace",
        "crm",
        "UAE brokerage CRM. Two-way lead and listing sync via REST API.",
        "api_key",
        ("pull_leads", "push_leads", "sync_stages", "pull_listings"),
        (ConfigField("base_url", "API base URL", placeholder="https://api.propspace.com"), _API_KEY),
        test_method="http_ping",
    ),
    ProviderSpec(
        "pixxi",
        "Pixxi CRM",
        "crm",
        "Dubai real-estate CRM with portal publishing. Lead pull and stage write-back.",
        "api_key",
        ("pull_leads", "push_leads", "sync_stages"),
        (_BASE_URL, _API_KEY),
        test_method="http_ping",
    ),
    ProviderSpec(
        "bitrix24",
        "Bitrix24",
        "crm",
        "Bitrix24 REST via an inbound webhook URL (crm.lead.list / crm.lead.add).",
        "api_key",
        ("pull_leads", "push_leads", "sync_stages"),
        (ConfigField("webhook_url", "Inbound webhook URL", secret=True, placeholder="https://<portal>.bitrix24.com/rest/1/<code>/"),),
        test_method="http_ping",
    ),
    ProviderSpec(
        "hubspot",
        "HubSpot",
        "crm",
        "HubSpot CRM contacts & deals with a private-app token.",
        "oauth_token",
        ("pull_leads", "push_leads", "sync_stages"),
        (_ACCESS_TOKEN,),
        test_method="http_ping",
    ),
    ProviderSpec(
        "zoho_crm",
        "Zoho CRM",
        "crm",
        "Zoho CRM leads module (OAuth refresh-token flow).",
        "oauth_token",
        ("pull_leads", "push_leads", "sync_stages"),
        (ConfigField("base_url", "API domain", placeholder="https://www.zohoapis.com"), _ACCESS_TOKEN),
        test_method="http_ping",
    ),
    ProviderSpec(
        "propertybase",
        "Propertybase (Salesforce)",
        "crm",
        "Salesforce-based real-estate CRM; also the usual portal-feed publisher.",
        "oauth_token",
        ("pull_leads", "push_leads", "sync_stages", "publish_listings"),
        (ConfigField("base_url", "Instance URL", placeholder="https://<org>.my.salesforce.com"), _ACCESS_TOKEN),
        test_method="http_ping",
    ),
    ProviderSpec(
        "generic_crm",
        "Generic REST CRM",
        "crm",
        "Any CRM with a JSON list endpoint — configure URL, auth header and field paths.",
        "api_key",
        ("pull_leads", "push_leads"),
        (
            ConfigField("base_url", "List endpoint URL", placeholder="https://crm.example.com/api/leads"),
            ConfigField("api_key", "Bearer token", secret=True, required=False),
            ConfigField("items_path", "Items JSON path", required=False, placeholder="data.items"),
        ),
        test_method="http_ping",
    ),
    # ---- Portals ----------------------------------------------------------
    ProviderSpec(
        "property_finder",
        "Property Finder",
        "portal",
        "Daily pull of your live listings and portal leads through the partner API.",
        "api_key",
        ("pull_listings", "publish_listings", "pull_leads", "receive_leads"),
        (
            ConfigField("base_url", "API base URL", placeholder="https://api.propertyfinder.ae", required=False),
            _API_KEY,
            ConfigField("broker_id", "Broker / agency id", required=False),
        ),
        inbound_webhook=True,
        certification="Requires a Property Finder partner API key (certified broker account).",
        docs_url="https://www.propertyfinder.ae/en/broker",
        test_method="http_ping",
        tags=("uae", "daily-listings"),
    ),
    ProviderSpec(
        "bayut",
        "Bayut",
        "portal",
        "Publish listings via XML feed; leads arrive by e-mail or an account-manager-enabled webhook.",
        "feed_url",
        ("publish_listings", "receive_leads"),
        (
            ConfigField("feed_url", "Public XML feed URL", placeholder="https://your-domain/feeds/bayut.xml"),
            ConfigField("lead_email", "Lead notification mailbox", required=False, placeholder="leads@agency.ae", help="Parsed via a Gmail connection."),
        ),
        inbound_webhook=True,
        certification="No public lead API — one-way listing feed; lead webhook is enabled per account.",
        test_method="feed_fetch",
        tags=("uae",),
    ),
    ProviderSpec(
        "dubizzle",
        "Dubizzle Property",
        "portal",
        "Same feed format as Bayut (same group). One-way listing publish; e-mail leads.",
        "feed_url",
        ("publish_listings", "receive_leads"),
        (
            ConfigField("feed_url", "Public XML feed URL", placeholder="https://your-domain/feeds/dubizzle.xml"),
            ConfigField("lead_email", "Lead notification mailbox", required=False),
        ),
        inbound_webhook=True,
        certification="No public lead API — one-way listing feed; lead webhook is enabled per account.",
        test_method="feed_fetch",
        tags=("uae",),
    ),
    ProviderSpec(
        "meta_lead_ads",
        "Meta Lead Ads (Facebook / Instagram)",
        "portal",
        "Instant-form leads from Facebook and Instagram campaigns: real-time leadgen webhook plus a scheduled pull of every form on the page.",
        "oauth_token",
        ("receive_leads", "pull_leads"),
        (
            ConfigField("page_id", "Facebook Page id"),
            ConfigField("access_token", "Page access token", secret=True, help="Needs leads_retrieval + pages_manage_ads."),
            ConfigField("app_secret", "App secret", secret=True, required=False, help="Verifies X-Hub-Signature-256 on webhooks."),
            ConfigField("verify_token", "Webhook verify token", secret=True, required=False),
        ),
        inbound_webhook=True,
        docs_url="https://developers.facebook.com/docs/marketing-api/guides/lead-ads/retrieving",
        test_method="http_ping",
        tags=("ads", "leads"),
    ),
    ProviderSpec(
        "broker_api",
        "Broker / developer lead API",
        "portal",
        "Any developer, aggregator or referral partner exposing a JSON leads or listings endpoint (bearer token).",
        "api_key",
        ("pull_leads", "pull_listings"),
        (
            _BASE_URL,
            ConfigField("api_key", "Bearer token", secret=True, required=False),
            ConfigField("leads_path", "Leads path", required=False, placeholder="/leads"),
            ConfigField("listings_path", "Listings path", required=False, placeholder="/listings"),
            ConfigField("items_path", "Items JSON path", required=False, placeholder="data"),
        ),
        test_method="http_ping",
    ),
    ProviderSpec(
        "portal_webhook",
        "Generic lead webhook",
        "portal",
        "HMAC-signed JSON webhook for any portal, website form, Meta Lead Ads relay or n8n flow.",
        "webhook_secret",
        ("receive_leads",),
        (),
        inbound_webhook=True,
        test_method="webhook",
    ),
    # ---- Messaging / e-mail / calendar -----------------------------------
    ProviderSpec(
        "whatsapp",
        "WhatsApp Business (Meta Cloud API)",
        "messaging",
        "Send templates & free-form replies, receive buyer messages, deliver follow-ups.",
        "oauth_token",
        ("send_message", "receive_message", "notify"),
        (
            ConfigField("phone_number_id", "Phone number id"),
            _ACCESS_TOKEN,
            ConfigField("verify_token", "Webhook verify token", secret=True, required=False),
        ),
        inbound_webhook=True,
        test_method="http_ping",
    ),
    ProviderSpec(
        "voice_notes",
        "Automated voice notes",
        "messaging",
        "Turns a personalised follow-up into speech (Piper / configured TTS) and delivers it as a WhatsApp audio message. Independent of the text WhatsApp connector; no text fallback.",
        "oauth_token",
        ("send_voice_note",),
        (
            ConfigField("phone_number_id", "WhatsApp phone number id"),
            _ACCESS_TOKEN,
            ConfigField("voice_language", "Default voice", required=False, placeholder="en | ar"),
        ),
        test_method="voice_ping",
        tags=("voice", "follow-up"),
    ),
    ProviderSpec(
        "gmail",
        "Gmail",
        "email",
        "Reads portal lead e-mails (Bayut, Dubizzle, Property Finder, website forms), extracts a structured lead and adds it to the CRM; also sends follow-ups.",
        "oauth_token",
        ("read_email", "send_email", "receive_leads", "pull_leads"),
        (
            ConfigField("mailbox", "Mailbox", placeholder="leads@agency.ae"),
            _ACCESS_TOKEN,
            ConfigField("label", "Label / query", required=False, placeholder="from:(bayut.com OR dubizzle.com) newer_than:1d"),
        ),
        test_method="http_ping",
    ),
    ProviderSpec(
        "google_calendar",
        "Google Calendar",
        "calendar",
        "Create viewing appointments and send invites to buyers and brokers.",
        "oauth_token",
        ("create_event",),
        (ConfigField("calendar_id", "Calendar id", placeholder="primary"), _ACCESS_TOKEN),
        test_method="http_ping",
    ),
    ProviderSpec(
        "slack",
        "Slack",
        "messaging",
        "Team notifications (hot leads, failed runs, daily digest) via incoming webhook.",
        "webhook_secret",
        ("notify",),
        (ConfigField("webhook_url", "Incoming webhook URL", secret=True, placeholder="https://hooks.slack.com/services/..."),),
        test_method="http_ping",
    ),
    # ---- AI / data ----------------------------------------------------------
    ProviderSpec(
        "typesafe_jev",
        "TypeSafe AI · Jev",
        "ai",
        "System One model that returns typed, calibrated decisions (band, readiness, intent, financing) instead of text. Used for lead scoring and qualification.",
        "api_key",
        ("score_leads",),
        (
            _API_KEY,
            ConfigField("model", "Model", required=False, placeholder="jev-latest"),
            ConfigField("base_url", "API base URL", required=False, placeholder="https://api.typesafe.ai"),
        ),
        docs_url="https://typesafe.ai",
        test_method="jev_ping",
        tags=("scoring", "qualification", "calibrated"),
    ),
    ProviderSpec(
        "llm",
        "LLM gateway",
        "ai",
        "Groq / OpenAI-compatible models used by routines for extraction, scoring, summaries and drafts.",
        "none",
        ("llm",),
        (),
        test_method="llm_ping",
    ),
    ProviderSpec(
        "google_sheets",
        "Google Sheets",
        "data",
        "Append leads / listings to a sheet for reporting or manual review.",
        "oauth_token",
        ("push_leads", "notify"),
        (ConfigField("spreadsheet_id", "Spreadsheet id"), _ACCESS_TOKEN),
        test_method="http_ping",
    ),
)

PROVIDER_INDEX: dict[str, ProviderSpec] = {p.id: p for p in PROVIDERS}


def get_provider(provider_id: str) -> ProviderSpec | None:
    return PROVIDER_INDEX.get(provider_id)


def secret_keys(spec: ProviderSpec) -> set[str]:
    return {f.key for f in spec.fields if f.secret}
