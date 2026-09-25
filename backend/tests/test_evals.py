import pytest

from scripts.run_evals import load_cases, run_all


def test_cases_file_is_well_formed():
    cases = load_cases()
    assert len(cases) >= 40
    assert len({c["id"] for c in cases}) == len(cases)
    assert all(c["turns"] for c in cases)


@pytest.mark.asyncio
async def test_offline_evals_pass():
    results = await run_all()
    failing = [r for r in results if not r.ok]
    assert not failing, "\n".join(f"{r.id}: {r.failures}" for r in failing)


def test_matrix_expands_to_target_size():
    cases = load_cases()
    assert len(cases) >= 180
    assert any(c["id"].startswith("ar_one_shot__") for c in cases)
    marina = next(c for c in cases if c["id"] == "en_one_shot__marina_apt_buy")
    assert marina["turns"][0]["slots"] == {"purpose": "buy", "area": ["Dubai Marina"]}
    assert marina["turns"][1]["slots"] == {"budget.max_aed": 2500000}
