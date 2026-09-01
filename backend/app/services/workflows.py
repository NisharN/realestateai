"""Hardcoded workflow templates — the reminders engine.

This is deliberately NOT a visual workflow builder. Three advisors
independently rejected the canvas (see docs/workflow_builder_validation.md):
it rebuilds n8n by hand, it contradicts the forward-deployed-engineer model
where the customer pays specifically so they don't configure anything, and the
broker was blunt that no agent will open a node editor between viewings.

What replaced it: a fixed set of templates with a handful of thresholds. The
founder picks which templates a deployment runs and tunes the numbers. Each
template is a pure function that decides *what should happen*; the Celery
worker is what actually runs them on a schedule.

Keeping the decision logic pure (no DB, no network) means every rule here is
directly testable and can't silently drift.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional


class WorkflowTemplate(str, Enum):
    """The templates a deployment can enable. No custom graphs."""

    NEW_LEAD_FOLLOWUP = "new_lead_followup"
    VIEWING_REMINDER = "viewing_reminder"
    MANDATE_RENEWAL = "mandate_renewal"
    LISTING_STALE = "listing_stale"
    POST_VIEWING_NUDGE = "post_viewing_nudge"


class ActionType(str, Enum):
    SEND_WHATSAPP = "send_whatsapp"
    NOTIFY_AGENT = "notify_agent"
    ESCALATE_TO_HUMAN = "escalate_to_human"
    GENERATE_LISTING_COPY = "generate_listing_copy"
    REQUEST_VOICE_APPROVAL = "request_voice_approval"


@dataclass
class WorkflowAction:
    """One thing the engine decided should happen. Nothing is sent from here."""

    template: WorkflowTemplate
    action: ActionType
    subject_id: str                       # lead id, listing id, mandate id
    subject_type: str                     # "lead" | "property" | "mandate"
    message: Optional[str] = None
    recipient: Optional[str] = None       # phone for WhatsApp, user id for notify
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template": self.template.value,
            "action": self.action.value,
            "subject_id": self.subject_id,
            "subject_type": self.subject_type,
            "message": self.message,
            "recipient": self.recipient,
            "reason": self.reason,
            "metadata": self.metadata,
        }


@dataclass
class WorkflowSettings:
    """Tunable knobs. These are the whole configuration surface."""

    followup_delay_minutes: int = 5
    viewing_reminder_hours: int = 24
    mandate_renewal_lead_days: int = 45
    listing_stale_days: int = 14
    hot_lead_score: int = 60
    enabled: List[WorkflowTemplate] = field(
        default_factory=lambda: list(WorkflowTemplate)
    )

    @classmethod
    def from_settings(cls, settings: Any) -> "WorkflowSettings":
        return cls(
            followup_delay_minutes=settings.FOLLOWUP_DELAY_MINUTES,
            viewing_reminder_hours=settings.VIEWING_REMINDER_HOURS,
            mandate_renewal_lead_days=settings.MANDATE_RENEWAL_LEAD_DAYS,
            listing_stale_days=settings.LISTING_STALE_DAYS,
            hot_lead_score=settings.HOT_LEAD_SCORE,
        )


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _first_name(lead: Mapping[str, Any]) -> str:
    name = (lead.get("first_name") or "").strip()
    return name or "there"


# --------------------------------------------------------------------------
# Template 1: new lead follow-up  (the "leads die overnight" fix)
# --------------------------------------------------------------------------

def evaluate_new_lead_followup(
    leads: Iterable[Mapping[str, Any]],
    now: datetime,
    settings: WorkflowSettings,
) -> List[WorkflowAction]:
    """A new lead with no contact yet gets a WhatsApp within minutes.

    The broker's #1 named bleed: a portal enquiry lands at 11pm, the agent
    sees it at 9am, and three other brokers have already replied. This closes
    that window. Hot leads additionally escalate to a human immediately —
    the AI opens the conversation, it does not own it.
    """
    actions: List[WorkflowAction] = []
    cutoff = now - timedelta(minutes=settings.followup_delay_minutes)

    for lead in leads:
        if lead.get("last_contact_at"):
            continue  # already spoken to
        if lead.get("status") in {"closed", "lost"}:
            continue
        created = _parse_dt(lead.get("created_at"))
        if created is None or created > cutoff:
            continue  # too fresh — give the human a chance first

        lead_id = str(lead.get("id"))
        score = int(lead.get("intent_score") or 0)

        actions.append(
            WorkflowAction(
                template=WorkflowTemplate.NEW_LEAD_FOLLOWUP,
                action=ActionType.SEND_WHATSAPP,
                subject_id=lead_id,
                subject_type="lead",
                recipient=lead.get("phone"),
                message=(
                    f"Hi {_first_name(lead)}, thanks for your enquiry. "
                    "I can send you a few options that match what you're after — "
                    "could you confirm your budget and which area you prefer?"
                ),
                reason="new lead with no contact yet",
                metadata={"intent_score": score},
            )
        )

        if score >= settings.hot_lead_score:
            actions.append(
                WorkflowAction(
                    template=WorkflowTemplate.NEW_LEAD_FOLLOWUP,
                    action=ActionType.ESCALATE_TO_HUMAN,
                    subject_id=lead_id,
                    subject_type="lead",
                    reason=f"intent score {score} >= {settings.hot_lead_score}",
                    metadata={"intent_score": score},
                )
            )

    return actions


# --------------------------------------------------------------------------
# Template 2: viewing reminders  (table stakes, ships unmarketed)
# --------------------------------------------------------------------------

def evaluate_viewing_reminders(
    viewings: Iterable[Mapping[str, Any]],
    now: datetime,
    settings: WorkflowSettings,
) -> List[WorkflowAction]:
    """Remind a lead about a viewing N hours out, once."""
    actions: List[WorkflowAction] = []
    window_end = now + timedelta(hours=settings.viewing_reminder_hours)

    for viewing in viewings:
        if viewing.get("reminder_sent_at") or viewing.get("status") == "cancelled":
            continue
        scheduled = _parse_dt(viewing.get("scheduled_at"))
        if scheduled is None or not (now <= scheduled <= window_end):
            continue

        actions.append(
            WorkflowAction(
                template=WorkflowTemplate.VIEWING_REMINDER,
                action=ActionType.SEND_WHATSAPP,
                subject_id=str(viewing.get("id")),
                subject_type="viewing",
                recipient=viewing.get("phone"),
                message=(
                    f"Hi {viewing.get('lead_name') or 'there'}, a reminder about your viewing "
                    f"at {viewing.get('property_title') or 'the property'} on "
                    f"{scheduled.strftime('%a %d %b at %H:%M')}. Reply here if you need to reschedule."
                ),
                reason=f"viewing within {settings.viewing_reminder_hours}h",
                metadata={"scheduled_at": scheduled.isoformat()},
            )
        )

    return actions


# --------------------------------------------------------------------------
# Template 3: mandate renewal  (marketed differentiator — protects commission)
# --------------------------------------------------------------------------

def evaluate_mandate_renewals(
    mandates: Iterable[Mapping[str, Any]],
    now: datetime,
    settings: WorkflowSettings,
) -> List[WorkflowAction]:
    """Warn the agent before an exclusive mandate lapses.

    The PM's argument for marketing this one: a lapsed exclusive is a lost
    commission, so it defends revenue directly rather than just saving time.
    """
    actions: List[WorkflowAction] = []
    horizon = now + timedelta(days=settings.mandate_renewal_lead_days)

    for mandate in mandates:
        if mandate.get("renewal_notified_at") or mandate.get("status") != "active":
            continue
        expires = _parse_dt(mandate.get("expires_at"))
        if expires is None or not (now <= expires <= horizon):
            continue

        days_left = (expires - now).days
        actions.append(
            WorkflowAction(
                template=WorkflowTemplate.MANDATE_RENEWAL,
                action=ActionType.NOTIFY_AGENT,
                subject_id=str(mandate.get("id")),
                subject_type="mandate",
                recipient=mandate.get("agent_id"),
                message=(
                    f"Exclusive mandate on {mandate.get('property_title') or 'a listing'} "
                    f"expires in {days_left} days ({expires.strftime('%d %b %Y')}). "
                    "Start the renewal conversation with the owner."
                ),
                reason=f"mandate expires in {days_left} days",
                metadata={"expires_at": expires.isoformat(), "days_left": days_left},
            )
        )

    return actions


# --------------------------------------------------------------------------
# Template 4: listing staleness  (trigger only — see listing_refresh.py)
# --------------------------------------------------------------------------

def evaluate_listing_staleness(
    listings: Iterable[Mapping[str, Any]],
    now: datetime,
    settings: WorkflowSettings,
) -> List[WorkflowAction]:
    """Find listings that have gone stale and need refreshed copy.

    Note what this does NOT do: it never posts anything to Bayut, Property
    Finder, or Dubizzle. Automating a repost against a portal you don't have
    an API agreement with risks getting the customer's account banned — the
    consultant refused it outright and the PM agreed. What ships instead is
    generated copy the broker pastes herself, which solves the actual
    complaint (staring at a blank page rewriting a description) rather than
    the imagined one (forgetting to do it).
    """
    actions: List[WorkflowAction] = []
    stale_before = now - timedelta(days=settings.listing_stale_days)

    for listing in listings:
        if not listing.get("is_active", True):
            continue
        last_refreshed = _parse_dt(
            listing.get("last_refreshed_at") or listing.get("scraped_at")
        )
        if last_refreshed is None or last_refreshed > stale_before:
            continue

        days_stale = (now - last_refreshed).days
        actions.append(
            WorkflowAction(
                template=WorkflowTemplate.LISTING_STALE,
                action=ActionType.GENERATE_LISTING_COPY,
                subject_id=str(listing.get("id")),
                subject_type="property",
                reason=f"not refreshed for {days_stale} days",
                metadata={
                    "days_stale": days_stale,
                    "title": listing.get("title"),
                    "area": listing.get("area"),
                },
            )
        )

    return actions


# --------------------------------------------------------------------------
# Template 5: post-viewing nudge
# --------------------------------------------------------------------------

def evaluate_post_viewing_nudge(
    viewings: Iterable[Mapping[str, Any]],
    now: datetime,
    settings: WorkflowSettings,
) -> List[WorkflowAction]:
    """Ask for feedback the day after a completed viewing."""
    actions: List[WorkflowAction] = []

    for viewing in viewings:
        if viewing.get("followup_sent_at") or viewing.get("status") != "completed":
            continue
        scheduled = _parse_dt(viewing.get("scheduled_at"))
        if scheduled is None or now < scheduled + timedelta(hours=18):
            continue

        actions.append(
            WorkflowAction(
                template=WorkflowTemplate.POST_VIEWING_NUDGE,
                action=ActionType.SEND_WHATSAPP,
                subject_id=str(viewing.get("id")),
                subject_type="viewing",
                recipient=viewing.get("phone"),
                message=(
                    f"Hi {viewing.get('lead_name') or 'there'}, how did you find "
                    f"{viewing.get('property_title') or 'the property'}? "
                    "Happy to line up similar options, or answer anything on this one."
                ),
                reason="viewing completed, no follow-up yet",
            )
        )

    return actions


# --------------------------------------------------------------------------
# Voice gate — a standing requirement, not a template
# --------------------------------------------------------------------------

def gate_voice_action(
    action: WorkflowAction,
    voice_outbound_enabled: bool,
    require_human_approval: bool,
) -> WorkflowAction:
    """No workflow may auto-dial a lead without a human approving first.

    The broker's hard requirement once workflows entered the picture: an
    automated call fired off a scoring rule can hit a wrong number, a lead
    another agent already closed, or someone who asked not to be called — with
    nobody watching. Voice itself is deferred past the pilot, but this gate
    ships now so that can never quietly become possible later.
    """
    if action.action != ActionType.REQUEST_VOICE_APPROVAL:
        return action
    if not voice_outbound_enabled:
        action.metadata["blocked"] = "voice_outbound_disabled"
        return action
    if require_human_approval:
        action.metadata["requires_approval"] = True
    return action


TEMPLATE_LABELS = {
    WorkflowTemplate.NEW_LEAD_FOLLOWUP: "New lead → auto follow-up → escalate if hot",
    WorkflowTemplate.VIEWING_REMINDER: "Viewing reminder (24h before)",
    WorkflowTemplate.MANDATE_RENEWAL: "Mandate renewal warning",
    WorkflowTemplate.LISTING_STALE: "Stale listing → generate fresh copy",
    WorkflowTemplate.POST_VIEWING_NUDGE: "Post-viewing feedback nudge",
}
