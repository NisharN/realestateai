"""Tests for the workflow templates.

These encode the decisions the advisory rounds landed on, so a future change
that quietly reverses one of them fails loudly:

- a lead that has already been contacted is never re-messaged automatically
- hot leads escalate to a human rather than being handled by AI alone
- stale listings produce *copy to paste*, never an automated portal post
- no workflow can dial a lead without a human approving it
"""
from datetime import datetime, timedelta, timezone

from app.services import workflows as wf

NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
SETTINGS = wf.WorkflowSettings()


def _lead(**overrides):
    base = {
        "id": "lead-1",
        "first_name": "Ahmed",
        "phone": "+971501234567",
        "created_at": (NOW - timedelta(hours=1)).isoformat(),
        "intent_score": 30,
        "status": "new",
        "last_contact_at": None,
    }
    base.update(overrides)
    return base


class TestNewLeadFollowup:
    def test_uncontacted_lead_gets_a_message(self):
        actions = wf.evaluate_new_lead_followup([_lead()], NOW, SETTINGS)
        assert len(actions) == 1
        assert actions[0].action == wf.ActionType.SEND_WHATSAPP
        assert actions[0].recipient == "+971501234567"

    def test_already_contacted_lead_is_left_alone(self):
        lead = _lead(last_contact_at=NOW.isoformat())
        assert wf.evaluate_new_lead_followup([lead], NOW, SETTINGS) == []

    def test_very_fresh_lead_waits_so_a_human_can_go_first(self):
        lead = _lead(created_at=(NOW - timedelta(minutes=1)).isoformat())
        assert wf.evaluate_new_lead_followup([lead], NOW, SETTINGS) == []

    def test_hot_lead_escalates_to_a_human(self):
        actions = wf.evaluate_new_lead_followup([_lead(intent_score=85)], NOW, SETTINGS)
        kinds = {a.action for a in actions}
        assert wf.ActionType.ESCALATE_TO_HUMAN in kinds
        assert wf.ActionType.SEND_WHATSAPP in kinds

    def test_closed_lead_is_never_messaged(self):
        assert wf.evaluate_new_lead_followup([_lead(status="closed")], NOW, SETTINGS) == []


class TestListingStaleness:
    def _listing(self, days_ago: int, **overrides):
        base = {
            "id": "p-1",
            "title": "2BR Marina",
            "area": "Dubai Marina",
            "is_active": True,
            "last_refreshed_at": (NOW - timedelta(days=days_ago)).isoformat(),
        }
        base.update(overrides)
        return base

    def test_stale_listing_generates_copy_not_a_post(self):
        actions = wf.evaluate_listing_staleness([self._listing(20)], NOW, SETTINGS)
        assert len(actions) == 1
        # The critical assertion: we generate copy, we never post it anywhere.
        assert actions[0].action == wf.ActionType.GENERATE_LISTING_COPY
        assert actions[0].metadata["days_stale"] == 20

    def test_fresh_listing_is_ignored(self):
        assert wf.evaluate_listing_staleness([self._listing(3)], NOW, SETTINGS) == []

    def test_inactive_listing_is_ignored(self):
        listing = self._listing(30, is_active=False)
        assert wf.evaluate_listing_staleness([listing], NOW, SETTINGS) == []


class TestMandateRenewal:
    def _mandate(self, days_out: int, **overrides):
        base = {
            "id": "m-1",
            "status": "active",
            "property_title": "Palm Villa",
            "agent_id": "broker-1",
            "expires_at": (NOW + timedelta(days=days_out)).isoformat(),
            "renewal_notified_at": None,
        }
        base.update(overrides)
        return base

    def test_expiring_mandate_warns_the_agent(self):
        actions = wf.evaluate_mandate_renewals([self._mandate(20)], NOW, SETTINGS)
        assert len(actions) == 1
        assert actions[0].action == wf.ActionType.NOTIFY_AGENT
        assert actions[0].metadata["days_left"] == 20

    def test_distant_expiry_is_not_yet_actioned(self):
        assert wf.evaluate_mandate_renewals([self._mandate(200)], NOW, SETTINGS) == []

    def test_already_notified_mandate_is_not_repeated(self):
        mandate = self._mandate(20, renewal_notified_at=NOW.isoformat())
        assert wf.evaluate_mandate_renewals([mandate], NOW, SETTINGS) == []


class TestViewingReminders:
    def _viewing(self, hours_out: int, **overrides):
        base = {
            "id": "v-1",
            "lead_name": "Ahmed",
            "phone": "+971501234567",
            "property_title": "Marina Gate",
            "scheduled_at": (NOW + timedelta(hours=hours_out)).isoformat(),
            "status": "scheduled",
            "reminder_sent_at": None,
        }
        base.update(overrides)
        return base

    def test_viewing_inside_the_window_is_reminded(self):
        actions = wf.evaluate_viewing_reminders([self._viewing(6)], NOW, SETTINGS)
        assert len(actions) == 1
        assert "Marina Gate" in actions[0].message

    def test_viewing_beyond_the_window_waits(self):
        assert wf.evaluate_viewing_reminders([self._viewing(72)], NOW, SETTINGS) == []

    def test_cancelled_viewing_is_not_reminded(self):
        viewing = self._viewing(6, status="cancelled")
        assert wf.evaluate_viewing_reminders([viewing], NOW, SETTINGS) == []

    def test_persisted_viewing_rows_use_starts_at_and_done(self):
        upcoming = self._viewing(6, scheduled_at=None, starts_at=(NOW + timedelta(hours=6)).isoformat(), status="confirmed")
        assert len(wf.evaluate_viewing_reminders([upcoming], NOW, SETTINGS)) == 1
        done = self._viewing(-30, scheduled_at=None, starts_at=(NOW - timedelta(hours=30)).isoformat(), status="done")
        assert len(wf.evaluate_post_viewing_nudge([done], NOW, SETTINGS)) == 1


class TestVoiceGate:
    def _action(self):
        return wf.WorkflowAction(
            template=wf.WorkflowTemplate.NEW_LEAD_FOLLOWUP,
            action=wf.ActionType.REQUEST_VOICE_APPROVAL,
            subject_id="lead-1",
            subject_type="lead",
        )

    def test_voice_is_blocked_when_outbound_is_disabled(self):
        gated = wf.gate_voice_action(
            self._action(), voice_outbound_enabled=False, require_human_approval=True
        )
        assert gated.metadata["blocked"] == "voice_outbound_disabled"

    def test_voice_requires_human_approval_even_when_enabled(self):
        gated = wf.gate_voice_action(
            self._action(), voice_outbound_enabled=True, require_human_approval=True
        )
        assert gated.metadata["requires_approval"] is True
        assert "blocked" not in gated.metadata

    def test_non_voice_actions_pass_through_untouched(self):
        action = wf.WorkflowAction(
            template=wf.WorkflowTemplate.NEW_LEAD_FOLLOWUP,
            action=wf.ActionType.SEND_WHATSAPP,
            subject_id="lead-1",
            subject_type="lead",
        )
        gated = wf.gate_voice_action(
            action, voice_outbound_enabled=False, require_human_approval=True
        )
        assert gated.metadata == {}
