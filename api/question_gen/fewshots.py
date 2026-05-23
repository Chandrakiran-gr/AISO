"""Few-shot library loading for Phase 12 question generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


FEWSHOT_DIR = Path(__file__).resolve().parents[2] / "prompts" / "question_gen_fewshots"


def load_vertical_fewshots(vertical: str) -> list[dict[str, Any]]:
    path = FEWSHOT_DIR / f"{vertical}.yml"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    examples = raw.get("examples") if isinstance(raw, dict) else None
    if not isinstance(examples, list):
        return []
    return [example for example in examples if isinstance(example, dict)]
