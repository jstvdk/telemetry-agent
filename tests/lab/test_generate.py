"""The held-out generator keeps its promises for any seed (PROVENANCE D-18e)."""

import pytest

from shiftassist.lab.faults import seconds
from shiftassist.lab.generate import CATALOG, PAIRS, generate
from shiftassist.lab.harness import Scenario, groups

SEEDS = [f"{i * 2654435761 % 2**32:08x}" for i in range(1, 60)]


@pytest.mark.parametrize("seed", SEEDS)
def test_generated_scenarios_keep_the_protocol(seed: str) -> None:
    sc = generate(seed)
    parsed = Scenario.model_validate(sc)  # runnable
    kinds = [f.kind for f in parsed.faults]
    assert set(CATALOG) <= set(kinds) and len(kinds) == len(CATALOG) + 3
    pairs = [g for g in groups(parsed.faults) if len(g) > 1]
    assert len(pairs) == PAIRS and all(len(g) == 2 for g in pairs)
    for (_, a), (_, b) in pairs:
        gap = seconds(b.at) - seconds(a.at)
        assert 5 <= gap <= 20 and gap < seconds(a.hold), "second starts while the first is held"


def test_same_seed_same_scenario_and_seeds_differ() -> None:
    assert generate("1a946e1f") == generate("1a946e1f")
    assert generate("1a946e1f")["faults"] != generate("1a946e20")["faults"]


def test_extra_faults_are_inserted_alone() -> None:
    extra = {"kind": "gatherer_down", "hold": "41s"}
    for seed in SEEDS[:20]:
        sc = Scenario.model_validate(generate(seed, [extra]))
        (i,) = [i for i, f in enumerate(sc.faults) if f.kind == "gatherer_down" and f.hold == "41s"]
        nxt = sc.faults[i + 1] if i + 1 < len(sc.faults) else None
        assert not sc.faults[i].overlap and not (nxt and nxt.overlap)
