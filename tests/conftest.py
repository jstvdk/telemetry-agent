from pathlib import Path

import pytest

from shiftassist.sim.generator import SimResult, generate
from shiftassist.sim.scenario import Scenario, load_scenario

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = sorted((ROOT / "scenarios").glob("S*.yaml"))


def scenario(sid: str) -> Scenario:
    (path,) = [p for p in SCENARIOS if p.name.startswith(sid + "-")]
    return load_scenario(path)


_cache: dict[str, SimResult] = {}


@pytest.fixture
def sim() -> "type[SimCache]":
    return SimCache


class SimCache:
    """Generate each scenario once per test session (they take ~0.1-0.5 s each)."""

    @staticmethod
    def get(sid: str) -> SimResult:
        if sid not in _cache:
            _cache[sid] = generate(scenario(sid))
        return _cache[sid]
