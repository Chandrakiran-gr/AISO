"""Application service for Phase 12 constrained question selection."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from decimal import Decimal
import math
import re
import time

import pulp
from sqlalchemy.orm import Session

from api.database import QuestionCandidate, QuestionScore
from api.domain.question_selection import (
    DEFAULT_SELECTION_TARGET_N,
    SelectionCandidate,
    SelectionConstraints,
    SelectionResult,
    distribution_for,
    lambda_for_mode,
    objective_stage_targets,
    token_cosine_similarity,
)


class QuestionSelectionError(ValueError):
    """Raised when the candidate pool cannot satisfy selection constraints."""


def apply_question_selection(
    db: Session,
    *,
    client_id: str,
    target_n: int = DEFAULT_SELECTION_TARGET_N,
    critical_question_ids: list[str] | tuple[str, ...] | None = None,
    journey_min: dict[str, int] | None = None,
    frame_min: dict[str, int] | None = None,
    intent_band: dict[str, tuple[float, float]] | None = None,
    personas: list[str] | tuple[str, ...] | None = None,
    scan_run_id: str | None = None,
    generator_version: str | None = None,
    objective: str | None = None,
    selection_mode: str | None = None,
    lambda_mmr: float | None = None,
) -> SelectionResult:
    constraints = SelectionConstraints(
        target_n=target_n,
        critical_question_ids=tuple(critical_question_ids or ()),
        objective=objective,
        objective_stage_targets=objective_stage_targets(objective, target_n),
        personas=tuple(personas or ()),
        lambda_mmr=lambda_mmr if lambda_mmr is not None else lambda_for_mode(selection_mode),
    )
    if journey_min is not None:
        constraints = replace(constraints, journey_min={str(key): int(value) for key, value in journey_min.items()})
    if frame_min is not None:
        constraints = replace(constraints, frame_min={str(key): int(value) for key, value in frame_min.items()})
    if intent_band is not None:
        constraints = replace(
            constraints,
            intent_band={
                str(key): (float(value[0]), float(value[1]))
                for key, value in intent_band.items()
            },
        )

    candidates = scored_selection_candidates(
        db,
        client_id=client_id,
        scan_run_id=scan_run_id,
        generator_version=generator_version,
    )
    if not candidates:
        raise QuestionSelectionError("No scored question candidates available for selection")
    result = select_questions_mip(candidates, constraints)
    persist_selected_questions(
        db,
        client_id=client_id,
        selected_ids=result.selected_ids,
        scan_run_id=scan_run_id,
        generator_version=generator_version,
    )
    return result


def select_questions_mip(
    candidates: list[SelectionCandidate],
    constraints: SelectionConstraints,
) -> SelectionResult:
    validate_constraints(candidates, constraints)
    started = time.perf_counter()

    problem = pulp.LpProblem("question_selection", pulp.LpMaximize)
    decision = {
        candidate.id: pulp.LpVariable(f"x_{_safe_var_name(candidate.id)}", cat="Binary")
        for candidate in candidates
    }

    high_sim_pairs = [
        (left, right)
        for index, left in enumerate(candidates)
        for right in candidates[index + 1:]
        if token_cosine_similarity(left.text, right.text) > constraints.similarity_threshold
    ]
    sim_vars = {
        (left.id, right.id): pulp.LpVariable(
            f"sim_{_safe_var_name(left.id)}_{_safe_var_name(right.id)}",
            cat="Binary",
        )
        for left, right in high_sim_pairs
    }
    for (left_id, right_id), variable in sim_vars.items():
        problem += variable >= decision[left_id] + decision[right_id] - 1

    problem += pulp.lpSum(decision.values()) == constraints.target_n

    for critical_id in constraints.critical_question_ids:
        problem += decision[critical_id] == 1
    for journey_stage, min_count in constraints.journey_min.items():
        problem += (
            pulp.lpSum(
                decision[candidate.id]
                for candidate in candidates
                if candidate.journey_stage == journey_stage
            )
            >= min_count
        )
    for frame, min_count in constraints.frame_min.items():
        problem += (
            pulp.lpSum(
                decision[candidate.id]
                for candidate in candidates
                if candidate.brand_frame == frame
            )
            >= min_count
        )
    for intent, (lo, hi) in constraints.intent_band.items():
        selected_for_intent = pulp.lpSum(
            decision[candidate.id]
            for candidate in candidates
            if candidate.intent_class == intent
        )
        problem += selected_for_intent >= lo * constraints.target_n
        problem += selected_for_intent <= hi * constraints.target_n
    for persona in constraints.personas:
        problem += (
            pulp.lpSum(
                decision[candidate.id]
                for candidate in candidates
                if candidate.persona == persona
            )
            >= 1
        )

    stage_deviation_vars = []
    for stage, target_count in constraints.objective_stage_targets.items():
        selected_for_stage = pulp.lpSum(
            decision[candidate.id]
            for candidate in candidates
            if candidate.journey_stage == stage
        )
        over = pulp.LpVariable(f"stage_over_{_safe_var_name(stage)}", lowBound=0)
        under = pulp.LpVariable(f"stage_under_{_safe_var_name(stage)}", lowBound=0)
        problem += selected_for_stage - target_count == over - under
        stage_deviation_vars.extend([over, under])

    problem += (
        pulp.lpSum(candidate.score * decision[candidate.id] for candidate in candidates)
        - constraints.lambda_mmr * pulp.lpSum(sim_vars.values())
        - constraints.stage_deviation_penalty * pulp.lpSum(stage_deviation_vars)
    )

    solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=2)
    problem.solve(solver)
    solver_seconds = time.perf_counter() - started
    status = pulp.LpStatus.get(problem.status, str(problem.status))
    if status != "Optimal":
        raise QuestionSelectionError(f"Question selection solver failed with status {status}")

    selected_ids = [
        candidate.id
        for candidate in candidates
        if pulp.value(decision[candidate.id]) is not None and pulp.value(decision[candidate.id]) > 0.5
    ]
    if len(selected_ids) != constraints.target_n:
        raise QuestionSelectionError("Question selection did not hit target_n exactly")

    objective = pulp.value(problem.objective)
    return SelectionResult(
        selected_ids=selected_ids,
        target_n=constraints.target_n,
        objective=constraints.objective,
        objective_stage_targets=constraints.objective_stage_targets,
        objective_value=float(objective or 0.0),
        solver_status=status,
        solver_seconds=round(solver_seconds, 4),
        mmr_lambda=constraints.lambda_mmr,
        high_similarity_pair_count=len(high_sim_pairs),
        journey_distribution=distribution_for(candidates, selected_ids, "journey_stage"),
        frame_distribution=distribution_for(candidates, selected_ids, "brand_frame"),
        intent_distribution=distribution_for(candidates, selected_ids, "intent_class"),
        persona_distribution=distribution_for(candidates, selected_ids, "persona"),
    )


def scored_selection_candidates(
    db: Session,
    *,
    client_id: str,
    scan_run_id: str | None = None,
    generator_version: str | None = None,
) -> list[SelectionCandidate]:
    query = db.query(QuestionCandidate).filter(QuestionCandidate.client_id == client_id)
    if scan_run_id:
        query = query.filter(QuestionCandidate.scan_run_id == scan_run_id)
    if generator_version:
        query = query.filter(QuestionCandidate.generator_version == generator_version)
    candidates = query.order_by(QuestionCandidate.created_at.asc(), QuestionCandidate.id.asc()).all()
    candidate_ids = [candidate.id for candidate in candidates]
    if not candidate_ids:
        return []

    scores_by_question: dict[str, QuestionScore] = {}
    scores = (
        db.query(QuestionScore)
        .filter(QuestionScore.question_id.in_(candidate_ids))
        .order_by(QuestionScore.question_id.asc(), QuestionScore.scored_at.desc())
        .all()
    )
    for score in scores:
        if score.question_id not in scores_by_question:
            scores_by_question[score.question_id] = score

    output: list[SelectionCandidate] = []
    for candidate in candidates:
        score = scores_by_question.get(candidate.id)
        if not score:
            continue
        output.append(
            SelectionCandidate(
                id=candidate.id,
                text=candidate.text,
                score=float(score.weighted_score or Decimal("0")),
                journey_stage=candidate.journey_stage,
                brand_frame=candidate.brand_frame,
                intent_class=candidate.intent_class,
                persona=candidate.persona,
            )
        )
    return output


def persist_selected_questions(
    db: Session,
    *,
    client_id: str,
    selected_ids: list[str],
    scan_run_id: str | None = None,
    generator_version: str | None = None,
) -> None:
    query = db.query(QuestionCandidate).filter(QuestionCandidate.client_id == client_id)
    if scan_run_id:
        query = query.filter(QuestionCandidate.scan_run_id == scan_run_id)
    if generator_version:
        query = query.filter(QuestionCandidate.generator_version == generator_version)
    selected = set(selected_ids)
    for candidate in query.all():
        candidate.selected = candidate.id in selected
    db.flush()


def validate_constraints(candidates: list[SelectionCandidate], constraints: SelectionConstraints) -> None:
    violations = constraint_violations(candidates, constraints)
    if violations:
        raise QuestionSelectionError("Unsatisfiable selection constraints: " + "; ".join(violations))


def constraint_violations(candidates: list[SelectionCandidate], constraints: SelectionConstraints) -> list[str]:
    violations: list[str] = []
    if constraints.target_n < 1:
        violations.append("target_n must be at least 1")
        return violations
    if constraints.target_n > len(candidates):
        violations.append(f"target_n={constraints.target_n} exceeds scored_candidate_count={len(candidates)}")
    candidate_ids = {candidate.id for candidate in candidates}
    missing_critical = [item for item in constraints.critical_question_ids if item not in candidate_ids]
    if missing_critical:
        violations.append(f"critical_question_ids missing from scored pool: {missing_critical}")
    if len(constraints.critical_question_ids) > constraints.target_n:
        violations.append("critical_question_ids exceeds target_n")

    stage_counts = Counter(candidate.journey_stage for candidate in candidates)
    for stage, minimum in constraints.journey_min.items():
        available = stage_counts.get(stage, 0)
        if available < minimum:
            violations.append(f"journey_min[{stage}] requires {minimum}, available {available}")

    frame_counts = Counter(candidate.brand_frame for candidate in candidates)
    for frame, minimum in constraints.frame_min.items():
        available = frame_counts.get(frame, 0)
        if available < minimum:
            violations.append(f"frame_min[{frame}] requires {minimum}, available {available}")

    critical_ids = set(constraints.critical_question_ids)
    critical_by_intent = Counter(candidate.intent_class for candidate in candidates if candidate.id in critical_ids)
    intent_counts = Counter(candidate.intent_class for candidate in candidates)
    min_total = 0
    max_total = 0
    for name, (lo, hi) in constraints.intent_band.items():
        if lo < 0 or hi > 1 or lo > hi:
            violations.append(f"intent_band[{name}] invalid range {lo}-{hi}")
            continue
        minimum = math.ceil(lo * constraints.target_n)
        maximum = math.floor(hi * constraints.target_n)
        min_total += minimum
        max_total += maximum
        available = intent_counts.get(name, 0)
        if available < minimum:
            violations.append(f"intent_band[{name}] minimum requires {minimum}, available {available}")
        critical_count = critical_by_intent.get(name, 0)
        if critical_count > maximum:
            violations.append(f"intent_band[{name}] maximum allows {maximum}, critical questions force {critical_count}")
    if min_total > constraints.target_n:
        violations.append(f"intent_band minimums sum to {min_total}, above target_n={constraints.target_n}")
    if max_total and max_total < constraints.target_n:
        violations.append(f"intent_band maximums sum to {max_total}, below target_n={constraints.target_n}")

    persona_counts = Counter(candidate.persona for candidate in candidates)
    for persona in constraints.personas:
        if persona_counts.get(persona, 0) < 1:
            violations.append(f"personas[{persona}] requires 1, available 0")
    return violations


def _safe_var_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value)
