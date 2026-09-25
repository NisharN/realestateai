from app.modules.voice.speakify import number_words, speakify


def test_number_words_scales():
    assert number_words(1850000) == "one point eight five million"
    assert number_words(120000) == "one hundred twenty thousand"
    assert number_words(2) == "two"


def test_aed_prices_are_spoken_not_read_digit_by_digit():
    out = speakify("Priced at AED 1,850,000 in Dubai Marina.")
    assert "1,850,000" not in out
    assert "million dirhams" in out


def test_units_and_travel_facts():
    out = speakify("1,200 sq ft, about 15 min to DIFC and 3.5 km to the beach, up to 7% yield.")
    assert "square feet" in out
    assert "15 minutes" in out
    assert "kilometres" in out
    assert "percent" in out
    assert "sq ft" not in out and "%" not in out


def test_arabic_keeps_digits_but_localises_currency():
    out = speakify("السعر AED 2,500,000", language="ar")
    assert "درهم" in out and "AED" not in out
