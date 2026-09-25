from app.modules.agents.extractor import _bedrooms
from app.modules.geo.communities import resolve_area


def _ids(text: str) -> list[str]:
    return sorted(m.community.id for m in resolve_area(text))


def test_longer_name_owns_its_words():
    assert _ids("villa in palm jumeirah") == ["palm_jumeirah"]
    assert _ids("rent in jumeirah beach residence") == ["jbr"]
    assert _ids("townhouse in damac hills") == ["damac_hills"]
    assert _ids("شقة في قرية جميرا الدائرية") == ["jvc"]


def test_separate_mentions_are_all_kept():
    assert _ids("marina or jlt") == ["dubai_marina", "jlt"]
    assert _ids("villa in jumeirah") == ["jumeirah"]


def test_arabic_digit_room_count():
    assert _bedrooms("شقة 3 غرف") == 3
    assert _bedrooms("غرفتين") == 2
