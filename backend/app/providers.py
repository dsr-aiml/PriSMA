import json
from pathlib import Path
from typing import Protocol

from .schemas import FixtureEvidence


class InvestigationProvider(Protocol):
    def collect(self, depth: str) -> list[FixtureEvidence]: ...


class DemoProvider:
    """Never navigates to the requested target. Always returns fictional Atlas fixtures."""

    def collect(self, depth: str) -> list[FixtureEvidence]:
        fixture = json.loads((Path(__file__).parent.parent / "fixtures" / "atlas.json").read_text())
        items = [FixtureEvidence.model_validate(item) for item in fixture["evidence"]]
        return items[:3] if depth == "quick" else items


class SavedSourceCollector(Protocol):
    """Collection boundary shared by manual snapshots and future live search/fetch."""

    def collect(self, target: str) -> list[dict]: ...


# Live collection lives in collection.py; it shares no fixture annotations or cache keys.
from .collection import TinyFishCollector as TinyFishSearchFetch  # noqa: E402,F401
