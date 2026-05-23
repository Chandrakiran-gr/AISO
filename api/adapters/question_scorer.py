"""LLM adapters for Phase 12 question scoring."""

from __future__ import annotations

from typing import Any
import hashlib
import json
import os
import re

import requests

from api.domain.ports import ProviderResponse
from api.domain.question_scorer import weighted_score


DEFAULT_QUESTION_SCORER_MODEL = "claude-sonnet-4-20250514"


class AnthropicQuestionScorerAdapter:
    """Claude adapter for the n=3 question quality scorer."""

    provider = "anthropic"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 30.0,
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.model = model or os.getenv("AISO_QUESTION_SCORER_MODEL", DEFAULT_QUESTION_SCORER_MODEL)
        self.timeout_seconds = timeout_seconds

    def available(self) -> bool:
        return bool(self.api_key)

    def complete(
        self,
        *,
        prompt: str,
        seed: int,
        temperature: float,
        idempotency_key: str,
    ) -> ProviderResponse:
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for Claude question scoring")

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": 900,
                "temperature": temperature,
                "metadata": {"user_id": hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:64]},
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return ProviderResponse(
            text=_anthropic_text(payload),
            provider="anthropic",
            model=str(payload.get("model") or self.model),
            raw_metadata={
                "id": payload.get("id"),
                "stop_reason": payload.get("stop_reason"),
                "usage": payload.get("usage"),
                "seed": seed,
            },
        )


class HeuristicQuestionScorerAdapter:
    """Deterministic local scorer for tests and offline development."""

    provider = "local"
    model = "question-scorer-heuristic-v1"

    def complete(
        self,
        *,
        prompt: str,
        seed: int,
        temperature: float,
        idempotency_key: str,
    ) -> ProviderResponse:
        payload = _extract_runtime_inputs(prompt)
        scores, rationale = heuristic_question_scores(payload)
        response = {
            "question_id": payload.get("question_id"),
            "scores": {
                "D1": scores.d1_buyer_plausibility,
                "D2": scores.d2_commercial_proximity,
                "D3": {
                    "a": scores.d3_cognitive_answerability,
                    "b": scores.d3_cognitive_answerability,
                    "c": scores.d3_cognitive_answerability,
                    "d": scores.d3_cognitive_answerability,
                    "mean": scores.d3_cognitive_answerability,
                },
                "D4": scores.d4_diagnostic_power,
                "D5": scores.d5_statistical_identifiability,
            },
            "weighted_score": weighted_score(scores),
            "rationale": rationale,
        }
        return ProviderResponse(
            text=json.dumps(response, sort_keys=True),
            provider=self.provider,
            model=self.model,
            raw_metadata={
                "seed": seed,
                "temperature": temperature,
                "idempotency_hash": hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest(),
            },
        )


def default_question_scorer_provider():
    anthropic = AnthropicQuestionScorerAdapter()
    return anthropic if anthropic.available() else HeuristicQuestionScorerAdapter()


def heuristic_question_scores(payload: dict[str, Any]):
    from api.domain.question_scorer import DimensionScores

    question = str(payload.get("question") or "")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    profile = payload.get("business_profile") if isinstance(payload.get("business_profile"), dict) else {}
    lower = question.lower()
    token_count = len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", question))
    has_brand = _has_brand_or_competitor(lower, profile)
    has_context = any(marker in lower for marker in (" for ", " with ", " vs ", "pricing", "reviews", "integrate", "demo", "alternatives", "support"))
    bad = any(marker in question for marker in ("{", "}", "[", "]", "<", ">")) or "top 10" in lower or "2026" in lower

    journey = str(metadata.get("journey_stage") or "")
    frame = str(metadata.get("brand_frame") or "")
    intent = str(metadata.get("intent_class") or "")

    d1 = 3.0 if bad else 8.2 if has_context and 6 <= token_count <= 18 else 6.4
    d2 = _commercial_score(journey, intent, lower, frame)
    d3 = 3.5 if bad else 8.4 if has_context or has_brand else 6.2
    d4 = 4.0 if bad else 8.0 if has_brand or frame in {"branded_comparison", "brand_only", "competitor_only"} else 6.8
    d5 = 3.0 if bad else 8.1 if has_brand else 6.5 if has_context else 5.5

    scores = DimensionScores(
        d1_buyer_plausibility=round(d1, 3),
        d2_commercial_proximity=round(d2, 3),
        d3_cognitive_answerability=round(d3, 3),
        d4_diagnostic_power=round(d4, 3),
        d5_statistical_identifiability=round(d5, 3),
    )
    return scores, "Heuristic v1 scored the question against the Phase 12 rubric."


def _commercial_score(journey: str, intent: str, lower: str, frame: str) -> float:
    score = 4.5
    if journey in {"J4", "J6"} or intent == "transactional":
        score += 2.5
    elif journey in {"J2", "J3", "J5"}:
        score += 1.5
    if any(marker in lower for marker in ("pricing", "demo", "contract", "worth it", "migrate", "replace", "shortlist")):
        score += 1.3
    if frame in {"brand_only", "branded_comparison"}:
        score += 0.7
    return round(max(0.0, min(10.0, score)), 3)


def _has_brand_or_competitor(lower: str, profile: dict[str, Any]) -> bool:
    competitors = profile.get("competitors") if isinstance(profile.get("competitors"), list) else []
    names = [str(name).lower() for name in competitors if str(name).strip()]
    artifacts = profile.get("crawl_artifacts") if isinstance(profile.get("crawl_artifacts"), dict) else {}
    auto = artifacts.get("auto_extracted") if isinstance(artifacts.get("auto_extracted"), dict) else {}
    brand = str(auto.get("brand_name") or "").strip().lower()
    if brand:
        names.append(brand)
    names.extend(["vectorcrm", "hubspot", "salesforce", "pipedrive"])
    return any(name and name in lower for name in names)


def _anthropic_text(payload: dict[str, Any]) -> str:
    pieces: list[str] = []
    for block in payload.get("content", []) if isinstance(payload.get("content"), list) else []:
        if isinstance(block, dict) and block.get("type") == "text":
            pieces.append(str(block.get("text") or ""))
    return "\n".join(piece for piece in pieces if piece).strip()


def _extract_runtime_inputs(prompt: str) -> dict[str, Any]:
    start = prompt.find("<runtime_inputs>")
    end = prompt.rfind("</runtime_inputs>")
    if start < 0 or end < 0 or end <= start:
        return {}
    raw = prompt[start + len("<runtime_inputs>"):end].strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
