"""Framework-neutral AVS-1.0 computation rules."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
import re
from statistics import NormalDist
from typing import Iterable


AVS_FORMULA_VERSION = "AVS-1.0.0"
BOOTSTRAP_PRODUCTION_ITERATIONS = 10_000
BOOTSTRAP_SMOKE_ITERATIONS = 2_000
ZERO_EPSILON = 1e-9

STANCE_VALUE_MAP = {
    "R+": 1.00,
    "C+": 0.75,
    "N": 0.50,
    "C-": 0.25,
    "F-": 0.10,
    "R-": 0.00,
}


@dataclass(frozen=True)
class AVSSample:
    question_id: str
    provider: str
    sample_index: int
    text: str
    stance_label: str
    stance_confidence: float
    question_weight: float = 1.0


@dataclass(frozen=True)
class AVSSubindices:
    presence: float
    prominence: float
    positivity: float


@dataclass(frozen=True)
class AVSResult:
    avs_value: float
    presence: float
    prominence: float
    positivity: float
    ci_lower_95: float
    ci_upper_95: float
    ci_method: str
    bootstrap_iterations: int
    zero_mentions: bool = False


def compute_avs(
    samples_by_pair: dict[tuple[str, str], list[AVSSample]],
    *,
    target_aliases: Iterable[str],
    bootstrap_iterations: int = BOOTSTRAP_PRODUCTION_ITERATIONS,
    bootstrap_seed: int = 42,
) -> AVSResult:
    indices = compute_subindices(samples_by_pair, target_aliases=target_aliases)
    point = avs_from_subindices(indices)
    if point == 0:
        return AVSResult(
            avs_value=0.0,
            presence=indices.presence,
            prominence=indices.prominence,
            positivity=indices.positivity,
            ci_lower_95=0.0,
            ci_upper_95=0.0,
            ci_method="percentile-fallback",
            bootstrap_iterations=bootstrap_iterations,
            zero_mentions=indices.presence <= ZERO_EPSILON,
        )
    _, interval, method = nested_cluster_bootstrap(
        samples_by_pair,
        STANCE_VALUE_MAP,
        B=bootstrap_iterations,
        seed=bootstrap_seed,
        target_aliases=target_aliases,
    )
    return AVSResult(
        avs_value=point,
        presence=indices.presence,
        prominence=indices.prominence,
        positivity=indices.positivity,
        ci_lower_95=interval[0],
        ci_upper_95=interval[1],
        ci_method=method,
        bootstrap_iterations=bootstrap_iterations,
        zero_mentions=False,
    )


def compute_subindices(
    samples_by_pair: dict[tuple[str, str], list[AVSSample]],
    *,
    target_aliases: Iterable[str],
) -> AVSSubindices:
    aliases = normalized_aliases(target_aliases)
    weighted_presence_num = 0.0
    weighted_prominence_num = 0.0
    weighted_cell_den = 0.0
    positivity_num = 0.0
    positivity_den = 0.0

    for (_question_id, _provider), samples in sorted(samples_by_pair.items()):
        if not samples:
            continue
        question_weight = max(float(samples[0].question_weight), 0.0)
        mentions: list[tuple[AVSSample, float]] = []
        for sample in samples:
            position = first_mention_position(sample.text, aliases)
            if position is None:
                continue
            pos, total = position
            mention_weight = math.exp(-pos / total)
            mentions.append((sample, mention_weight))

        mention_rate = len(mentions) / len(samples)
        weighted_presence_num += question_weight * mention_rate
        if mentions:
            cell_prominence = sum(weight for _sample, weight in mentions) / len(mentions)
        else:
            cell_prominence = 0.0
        weighted_prominence_num += question_weight * cell_prominence
        weighted_cell_den += question_weight

        for sample, _mention_weight in mentions:
            stance_value = STANCE_VALUE_MAP.get(sample.stance_label, STANCE_VALUE_MAP["N"])
            weighted = question_weight
            positivity_num += weighted * stance_value
            positivity_den += weighted

    if weighted_cell_den <= 0:
        return AVSSubindices(presence=0.0, prominence=0.0, positivity=0.0)
    positivity = positivity_num / positivity_den if positivity_den > 0 else 0.0
    return AVSSubindices(
        presence=_clamp01(weighted_presence_num / weighted_cell_den),
        prominence=_clamp01(weighted_prominence_num / weighted_cell_den),
        positivity=_clamp01(positivity),
    )


def avs_from_subindices(indices: AVSSubindices) -> float:
    if indices.presence <= 0 or indices.prominence <= 0 or indices.positivity <= 0:
        return 0.0
    return 100.0 * ((indices.presence * indices.prominence * indices.positivity) ** (1.0 / 3.0))


def wilson_interval(mentions: int, total: int, *, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    p_hat = mentions / total
    denominator = 1 + (z * z / total)
    center = (p_hat + (z * z / (2 * total))) / denominator
    margin = (
        z
        * math.sqrt((p_hat * (1 - p_hat) / total) + (z * z / (4 * total * total)))
        / denominator
    )
    return (_clamp01(center - margin), _clamp01(center + margin))


def nested_cluster_bootstrap(
    samples_by_pair: dict[tuple, list[AVSSample]],
    stance_value_map: dict[str, float],
    B: int = BOOTSTRAP_PRODUCTION_ITERATIONS,
    alpha: float = 0.05,
    seed: int = 42,
    target_aliases: Iterable[str] = (),
) -> tuple[float, tuple[float, float], str]:
    """Returns (point_estimate, (ci_lo, ci_hi), method_used)."""

    del stance_value_map  # Stance mapping is fixed by AVS-1.0 in this module.
    aliases = list(target_aliases)
    clusters = [(pair, samples) for pair, samples in sorted(samples_by_pair.items()) if samples]
    if not clusters:
        return (0.0, (0.0, 0.0), "percentile-fallback")

    point_indices = compute_subindices(dict(clusters), target_aliases=aliases)
    point = avs_from_subindices(point_indices)
    rng = random.Random(seed)
    boot = sorted(
        _bootstrap_once(clusters, rng=rng, target_aliases=aliases)
        for _ in range(max(int(B), 1))
    )

    if _requires_percentile_fallback(point_indices, clusters):
        return (point, _percentile_interval(boot, alpha), "percentile-fallback")

    try:
        interval = _bca_interval(
            point=point,
            boot=boot,
            clusters=clusters,
            alpha=alpha,
            target_aliases=aliases,
        )
    except ArithmeticError:
        return (point, _percentile_interval(boot, alpha), "percentile-fallback")
    return (point, interval, "BCa")


def normalized_aliases(values: Iterable[str]) -> list[str]:
    aliases: list[str] = []
    for value in values:
        clean = _normalize_text(value)
        if clean and clean not in aliases:
            aliases.append(clean)
    return aliases


def first_mention_position(text: str, aliases: list[str]) -> tuple[int, int] | None:
    if not aliases:
        return None
    segments = _rank_segments(text)
    for index, segment in enumerate(segments, start=1):
        normalized = _normalize_text(segment)
        if any(_contains_alias(normalized, alias) for alias in aliases):
            return (index, max(len(segments), 1))
    return None


def _bootstrap_once(
    clusters: list[tuple[tuple, list[AVSSample]]],
    *,
    rng: random.Random,
    target_aliases: Iterable[str],
) -> float:
    resampled: dict[tuple[str, int], list[AVSSample]] = {}
    for draw_index in range(len(clusters)):
        pair, samples = rng.choice(clusters)
        selected = [rng.choice(samples) for _ in range(len(samples))]
        resampled[(pair, draw_index)] = selected
    return avs_from_subindices(compute_subindices(resampled, target_aliases=target_aliases))


def _bca_interval(
    *,
    point: float,
    boot: list[float],
    clusters: list[tuple[tuple, list[AVSSample]]],
    alpha: float,
    target_aliases: Iterable[str],
) -> tuple[float, float]:
    n = len(boot)
    below = sum(1 for value in boot if value < point)
    prop = min(max(below / n, 1 / (2 * n)), 1 - (1 / (2 * n)))
    normal = NormalDist()
    z0 = normal.inv_cdf(prop)

    jackknife = []
    for index in range(len(clusters)):
        remaining = dict(clusters[:index] + clusters[index + 1 :])
        if not remaining:
            continue
        jackknife.append(avs_from_subindices(compute_subindices(remaining, target_aliases=target_aliases)))
    if len(jackknife) < 2:
        raise ArithmeticError("BCa requires at least two jackknife clusters")

    jack_mean = sum(jackknife) / len(jackknife)
    diffs = [jack_mean - value for value in jackknife]
    numerator = sum(value**3 for value in diffs)
    denominator_base = sum(value**2 for value in diffs)
    denominator = 6 * (denominator_base ** 1.5)
    if denominator_base < 1e-12 or denominator == 0:
        raise ArithmeticError("BCa acceleration denominator degenerate")
    acceleration = numerator / denominator

    z_low = normal.inv_cdf(alpha / 2)
    z_high = normal.inv_cdf(1 - alpha / 2)
    a_low = _adjusted_alpha(normal, z0, z_low, acceleration)
    a_high = _adjusted_alpha(normal, z0, z_high, acceleration)
    if not (0 < a_low < 1 and 0 < a_high < 1 and a_low < a_high):
        raise ArithmeticError("BCa endpoints degenerate")
    return (_quantile(boot, a_low), _quantile(boot, a_high))


def _adjusted_alpha(normal: NormalDist, z0: float, z_alpha: float, acceleration: float) -> float:
    denominator = 1 - acceleration * (z0 + z_alpha)
    if abs(denominator) < 1e-12:
        raise ArithmeticError("BCa denominator degenerate")
    return normal.cdf(z0 + ((z0 + z_alpha) / denominator))


def _percentile_interval(values: list[float], alpha: float) -> tuple[float, float]:
    return (_quantile(values, alpha / 2), _quantile(values, 1 - alpha / 2))


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    p = min(max(probability, 0.0), 1.0)
    if len(values) == 1:
        return values[0]
    position = p * (len(values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    fraction = position - lower
    return values[lower] + ((values[upper] - values[lower]) * fraction)


def _requires_percentile_fallback(
    indices: AVSSubindices,
    clusters: list[tuple[tuple, list[AVSSample]]],
) -> bool:
    del clusters
    return any(
        value <= ZERO_EPSILON or value >= 1 - ZERO_EPSILON
        for value in (indices.presence, indices.prominence, indices.positivity)
    )


def _rank_segments(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    list_items = [line for line in lines if re.match(r"^(\d+[.)]|[-*•])\s+", line)]
    if len(list_items) >= 2:
        return list_items
    sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", text) if segment.strip()]
    return sentences or ([text] if text else [""])


def _normalize_text(value: str) -> str:
    lowered = value.lower()
    return re.sub(r"[^a-z0-9]+", " ", lowered).strip()


def _contains_alias(normalized_text: str, normalized_alias: str) -> bool:
    if not normalized_text or not normalized_alias:
        return False
    return re.search(rf"(^|\s){re.escape(normalized_alias)}($|\s)", normalized_text) is not None


def _clamp01(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)
