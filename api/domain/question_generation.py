"""Phase 12 question-generation domain rules."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any
import hashlib
import json
import re

from api.domain.ports import BusinessProfileSnapshot, ProviderResponse


QUESTION_GENERATION_PROMPT_KEY = "question_generation"
QUESTION_GENERATION_PROMPT_VERSION = "question_generation-1.0.0"
QUESTION_GENERATION_SEED = 1205
CANDIDATE_MULTIPLIER = 3
REALISM_FILTER_PENDING_VERSION = "realism_filter-pending-0.0.0"

JOURNEY_STAGES = ("J1", "J2", "J3", "J4", "J5", "J6")
BRAND_FRAMES = ("unbranded_category", "branded_comparison", "brand_only", "competitor_only")
INTENT_CLASSES = ("informational", "navigational", "transactional")

OBJECTIVE_STAGE_WEIGHTS: dict[str, dict[str, int]] = {
    "awareness": {"J1": 30, "J2": 35, "J3": 10, "J4": 10, "J5": 10, "J6": 5},
    "consideration": {"J1": 15, "J2": 30, "J3": 20, "J4": 20, "J5": 10, "J6": 5},
    "preference": {"J1": 5, "J2": 15, "J3": 20, "J4": 35, "J5": 20, "J6": 5},
    "reputation_defense": {"J1": 5, "J2": 10, "J3": 10, "J4": 30, "J5": 35, "J6": 10},
    "competitive_intelligence": {"J1": 10, "J2": 20, "J3": 15, "J4": 35, "J5": 15, "J6": 5},
}

QUESTION_GENERATION_SYSTEM_PROMPT = """<system>
You are AISO's question-generation engine. Produce a candidate pool of natural-sounding questions that real buyers might ask an LLM (ChatGPT, Claude, Perplexity, Gemini) at various stages of evaluating a category or brand. You are NOT writing SEO keywords. You are NOT writing search queries. You are writing questions in the voice of a real human typing into an AI assistant.

<inputs>
  <business_profile>{{auto_extracted_profile + customer_confirmed}}</business_profile>
  <vertical>{{one of the 9 vertical codes}}</vertical>
  <objective>{{Awareness | Consideration | Preference | Reputation_Defense | Competitive_Intelligence}}</objective>
  <competitors>{{list of named competitors}}</competitors>
  <icp>{{firmographic + persona description}}</icp>
  <geographic_scope>{{country | region | city list | radius}}</geographic_scope>
  <target_n>{{e.g., 50}}</target_n>
  <candidate_multiplier>3</candidate_multiplier>
  <vertical_pattern_library>{{10-15 patterns from §B.4}}</vertical_pattern_library>
  <constraints>
    <minimum_per_journey_stage>2</minimum_per_journey_stage>
    <minimum_per_brand_frame>1</minimum_per_brand_frame>
    <token_length_target>8-14</token_length_target>
    <forbidden_phrases>{{vertical-specific, e.g. healthcare: "cure", "guaranteed"}}</forbidden_phrases>
  </constraints>
</inputs>

<instructions>
Generate {{target_n * candidate_multiplier}} candidate questions distributed across the
(Journey Stage × Brand-Relational Frame × Persona × Locality × Intent) lattice.

For each question, output:
  - journey_stage (J1..J6)
  - brand_frame (unbranded_category | branded_comparison | brand_only | competitor_only)
  - intent_class (informational | navigational | transactional)
  - persona (which buyer role)
  - locality (if applicable)
  - rationale (one sentence: why a real buyer would ask this)

Requirements for question realism:
1. Use natural conversational syntax. A real person typing this into ChatGPT or Perplexity must look at the question and think "yes, I could see myself asking that."
2. Avoid keyword-stuffed phrasing. ("Top 10 best CRM software 2026 for small business" is keyword-stuffed; "what's the best CRM for a 50-person sales team?" is natural.)
3. Vary syntactic form: declarative ("best X"), interrogative ("how do I..."), comparative ("X vs Y"), evaluative ("is X worth..."), exploratory ("what are some...").
4. Include explicit context (industry, size, geography, use case) where a real buyer would.
5. Don't make every question include the customer's brand name. Most J1–J3 questions are unbranded.
6. Don't generate near-duplicates.
7. Vary across personas if multiple are present.
8. For competitor-named questions, name actual competitors from the input list. Don't invent.

<chain_of_thought>
Before producing the final list, think step-by-step:
1. What is the customer actually selling? Restate in one sentence.
2. Who are their three best customers' "jobs to be done" (Ulwick framing)?
3. For each journey stage J1..J6, what would a buyer in that stage realistically type?
4. For each brand-relational frame, what's a representative question?
5. Now generate the pool, biased by the objective's distribution.
</chain_of_thought>

<output_format>
Return a JSON array of {{target_n * candidate_multiplier}} objects.
No numbering. No section headers.
</output_format>
</instructions>
</system>"""


@dataclass(frozen=True)
class QuestionGenerationContext:
    client_id: str
    brand_name: str
    vertical: str
    objective: str
    category: str
    icp: dict[str, Any] = field(default_factory=dict)
    geographic_scope: dict[str, Any] = field(default_factory=dict)
    competitors: list[str] = field(default_factory=list)
    personas: dict[str, Any] = field(default_factory=dict)
    target_n: int = 50
    fewshot_examples: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class GeneratedQuestionCandidate:
    text: str
    journey_stage: str
    brand_frame: str
    intent_class: str
    persona: str | None = None
    locality: str | None = None
    rationale: str | None = None


@dataclass(frozen=True)
class QuestionGenerationResult:
    candidates: list[GeneratedQuestionCandidate]
    provider_response: ProviderResponse
    prompt_text: str
    distribution: dict[str, int]


def context_from_snapshot(
    snapshot: BusinessProfileSnapshot,
    *,
    brand_name: str,
    target_n: int = 50,
    fewshot_examples: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> QuestionGenerationContext:
    artifacts = snapshot.crawl_artifacts if isinstance(snapshot.crawl_artifacts, dict) else {}
    auto = artifacts.get("auto_extracted") if isinstance(artifacts.get("auto_extracted"), dict) else {}
    crawled_brand = str(auto.get("brand_name") or "").strip()
    return QuestionGenerationContext(
        client_id=snapshot.client_id,
        brand_name=(crawled_brand or brand_name or "the brand").strip(),
        vertical=snapshot.vertical,
        objective=snapshot.objective,
        category=snapshot.category,
        icp=dict(snapshot.icp),
        geographic_scope=dict(snapshot.geographic_scope),
        competitors=list(snapshot.competitors),
        personas=dict(snapshot.personas),
        target_n=max(1, int(target_n or 50)),
        fewshot_examples=tuple(fewshot_examples or ()),
    )


def context_from_runtime_payload(payload: dict[str, Any]) -> QuestionGenerationContext:
    profile = payload.get("business_profile") if isinstance(payload.get("business_profile"), dict) else {}
    return QuestionGenerationContext(
        client_id=str(profile.get("client_id") or ""),
        brand_name=str(profile.get("brand_name") or "the brand").strip() or "the brand",
        vertical=str(payload.get("vertical") or profile.get("vertical") or ""),
        objective=str(payload.get("objective") or profile.get("objective") or "consideration"),
        category=str(profile.get("category") or "solution").strip() or "solution",
        icp=_dict_value(payload.get("icp")) or _dict_value(profile.get("icp")),
        geographic_scope=_dict_value(payload.get("geographic_scope")) or _dict_value(profile.get("geographic_scope")),
        competitors=_list_value(payload.get("competitors")) or _list_value(profile.get("competitors")),
        personas=_dict_value(profile.get("personas")),
        target_n=max(1, int(payload.get("target_n") or 50)),
        fewshot_examples=tuple(_list_of_dicts(payload.get("vertical_pattern_library"))),
    )


def candidate_pool_size(target_n: int) -> int:
    return max(1, int(target_n or 50)) * CANDIDATE_MULTIPLIER


def stage_distribution(objective: str, total_candidates: int) -> dict[str, int]:
    objective_key = _normalize_objective(objective)
    weights = OBJECTIVE_STAGE_WEIGHTS[objective_key]
    total = max(1, int(total_candidates))
    raw = {stage: total * weights[stage] / 100 for stage in JOURNEY_STAGES}
    counts = {stage: int(raw[stage]) for stage in JOURNEY_STAGES}
    remainder = total - sum(counts.values())
    ranked = sorted(JOURNEY_STAGES, key=lambda stage: (raw[stage] - counts[stage], weights[stage]), reverse=True)
    for stage in ranked[:remainder]:
        counts[stage] += 1

    if total >= len(JOURNEY_STAGES) * 2:
        counts = _enforce_minimum_stage_counts(counts, minimum=2, total=total)
    return counts


def render_question_generation_prompt(context: QuestionGenerationContext) -> str:
    payload = {
        "business_profile": {
            "client_id": context.client_id,
            "brand_name": context.brand_name,
            "vertical": context.vertical,
            "objective": context.objective,
            "category": context.category,
            "icp": context.icp,
            "geographic_scope": context.geographic_scope,
            "competitors": context.competitors,
            "personas": context.personas,
        },
        "vertical": context.vertical,
        "objective": context.objective,
        "competitors": context.competitors,
        "icp": context.icp,
        "geographic_scope": context.geographic_scope,
        "target_n": context.target_n,
        "candidate_multiplier": CANDIDATE_MULTIPLIER,
        "vertical_pattern_library": list(context.fewshot_examples),
        "constraints": {
            "minimum_per_journey_stage": 2,
            "minimum_per_brand_frame": 1,
            "token_length_target": "8-14",
            "forbidden_phrases": _forbidden_phrases(context.vertical, context.icp),
        },
        "objective_stage_distribution": stage_distribution(context.objective, candidate_pool_size(context.target_n)),
    }
    return (
        f"{QUESTION_GENERATION_SYSTEM_PROMPT}\n\n"
        "<runtime_inputs>\n"
        f"{json.dumps(payload, sort_keys=True, ensure_ascii=False)}\n"
        "</runtime_inputs>"
    )


def generate_question_candidates(
    context: QuestionGenerationContext,
    provider,
    *,
    idempotency_key: str,
) -> QuestionGenerationResult:
    prompt_text = render_question_generation_prompt(context)
    response = provider.complete(
        prompt=prompt_text,
        seed=QUESTION_GENERATION_SEED,
        temperature=0.4,
        idempotency_key=idempotency_key,
    )
    candidates = normalize_provider_candidates(response.text, context)
    return QuestionGenerationResult(
        candidates=candidates,
        provider_response=response,
        prompt_text=prompt_text,
        distribution=distribution_for_candidates(candidates),
    )


def normalize_provider_candidates(text: str, context: QuestionGenerationContext) -> list[GeneratedQuestionCandidate]:
    parsed = parse_json_array(text)
    candidates: list[GeneratedQuestionCandidate] = []
    seen: set[str] = set()
    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            continue
        question = _clean_question(item.get("question") or item.get("text"))
        if not question:
            continue
        text_hash = question_text_hash(question)
        if text_hash in seen:
            continue
        seen.add(text_hash)
        stage = str(item.get("journey_stage") or "").strip().upper()
        frame = str(item.get("brand_frame") or "").strip().lower()
        intent = str(item.get("intent_class") or "").strip().lower()
        candidates.append(
            GeneratedQuestionCandidate(
                text=question,
                journey_stage=stage if stage in JOURNEY_STAGES else _stage_for_index(index, context),
                brand_frame=frame if frame in BRAND_FRAMES else _frame_for_stage(_stage_for_index(index, context), index),
                intent_class=intent if intent in INTENT_CLASSES else _intent_for_stage(_stage_for_index(index, context)),
                persona=_optional_str(item.get("persona")) or _persona_values(context)[index % len(_persona_values(context))],
                locality=_optional_str(item.get("locality")) or _locality(context),
                rationale=_optional_str(item.get("rationale")) or "A buyer would ask this while evaluating fit.",
            )
        )
        if len(candidates) >= candidate_pool_size(context.target_n):
            break
    return _fit_candidates_to_distribution(candidates, context)


def _fit_candidates_to_distribution(
    candidates: list[GeneratedQuestionCandidate],
    context: QuestionGenerationContext,
) -> list[GeneratedQuestionCandidate]:
    expected = stage_distribution(context.objective, candidate_pool_size(context.target_n))
    fallback = heuristic_question_candidates(context)
    output: list[GeneratedQuestionCandidate] = []
    seen: set[str] = set()
    for stage in JOURNEY_STAGES:
        stage_count = 0
        pool = [candidate for candidate in candidates if candidate.journey_stage == stage]
        pool.extend(candidate for candidate in fallback if candidate.journey_stage == stage)
        for candidate in pool:
            if stage_count >= expected[stage]:
                break
            text_hash = question_text_hash(candidate.text)
            if text_hash in seen:
                continue
            output.append(candidate)
            seen.add(text_hash)
            stage_count += 1

        index = 0
        while stage_count < expected[stage]:
            frame = _frame_for_stage(stage, index)
            candidate = _fallback_unique_candidate(context, stage, frame, index + len(output))
            text_hash = question_text_hash(candidate.text)
            if text_hash not in seen:
                output.append(candidate)
                seen.add(text_hash)
                stage_count += 1
            index += 1
    return output


def heuristic_question_candidates(context: QuestionGenerationContext) -> list[GeneratedQuestionCandidate]:
    total = candidate_pool_size(context.target_n)
    counts = stage_distribution(context.objective, total)
    output: list[GeneratedQuestionCandidate] = []
    seen: set[str] = set()
    for stage in JOURNEY_STAGES:
        stage_count = counts[stage]
        stage_index = 0
        stage_output_count = 0
        max_attempts = max(stage_count * 50, 100)
        attempts = 0
        while stage_output_count < stage_count:
            frame = _frame_for_stage(stage, stage_index)
            candidate = _heuristic_candidate(context, stage, frame, stage_index)
            text_hash = question_text_hash(candidate.text)
            if text_hash in seen:
                candidate = _add_buying_context(candidate, stage_index)
                text_hash = question_text_hash(candidate.text)
            if text_hash in seen and attempts >= max_attempts:
                candidate = _fallback_unique_candidate(context, stage, frame, stage_index)
                text_hash = question_text_hash(candidate.text)
            if text_hash not in seen:
                output.append(candidate)
                seen.add(text_hash)
                stage_output_count += 1
            stage_index += 1
            attempts += 1
    return output


def parse_json_array(text: str) -> list[Any]:
    clean = str(text or "").strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.I)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", clean, flags=re.S)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    return parsed if isinstance(parsed, list) else []


def distribution_for_candidates(candidates: list[GeneratedQuestionCandidate]) -> dict[str, int]:
    counts = {stage: 0 for stage in JOURNEY_STAGES}
    for candidate in candidates:
        if candidate.journey_stage in counts:
            counts[candidate.journey_stage] += 1
    return counts


def brand_frame_distribution(candidates: list[GeneratedQuestionCandidate]) -> dict[str, int]:
    counts = {frame: 0 for frame in BRAND_FRAMES}
    for candidate in candidates:
        if candidate.brand_frame in counts:
            counts[candidate.brand_frame] += 1
    return counts


def question_text_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _heuristic_candidate(
    context: QuestionGenerationContext,
    stage: str,
    frame: str,
    index: int,
) -> GeneratedQuestionCandidate:
    brand = context.brand_name or "the brand"
    category = context.category or "solution"
    competitors = context.competitors or ["a named competitor"]
    competitor = competitors[index % len(competitors)]
    personas = _persona_values(context)
    persona = personas[index % len(personas)]
    locality = _locality(context)
    firmographics = context.icp.get("firmographics") if isinstance(context.icp.get("firmographics"), dict) else {}
    industry = str(firmographics.get("industry") or context.icp.get("industry") or "growing companies").strip()
    employee_band = str(firmographics.get("employee_band") or context.icp.get("employee_band") or "mid-market").strip()
    segment = f"{employee_band} {industry}".strip()
    use_case = _cycle(_use_cases(context), index)
    tool = _cycle(_tools(context), index)
    criterion = _cycle(_criteria(), index)
    risk = _cycle(_risks(), index)
    outcome = _cycle(_outcomes(context), index)

    if frame == "unbranded_category":
        text = _unbranded_text(stage, category, segment, persona, use_case, tool, criterion, risk, outcome, locality, index)
    elif frame == "branded_comparison":
        text = _comparison_text(stage, brand, competitor, category, segment, persona, use_case, criterion, risk, index)
    elif frame == "brand_only":
        text = _brand_text(stage, brand, category, segment, persona, use_case, tool, criterion, risk, outcome, index)
    else:
        text = _competitor_text(stage, competitor, category, segment, persona, use_case, criterion, risk, index)

    return GeneratedQuestionCandidate(
        text=_clean_question(text),
        journey_stage=stage,
        brand_frame=frame,
        intent_class=_intent_for_stage(stage),
        persona=persona,
        locality=locality,
        rationale=_rationale(stage, frame),
    )


def _unbranded_text(
    stage: str,
    category: str,
    segment: str,
    persona: str,
    use_case: str,
    tool: str,
    criterion: str,
    risk: str,
    outcome: str,
    locality: str,
    index: int,
) -> str:
    templates = {
        "J1": [
            "what's the best {category} for {segment} teams trying to improve {outcome}?",
            "what should a {persona} know before buying {category} for {use_case}?",
            "which {category} options make sense for {segment} companies in {locality}?",
        ],
        "J2": [
            "what {category} should a {persona} shortlist for {use_case}?",
            "which {category} tools work best with {tool} for {segment} teams?",
            "how do {segment} companies compare {category} vendors for {criterion}?",
        ],
        "J3": [
            "what are the strongest {category} alternatives for {segment} teams?",
            "which {category} vendor is easiest for a {persona} to roll out?",
            "what {category} has the best balance of {criterion} and {outcome}?",
        ],
        "J4": [
            "how much should a {segment} team budget for {category} used for {use_case}?",
            "what should we ask on a {category} demo about {criterion}?",
            "what buying criteria matter most for {category} in {segment}?",
        ],
        "J5": [
            "which {category} vendors have the strongest reviews from {segment} teams?",
            "what red flags should a {persona} look for in {category} reviews?",
            "how can we tell whether a {category} vendor will avoid {risk}?",
        ],
        "J6": [
            "how can we expand {category} usage after the first team rollout?",
            "what should a {persona} track after implementing {category}?",
            "how do teams improve {outcome} six months after buying {category}?",
        ],
    }
    return _cycle(templates[stage], index).format(**locals())


def _comparison_text(
    stage: str,
    brand: str,
    competitor: str,
    category: str,
    segment: str,
    persona: str,
    use_case: str,
    criterion: str,
    risk: str,
    index: int,
) -> str:
    templates = {
        "J1": [
            "{brand} vs {competitor}: which one fits {segment} teams better?",
            "why would a {persona} compare {brand} with {competitor} for {use_case}?",
        ],
        "J2": [
            "should we shortlist {brand} or {competitor} for {use_case}?",
            "how do {brand} and {competitor} compare for {criterion}?",
        ],
        "J3": [
            "{brand} vs {competitor}: which is better for a {persona}?",
            "what are the tradeoffs between {brand} and {competitor} for {segment} teams?",
        ],
        "J4": [
            "should we choose {brand} or {competitor} if {criterion} matters most?",
            "what questions should we ask before picking {brand} over {competitor} for {use_case}?",
        ],
        "J5": [
            "does {brand} or {competitor} have better reviews from {segment} customers?",
            "which has fewer complaints about {risk}, {brand} or {competitor}?",
        ],
        "J6": [
            "when would a team switch from {competitor} to {brand} after rollout?",
            "how hard is it to migrate from {competitor} to {brand} for {category}?",
        ],
    }
    return _cycle(templates[stage], index).format(**locals())


def _brand_text(
    stage: str,
    brand: str,
    category: str,
    segment: str,
    persona: str,
    use_case: str,
    tool: str,
    criterion: str,
    risk: str,
    outcome: str,
    index: int,
) -> str:
    templates = {
        "J1": [
            "when should a {segment} team consider {brand}?",
            "is {brand} built for {persona}s working on {use_case}?",
        ],
        "J2": [
            "does {brand} integrate with {tool} for {use_case}?",
            "what problems does {brand} solve for {segment} teams?",
        ],
        "J3": [
            "is {brand} a good {category} choice for a {persona}?",
            "what are the main pros and cons of {brand}?",
        ],
        "J4": [
            "what is {brand} pricing for {segment} companies using it for {use_case} with {tool}?",
            "what should we confirm with {brand} about {criterion} before signing for {outcome}?",
        ],
        "J5": [
            "what do customers say about {brand} support and {risk}?",
            "is {brand} worth it if we care most about {criterion}?",
        ],
        "J6": [
            "how can a {persona} get more value from {brand} after launch?",
            "what {brand} features help improve {outcome} over time?",
        ],
    }
    return _cycle(templates[stage], index).format(**locals())


def _competitor_text(
    stage: str,
    competitor: str,
    category: str,
    segment: str,
    persona: str,
    use_case: str,
    criterion: str,
    risk: str,
    index: int,
) -> str:
    templates = {
        "J1": [
            "is {competitor} a good {category} for {segment} teams?",
            "who is {competitor} best for in {category}?",
        ],
        "J2": [
            "what are the best alternatives to {competitor} for {use_case}?",
            "should a {persona} evaluate {competitor} for {criterion}?",
        ],
        "J3": [
            "what are the downsides of using {competitor} for {use_case}?",
            "which teams outgrow {competitor} when {criterion} matters?",
        ],
        "J4": [
            "what should we negotiate with {competitor} before buying for {use_case}?",
            "how does {competitor} pricing work for {segment} teams that care about {criterion}?",
        ],
        "J5": [
            "what complaints do customers have about {competitor} and {risk}?",
            "is {competitor} reliable enough for a {persona}?",
        ],
        "J6": [
            "when should a team replace {competitor} after implementation?",
            "how do teams reduce {risk} after choosing {competitor}?",
        ],
    }
    return _cycle(templates[stage], index).format(**locals())


def _frame_for_stage(stage: str, index: int) -> str:
    mixes = {
        "J1": ("unbranded_category", "unbranded_category", "unbranded_category", "competitor_only", "brand_only", "branded_comparison"),
        "J2": ("unbranded_category", "unbranded_category", "brand_only", "branded_comparison", "competitor_only"),
        "J3": ("unbranded_category", "branded_comparison", "branded_comparison", "brand_only", "competitor_only"),
        "J4": ("brand_only", "branded_comparison", "unbranded_category", "brand_only", "competitor_only"),
        "J5": ("brand_only", "competitor_only", "branded_comparison", "unbranded_category"),
        "J6": ("brand_only", "unbranded_category", "branded_comparison", "competitor_only"),
    }
    sequence = mixes.get(stage, BRAND_FRAMES)
    return sequence[index % len(sequence)]


def _stage_for_index(index: int, context: QuestionGenerationContext) -> str:
    counts = stage_distribution(context.objective, candidate_pool_size(context.target_n))
    cursor = 0
    for stage in JOURNEY_STAGES:
        cursor += counts[stage]
        if index < cursor:
            return stage
    return JOURNEY_STAGES[-1]


def _intent_for_stage(stage: str) -> str:
    if stage in {"J4", "J6"}:
        return "transactional"
    if stage == "J5":
        return "navigational"
    return "informational"


def _rationale(stage: str, frame: str) -> str:
    stage_reason = {
        "J1": "A buyer is still learning the category and framing the problem.",
        "J2": "A buyer is building an initial shortlist and comparing fit.",
        "J3": "A buyer is narrowing alternatives and testing tradeoffs.",
        "J4": "A buyer is close to purchase and checking commercial details.",
        "J5": "A buyer is validating trust signals and risk before committing.",
        "J6": "A buyer is thinking about post-purchase expansion or replacement.",
    }.get(stage, "A buyer would ask this while evaluating fit.")
    frame_reason = {
        "unbranded_category": "The question does not require prior brand awareness.",
        "branded_comparison": "The question compares the customer's brand with a named alternative.",
        "brand_only": "The question tests the customer's brand directly.",
        "competitor_only": "The question captures demand currently attached to a competitor.",
    }.get(frame, "")
    return f"{stage_reason} {frame_reason}".strip()


def _add_buying_context(candidate: GeneratedQuestionCandidate, index: int) -> GeneratedQuestionCandidate:
    base = candidate.text.rstrip("?")
    detail = _cycle(_buying_contexts(), index)
    criterion = _cycle(_criteria(), index)
    return replace(candidate, text=f"{base} when {detail} and {criterion} matter?")


def _fallback_unique_candidate(
    context: QuestionGenerationContext,
    stage: str,
    frame: str,
    index: int,
) -> GeneratedQuestionCandidate:
    brand = context.brand_name or "the brand"
    category = context.category or "solution"
    persona = _persona_values(context)[index % len(_persona_values(context))]
    detail = _cycle(_buying_contexts(), index)
    criterion = _cycle(_criteria(), index)
    if frame == "unbranded_category":
        text = f"what should a {persona} ask about {category} when {detail} and {criterion} matter?"
    elif frame == "branded_comparison":
        competitor = (context.competitors or ["a named competitor"])[index % len(context.competitors or ["a named competitor"])]
        text = f"should we compare {brand} with {competitor} when {detail} and {criterion} matter?"
    elif frame == "brand_only":
        text = f"is {brand} a good fit when {detail} and {criterion} matter?"
    else:
        competitor = (context.competitors or ["a named competitor"])[index % len(context.competitors or ["a named competitor"])]
        text = f"is {competitor} still a good option when {detail} and {criterion} matter?"
    return GeneratedQuestionCandidate(
        text=_clean_question(text),
        journey_stage=stage,
        brand_frame=frame,
        intent_class=_intent_for_stage(stage),
        persona=persona,
        locality=_locality(context),
        rationale=_rationale(stage, frame),
    )


def _persona_values(context: QuestionGenerationContext) -> list[str]:
    values: list[str] = []
    for value in context.personas.values():
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
        elif isinstance(value, list):
            values.extend(str(item).strip() for item in value if str(item).strip())
    return values or ["buyer"]


def _locality(context: QuestionGenerationContext) -> str:
    geo = context.geographic_scope if isinstance(context.geographic_scope, dict) else {}
    if isinstance(geo.get("description"), str) and geo["description"].strip():
        return geo["description"].strip()
    if isinstance(geo.get("countries"), list) and geo["countries"]:
        return ", ".join(str(item).strip() for item in geo["countries"] if str(item).strip())
    nap = geo.get("nap") if isinstance(geo.get("nap"), dict) else {}
    address = nap.get("address") if isinstance(nap.get("address"), dict) else {}
    city = str(address.get("addressLocality") or "").strip()
    region = str(address.get("addressRegion") or "").strip()
    if city and region:
        return f"{city}, {region}"
    return city or region or "the target market"


def _use_cases(context: QuestionGenerationContext) -> list[str]:
    values = _list_value(context.icp.get("use_cases"))
    values.extend(_list_value(context.icp.get("service_offerings")))
    values.extend(_list_value(context.icp.get("service_taxonomy")))
    return values or [
        "pipeline forecasting",
        "lead routing",
        "sales reporting",
        "deal review",
        "customer onboarding",
        "renewal planning",
        "buyer intent tracking",
        "competitive analysis",
        "executive reporting",
        "workflow automation",
    ]


def _outcomes(context: QuestionGenerationContext) -> list[str]:
    values = _list_value(context.icp.get("desired_outcomes"))
    return values or [
        "forecast accuracy",
        "sales productivity",
        "pipeline visibility",
        "buyer conversion",
        "team adoption",
        "reporting quality",
        "deal velocity",
        "customer retention",
    ]


def _tools(context: QuestionGenerationContext) -> list[str]:
    values = _list_value(context.icp.get("tools"))
    return values or ["Salesforce", "HubSpot", "Slack", "Gong", "Outreach", "Google Sheets", "Segment", "Zendesk"]


def _criteria() -> list[str]:
    return [
        "pricing",
        "implementation effort",
        "data quality",
        "integrations",
        "security review",
        "support quality",
        "reporting depth",
        "time to value",
        "admin controls",
        "workflow flexibility",
    ]


def _risks() -> list[str]:
    return [
        "slow implementation",
        "poor adoption",
        "messy data migration",
        "weak integrations",
        "limited support",
        "unexpected costs",
        "security review delays",
        "reporting gaps",
    ]


def _buying_contexts() -> list[str]:
    return [
        "preparing a vendor shortlist",
        "building the business case",
        "reviewing implementation risk",
        "planning the next budget cycle",
        "comparing sales tools",
        "briefing the executive team",
        "checking integration fit",
        "aligning RevOps and sales",
        "replacing a legacy workflow",
        "standardizing reporting",
        "expanding to a second team",
        "evaluating support quality",
        "cleaning up pipeline data",
        "preparing a security review",
        "mapping adoption risks",
        "deciding between finalists",
        "validating customer proof",
        "building a renewal plan",
        "testing admin workflows",
        "planning data migration",
        "reducing tool sprawl",
        "improving forecast hygiene",
        "supporting a faster rollout",
        "checking total cost",
        "prioritizing time to value",
        "training front-line managers",
        "supporting a new sales motion",
        "improving handoffs",
        "reviewing contract terms",
        "scaling from pilot to rollout",
        "defending the purchase internally",
        "avoiding manual reporting",
        "tracking adoption after launch",
        "comparing customer feedback",
        "evaluating onboarding effort",
        "planning a migration window",
        "reviewing vendor reliability",
        "choosing a long-term platform",
        "improving deal inspection",
        "reducing implementation delays",
    ]


def _forbidden_phrases(vertical: str, icp: dict[str, Any]) -> list[str]:
    phrases = _list_value(icp.get("prohibited_claims"))
    if vertical.startswith("regulated_"):
        phrases.extend(["cure", "guaranteed"])
    return phrases


def _enforce_minimum_stage_counts(counts: dict[str, int], *, minimum: int, total: int) -> dict[str, int]:
    adjusted = dict(counts)
    deficit = 0
    for stage in JOURNEY_STAGES:
        if adjusted[stage] < minimum:
            deficit += minimum - adjusted[stage]
            adjusted[stage] = minimum
    while deficit > 0:
        candidates = [stage for stage in JOURNEY_STAGES if adjusted[stage] > minimum]
        if not candidates:
            break
        stage = max(candidates, key=lambda key: adjusted[key])
        adjusted[stage] -= 1
        deficit -= 1
    difference = total - sum(adjusted.values())
    if difference:
        adjusted[JOURNEY_STAGES[-1]] += difference
    return adjusted


def _normalize_objective(objective: str) -> str:
    value = str(objective or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "awareness_building": "awareness",
        "preference_displacement": "preference",
        "reputation": "reputation_defense",
        "competitive": "competitive_intelligence",
    }
    value = aliases.get(value, value)
    return value if value in OBJECTIVE_STAGE_WEIGHTS else "consideration"


def _clean_question(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    text = text.strip(" -")
    if not text:
        return ""
    text = text[0].lower() + text[1:] if len(text) > 1 else text.lower()
    return text if text.endswith("?") else f"{text}?"


def _cycle(values: list[str] | tuple[str, ...], index: int) -> str:
    return values[index % len(values)]


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
