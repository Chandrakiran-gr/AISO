"""Domain ports and framework-neutral data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class BusinessProfileSnapshot:
    client_id: str
    vertical: str
    objective: str
    category: str = ""
    icp: dict[str, Any] = field(default_factory=dict)
    geographic_scope: dict[str, Any] = field(default_factory=dict)
    competitors: list[str] = field(default_factory=list)
    personas: dict[str, Any] = field(default_factory=dict)
    crawl_artifacts: dict[str, Any] = field(default_factory=dict)
    floor_met: bool = False
    onboarding_completed_at: datetime | None = None
    founder_reviewed_at: datetime | None = None


class BusinessProfileStore(Protocol):
    def get_profile(self, client_id: str) -> BusinessProfileSnapshot | None: ...
