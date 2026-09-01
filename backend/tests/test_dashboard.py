from app.services.dashboard import summarize_leads


def test_dashboard_summary_is_derived_from_workspace_leads():
    summary = summarize_leads(
        [
            {"status": "new", "intent_score": 80, "assigned_broker": None},
            {"status": "qualified", "intent_score": 60, "assigned_broker": "broker-1"},
            {"status": "closed", "intent_score": 100, "assigned_broker": "broker-1"},
        ]
    )

    assert summary == {
        "total_leads": 3,
        "qualified_leads": 2,
        "closed_leads": 1,
        "unassigned_leads": 1,
        "average_intent_score": 80.0,
        "status_counts": {"new": 1, "qualified": 1, "closed": 1},
    }
