"""Phase 12 realism-filter scoring rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import json
import re

from api.domain.ports import LLMProvider, ProviderResponse


REALISM_FILTER_PROMPT_KEY = "realism_filter"
REALISM_FILTER_PROMPT_VERSION = "realism_filter-1.0.0"
REALISM_FILTER_SEED = 1206
REALISM_SELF_CONSISTENCY_RUNS = 3
REALISM_PASS_THRESHOLD = 7.0

REALISM_FILTER_SYSTEM_PROMPT = """<system>
You are AISO's realism filter for generated buyer questions.

Judge this exact prompt from pipeline-1.0.md §B.3:
"On a scale of 0–10, how likely is this question to be typed verbatim (or with minor edits) by a real human buyer in {{vertical}} into ChatGPT/Perplexity?"

Return JSON only:
{
  "score": 0-10,
  "rationale": "one short sentence"
}

Use the full 0-10 scale:
- 9-10: natural, specific, and plausible for a real buyer.
- 7-8: plausible with minor awkwardness.
- 4-6: understandable but generic, stiff, or unlikely as written.
- 0-3: keyword stuffing, template residue, missing entity, nonsense, or obviously fake.

Failure modes from §B.3:
- Keyword stuffing: "Top 10 best [category] software 2026 for [industry] companies."
- Unnatural specificity: "Best CRM for B2B SaaS companies with 45–55 employees in California."
- Missing entity: "What's the best for our team?"
- Generic phrasing: "Tell me about CRM software."
- Template residue: brackets/braces still in output.
</system>"""


@dataclass(frozen=True)
class RealismJudgeRun:
    score: float
    rationale: str
    provider_response: ProviderResponse


@dataclass(frozen=True)
class RealismEvaluation:
    question: str
    vertical: str
    llm_judge_score: float
    length_penalty: float
    realism_score: float
    passed: bool
    dropped_for_length: bool
    runs: tuple[RealismJudgeRun, ...]


def render_realism_prompt(*, question: str, vertical: str, metadata: dict[str, Any] | None = None) -> str:
    payload = {
        "vertical": vertical,
        "question": question,
        "metadata": metadata or {},
        "deferred_classifier": {
            "wellformedness_score": "deferred",
            "w2": 0,
        },
        "threshold": REALISM_PASS_THRESHOLD,
    }
    return (
        f"{REALISM_FILTER_SYSTEM_PROMPT}\n\n"
        "<runtime_inputs>\n"
        f"{json.dumps(payload, sort_keys=True, ensure_ascii=False)}\n"
        "</runtime_inputs>"
    )


def evaluate_realism(
    *,
    question: str,
    vertical: str,
    provider: LLMProvider,
    idempotency_key: str,
    metadata: dict[str, Any] | None = None,
    runs: int = REALISM_SELF_CONSISTENCY_RUNS,
) -> RealismEvaluation:
    prompt = render_realism_prompt(question=question, vertical=vertical, metadata=metadata)
    judge_runs: list[RealismJudgeRun] = []
    for index in range(max(1, runs)):
        response = provider.complete(
            prompt=prompt,
            seed=REALISM_FILTER_SEED + index,
            temperature=0.0,
            idempotency_key=f"{idempotency_key}:{index}",
        )
        payload = parse_realism_response(response.text)
        judge_runs.append(
            RealismJudgeRun(
                score=clamp_score(payload.get("score")),
                rationale=str(payload.get("rationale") or "").strip(),
                provider_response=response,
            )
        )

    llm_score = sum(run.score for run in judge_runs) / len(judge_runs)
    penalty = length_penalty(question)
    final_score = round(llm_score * penalty, 3)
    return RealismEvaluation(
        question=question,
        vertical=vertical,
        llm_judge_score=round(llm_score, 3),
        length_penalty=penalty,
        realism_score=final_score,
        passed=final_score >= REALISM_PASS_THRESHOLD,
        dropped_for_length=penalty == 0.0,
        runs=tuple(judge_runs),
    )


def parse_realism_response(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.I)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        score_match = re.search(r"(?:score|rating)?\s*[:=]?\s*(10(?:\.0)?|[0-9](?:\.[0-9]+)?)", clean, flags=re.I)
        return {"score": float(score_match.group(1)) if score_match else 0.0, "rationale": clean[:240]}
    return parsed if isinstance(parsed, dict) else {"score": 0.0, "rationale": ""}


def length_penalty(question: str) -> float:
    count = token_count(question)
    if count < 4 or count > 24:
        return 0.0
    if count < 6 or count > 18:
        return 0.5
    return 1.0


def token_count(question: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", question or ""))


def clamp_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = 0.0
    return max(0.0, min(10.0, score))
