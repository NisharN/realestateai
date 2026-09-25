import pytest

from scripts.run_evals import load_cases, run_all


def test_cases_file_is_well_formed():
    cases = load_cases()
    assert len(cases) >= 10
    assert len({c["id"] for c in cases}) == len(cases)
    assert all(c["turns"] for c in cases)


@pytest.mark.asyncio
async def test_offline_evals_pass():
    results = await run_all()
    failing = [r for r in results if not r.ok]
    assert not failing, "\n".join(f"{r.id}: {r.failures}" for r in failing)
