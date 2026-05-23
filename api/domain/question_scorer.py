"""Phase 12 question scoring domain rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import json
import math
import re

from api.domain.ports import BusinessProfileSnapshot, LLMProvider, ProviderResponse


QUESTION_SCORER_PROMPT_KEY = "question_scorer"
QUESTION_SCORER_PROMPT_VERSION = "question_scorer-1.0.0"
QUESTION_SCORER_WEIGHTS_VERSION = "question_scorer_weights-1.0.0"
QUESTION_SCORER_SEED = 1207
SCORER_SELF_CONSISTENCY_RUNS = 3
GWET_AC2_THRESHOLD = 0.75

SCORE_WEIGHTS: dict[str, float] = {
    "D1": 0.30,
    "D2": 0.25,
    "D3": 0.20,
    "D4": 0.15,
    "D5": 0.10,
}

QUESTION_SCORER_SYSTEM_PROMPT = """<system>
You are AISO's question quality scorer. For each question, score 5 dimensions on a 0–10 scale and return a JSON object. Be ruthless. Most questions should score 5–7; only exceptional questions score 8+. Score 0–3 freely on bad questions.

<inputs>
  <business_profile>{{...}}</business_profile>
  <vertical>{{...}}</vertical>
  <objective>{{...}}</objective>
  <question>{{the question to score}}</question>
  <metadata>journey_stage={{...}}, brand_frame={{...}}, intent_class={{...}}, persona={{...}}</metadata>
</inputs>

<dimensions>
  <D1 name="Buyer Plausibility">
    On 0–10, how likely is this question to be typed verbatim (or with minor edits) by a real {{persona}} buyer in {{vertical}} into ChatGPT or Perplexity in the next 30 days, given they are at the {{journey_stage}} stage?
    0 = SEO keyword bait, template residue, or unnatural phrasing.
    10 = indistinguishable from a real anonymous query in the Google/Bing log distribution.
  </D1>
  <D2 name="Commercial Proximity">
    On 0–10, how close is this question to a revenue event for the customer's business?
    10 = buyer answering this question would convert to SQL within 14 days.
    5 = research-mode but commercially relevant.
    0 = high-funnel or off-topic.
  </D2>
  <D3 name="Cognitive Answerability">
    Score 4 sub-dimensions 0–10, return mean:
    (a) Logical form: parseable structure?
    (b) Question focus: clear what's being asked?
    (c) Retrievable context: plausible LLM training data?
    (d) Stance-revealing: will response reveal Presence/Prominence/stance?
  </D3>
  <D4 name="Diagnostic Power">
    If AISO measures the customer is winning on this question, is that informative AND if losing, can they take a concrete action?
    10 = both true.
    5 = one true.
    0 = irrelevant regardless of outcome.
  </D4>
  <D5 name="Statistical Identifiability">
    Probability 5 LLM samples produce consistent Presence/Prominence reading.
    10 = specific entities, likely-deterministic LLM behavior.
    5 = moderately specific.
    0 = open-ended; 5 samples → 5 different answer structures.
  </D5>
</dimensions>

<output_format>
{
  "question_id": "...",
  "scores": {"D1": ?, "D2": ?, "D3": {"a": ?, "b": ?, "c": ?, "d": ?, "mean": ?}, "D4": ?, "D5": ?},
  "weighted_score": ?,
  "rationale": "2-3 sentences"
}
</output_format>
</system>"""


@dataclass(frozen=True)
class QuestionScoreInput:
    question_id: str
    question: str
    journey_stage: str
    brand_frame: str
    intent_class: str
    persona: str | None = None
    locality: str | None = None
    rationale: str | None = None


@dataclass(frozen=True)
class DimensionScores:
    d1_buyer_plausibility: float
    d2_commercial_proximity: float
    d3_cognitive_answerability: float
    d4_diagnostic_power: float
    d5_statistical_identifiability: float


@dataclass(frozen=True)
class ScorerJudgeRun:
    scores: DimensionScores
    weighted_score: float
    rationale: str
    provider_response: ProviderResponse


@dataclass(frozen=True)
class QuestionScoringEvaluation:
    question_id: str
    scores: DimensionScores
    weighted_score: float
    rationale: str
    gwet_ac2: float
    runs: tuple[ScorerJudgeRun, ...]


class ScorerAgreementError(ValueError):
    """Raised when n=3 scorer self-consistency falls below the AC2 gate."""

    def __init__(self, *, question_id: str, gwet_ac2: float, threshold: float):
        super().__init__(f"Scorer self-consistency below threshold: {gwet_ac2:.3f}")
        self.question_id = question_id
        self.gwet_ac2 = gwet_ac2
        self.threshold = threshold


def scorer_prompt_text_for_registry() -> str:
    return (
        f"{QUESTION_SCORER_SYSTEM_PROMPT}\n\n"
        "<scoring_weights>\n"
        f"{json.dumps({'version': QUESTION_SCORER_WEIGHTS_VERSION, 'weights': SCORE_WEIGHTS}, sort_keys=True)}\n"
        "</scoring_weights>"
    )


def render_question_scorer_prompt(
    *,
    snapshot: BusinessProfileSnapshot,
    candidate: QuestionScoreInput,
) -> str:
    payload = {
        "business_profile": {
            "client_id": snapshot.client_id,
            "vertical": snapshot.vertical,
            "objective": snapshot.objective,
            "category": snapshot.category,
            "icp": snapshot.icp,
            "geographic_scope": snapshot.geographic_scope,
            "competitors": snapshot.competitors,
            "personas": snapshot.personas,
        },
        "vertical": snapshot.vertical,
        "objective": snapshot.objective,
        "question_id": candidate.question_id,
        "question": candidate.question,
        "metadata": {
            "journey_stage": candidate.journey_stage,
            "brand_frame": candidate.brand_frame,
            "intent_class": candidate.intent_class,
            "persona": candidate.persona,
            "locality": candidate.locality,
            "rationale": candidate.rationale,
        },
        "weights": SCORE_WEIGHTS,
        "weights_version": QUESTION_SCORER_WEIGHTS_VERSION,
    }
    return (
        f"{QUESTION_SCORER_SYSTEM_PROMPT}\n\n"
        "<runtime_inputs>\n"
        f"{json.dumps(payload, sort_keys=True, ensure_ascii=False)}\n"
        "</runtime_inputs>"
    )


def score_question(
    *,
    snapshot: BusinessProfileSnapshot,
    candidate: QuestionScoreInput,
    provider: LLMProvider,
    idempotency_key: str,
    runs: int = SCORER_SELF_CONSISTENCY_RUNS,
) -> QuestionScoringEvaluation:
    prompt = render_question_scorer_prompt(snapshot=snapshot, candidate=candidate)
    judge_runs: list[ScorerJudgeRun] = []
    for index in range(max(1, runs)):
        response = provider.complete(
            prompt=prompt,
            seed=QUESTION_SCORER_SEED + index,
            temperature=0.0,
            idempotency_key=f"{idempotency_key}:{index}",
        )
        payload = parse_scorer_response(response.text)
        scores = scores_from_payload(payload)
        judge_runs.append(
            ScorerJudgeRun(
                scores=scores,
                weighted_score=weighted_score(scores),
                rationale=str(payload.get("rationale") or "").strip(),
                provider_response=response,
            )
        )

    agreement = gwet_ac2_for_runs([run.scores for run in judge_runs])
    if agreement < GWET_AC2_THRESHOLD:
        raise ScorerAgreementError(
            question_id=candidate.question_id,
            gwet_ac2=agreement,
            threshold=GWET_AC2_THRESHOLD,
        )

    averaged = average_scores([run.scores for run in judge_runs])
    return QuestionScoringEvaluation(
        question_id=candidate.question_id,
        scores=averaged,
        weighted_score=weighted_score(averaged),
        rationale=_combine_rationales(judge_runs),
        gwet_ac2=round(agreement, 3),
        runs=tuple(judge_runs),
    )


def parse_scorer_response(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.I)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", clean, flags=re.S)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def scores_from_payload(payload: dict[str, Any]) -> DimensionScores:
    raw_scores = payload.get("scores") if isinstance(payload.get("scores"), dict) else payload
    d3 = raw_scores.get("D3") if isinstance(raw_scores.get("D3"), dict) else {}
    d3_mean = d3.get("mean") if isinstance(d3, dict) else raw_scores.get("D3")
    if d3_mean is None and isinstance(d3, dict):
        parts = [clamp_score(d3.get(key)) for key in ("a", "b", "c", "d")]
        d3_mean = sum(parts) / len(parts)
    return DimensionScores(
        d1_buyer_plausibility=clamp_score(raw_scores.get("D1")),
        d2_commercial_proximity=clamp_score(raw_scores.get("D2")),
        d3_cognitive_answerability=clamp_score(d3_mean),
        d4_diagnostic_power=clamp_score(raw_scores.get("D4")),
        d5_statistical_identifiability=clamp_score(raw_scores.get("D5")),
    )


def weighted_score(scores: DimensionScores) -> float:
    value = (
        SCORE_WEIGHTS["D1"] * scores.d1_buyer_plausibility
        + SCORE_WEIGHTS["D2"] * scores.d2_commercial_proximity
        + SCORE_WEIGHTS["D3"] * scores.d3_cognitive_answerability
        + SCORE_WEIGHTS["D4"] * scores.d4_diagnostic_power
        + SCORE_WEIGHTS["D5"] * scores.d5_statistical_identifiability
    )
    return round(value, 3)


def average_scores(scores: list[DimensionScores]) -> DimensionScores:
    count = len(scores)
    return DimensionScores(
        d1_buyer_plausibility=round(sum(item.d1_buyer_plausibility for item in scores) / count, 3),
        d2_commercial_proximity=round(sum(item.d2_commercial_proximity for item in scores) / count, 3),
        d3_cognitive_answerability=round(sum(item.d3_cognitive_answerability for item in scores) / count, 3),
        d4_diagnostic_power=round(sum(item.d4_diagnostic_power for item in scores) / count, 3),
        d5_statistical_identifiability=round(sum(item.d5_statistical_identifiability for item in scores) / count, 3),
    )


def gwet_ac2_for_runs(scores: list[DimensionScores]) -> float:
    """Calculate Gwet's AC2 for ordinal 0-10 ratings with quadratic weights.

    Rows are the five scoring dimensions, columns are the n=3 self-consistency
    runs. This follows the raw-ratings AC1/AC2 construction from Gwet's
    irrCAC implementation: weighted observed agreement over per-subject rating
    distributions, and Gwet's chance agreement term based on
    sum(weights) * sum(pi * (1 - pi)) / (q * (q - 1)).
    """
    if len(scores) <= 1:
        return 1.0
    ratings_by_subject = [
        [round(run.d1_buyer_plausibility) for run in scores],
        [round(run.d2_commercial_proximity) for run in scores],
        [round(run.d3_cognitive_answerability) for run in scores],
        [round(run.d4_diagnostic_power) for run in scores],
        [round(run.d5_statistical_identifiability) for run in scores],
    ]
    categories = list(range(11))
    category_count = len(categories)
    weight_matrix = [
        [_ordinal_weight(left, right) for right in categories]
        for left in categories
    ]
    agreement_rows: list[list[int]] = []
    for ratings in ratings_by_subject:
        row = [0 for _ in categories]
        for rating in ratings:
            row[max(0, min(10, rating))] += 1
        agreement_rows.append(row)

    observed_parts: list[float] = []
    for row in agreement_rows:
        raters_for_subject = sum(row)
        if raters_for_subject < 2:
            continue
        weighted_counts = [
            sum(weight_matrix[col][other] * row[other] for other in categories)
            for col in categories
        ]
        numerator = sum(row[col] * (weighted_counts[col] - 1.0) for col in categories)
        observed_parts.append(numerator / (raters_for_subject * (raters_for_subject - 1)))
    observed = sum(observed_parts) / len(observed_parts) if observed_parts else 1.0

    subject_count = len(agreement_rows)
    pi = [
        sum(row[col] / sum(row) for row in agreement_rows if sum(row) > 0) / subject_count
        for col in categories
    ]
    weight_sum = sum(sum(row) for row in weight_matrix)
    chance = weight_sum * sum(value * (1.0 - value) for value in pi) / (category_count * (category_count - 1))
    if math.isclose(1.0, chance):
        return 1.0
    return round(max(0.0, min(1.0, (observed - chance) / (1.0 - chance))), 3)


def clamp_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = 0.0
    return round(max(0.0, min(10.0, score)), 3)


def _ordinal_weight(left: int, right: int) -> float:
    distance = abs(left - right) / 10
    return 1.0 - distance * distance


def _combine_rationales(runs: list[ScorerJudgeRun]) -> str:
    for run in runs:
        if run.rationale:
            return run.rationale
    return "Scored from the Phase 12 five-dimension rubric."
