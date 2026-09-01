"""Tests for budget/currency extraction.

These encode the exact failure modes a Dubai broker flagged as trust-killing:
a bare "1.2" being read as AED 1.20, a bedroom count leaking into the budget,
and per-year rent being confused with a total purchase price.
"""
from app.services.budget_extraction import describe_budget, extract_budget


def test_bare_number_asks_instead_of_guessing():
    result = extract_budget("my budget is 1.2")
    assert result.needs_clarification
    assert "million" in result.clarifying_question
    # Nothing is written to the lead while the value is ambiguous.
    assert result.to_lead_fields() == {}


def test_bedroom_count_is_not_treated_as_budget():
    result = extract_budget("looking to buy a 2 bed in Marina, budget AED 1.8M")
    assert result.amount_min == 1_800_000
    assert result.amount_max == 1_800_000
    assert result.currency == "AED"
    assert result.intent == "buy"
    assert not result.needs_clarification


def test_size_in_sqft_is_not_treated_as_budget():
    result = extract_budget("3 bedroom villa 1800 sqft, purchase price 4.5M AED")
    assert result.amount_max == 4_500_000


def test_per_year_rent_is_not_read_as_total():
    result = extract_budget("rent up to 120,000 AED annually")
    assert result.period == "year"
    assert result.intent == "rent"
    assert describe_budget(result) == "AED 120,000 per year"


def test_missing_currency_triggers_clarification():
    result = extract_budget("I want to rent, 80k per year in JVC")
    assert result.needs_clarification
    assert "AED" in result.clarifying_question
    # Period/intent are known and still recorded; the amount is withheld.
    fields = result.to_lead_fields()
    assert fields["budget_period"] == "year"
    assert "budget_max" not in fields


def test_usd_is_converted_for_comparison_but_currency_is_preserved():
    result = extract_budget("budget is USD 500k to buy")
    assert result.currency == "USD"
    assert result.amount_max == 500_000
    assert result.amount_max_aed == 1_836_250.0
    assert describe_budget(result) == "USD 500,000"


def test_range_is_captured():
    result = extract_budget("between 900k and 1.4m AED to buy")
    assert result.amount_min == 900_000
    assert result.amount_max == 1_400_000


def test_purchase_implies_total_period():
    result = extract_budget("around 1,200,000 dirhams for purchase")
    assert result.period == "total"
    assert not result.needs_clarification


def test_no_amount_is_not_an_error():
    result = extract_budget("hello i am interested")
    assert result.amount_min is None
    assert not result.needs_clarification
    assert describe_budget(result) == "your budget"


def test_empty_input():
    result = extract_budget("")
    assert result.amount_min is None
    assert result.to_lead_fields() == {}
