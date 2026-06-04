"""Framework-neutral classifier rules for classifier-1.0."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse


CLASSIFIER_VERSION = "classifier-1.0.0"
STANCE_PROMPT_KEY = "classifier_stance"
STANCE_PROMPT_VERSION = "classifier-1.0.0-stance"
SOURCE_PROMPT_KEY = "classifier_source"
SOURCE_PROMPT_VERSION = "classifier-1.0.0-source"
STANCE_MODEL_NAME = "claude-sonnet-4"
SOURCE_MODEL_NAME = "claude-sonnet-4"
STANCE_SELF_CONSISTENCY_N = 3
STANCE_TEMPERATURE = 0.3
SOURCE_TEMPERATURE = 0.3
PROMPT_TOP_P = 1.0

STANCE_LABELS = ("R-", "F-", "C-", "N", "C+", "R+")
SOURCE_CLASSES = ("OWNED", "EARNED-HIGH", "EARNED-MID", "UGC", "COMPETITOR", "UNKNOWN")
STANCE_CONFIDENCE_BY_AGREEMENT = {3: 0.95, 2: 0.75, 1: 0.40}

STANCE_SYSTEM_PROMPT = """You are AISO's classifier-1.0 stance judge.

Task: classify the stance of a provider answer toward the TARGET business, not generic sentiment.

Return exactly one JSON object with keys:
{"label":"R+|C+|N|C-|F-|R-","rationale":"short reason"}

Rubric:
R+ means explicit strong recommendation, best choice, or clear endorsement of TARGET.
C+ means TARGET is included as a viable option, listed in a top-N, or mildly recommended.
N means no clear stance toward TARGET, mixed factual mention, or TARGET is absent.
C- means mild caution, weak disadvantage, or target is presented as less suitable.
F- means clear negative factual critique, operational concern, or meaningful warning.
R- means explicit strong recommendation against TARGET.

Critical distinctions:
- Stance is toward TARGET only.
- Sarcasm reverses surface polarity.
- Hedging weakens stance.
- Listing in a top-N without commentary is C+, not R+.
- If TARGET is absent from the answer context, use N.

Few-shot anchors:
1. "Choose Acme; it is the strongest option." => R+
2. "Acme is a reliable choice for most buyers." => R+
3. "Acme appears among the better options." => C+
4. "Acme is one of several local providers." => C+
5. "Acme is mentioned, but details are limited." => N
6. "The answer discusses the category without Acme." => N
7. "Acme may work, though reviews are inconsistent." => C-
8. "Acme is not ideal for urgent needs." => C-
9. "Acme has repeated service complaints." => F-
10. "Avoid Acme for this use case." => R-
11. "Sure, Acme is 'amazing' if you like missed appointments." => F-
12. "Acme is listed in a top five with no extra commentary." => C+
"""

SOURCE_SYSTEM_PROMPT = """You are AISO's classifier-1.0 source judge.

Task: classify one citation domain into exactly one AISO source class.

Return exactly one JSON object with keys:
{"class":"OWNED|EARNED-HIGH|EARNED-MID|UGC|COMPETITOR|UNKNOWN","rationale":"short reason"}

Classes:
OWNED means client-controlled property.
EARNED-HIGH means government, education, Wikipedia, tier-1 press, or peer-reviewed authority.
EARNED-MID means trade press, mid-tier business press, local/editorial press, or review aggregators.
UGC means Reddit, Quora, forums, Q&A, blog platforms, social, or video platforms.
COMPETITOR means client-declared competitor-controlled property.
UNKNOWN means indeterminate after review.
"""

UGC_DOMAINS = {
    "reddit.com",
    "quora.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "tiktok.com",
    "x.com",
    "twitter.com",
    "linkedin.com",
    "medium.com",
    "blogspot.com",
    "wordpress.com",
    "github.io",
}

EARNED_HIGH_DOMAINS = {
    "wikipedia.org",
    "nih.gov",
    "cdc.gov",
    "ftc.gov",
    "consumerfinance.gov",
    "harvard.edu",
    "stanford.edu",
    "mit.edu",
    "nytimes.com",
    "wsj.com",
    "reuters.com",
    "apnews.com",
    "bbc.com",
}

EARNED_MID_DOMAINS = {
    "yelp.com",
    "tripadvisor.com",
    "g2.com",
    "capterra.com",
    "trustpilot.com",
    "bbb.org",
    "forbes.com",
    "businessinsider.com",
    "techcrunch.com",
}


@dataclass(frozen=True)
class StanceConsensus:
    label: str
    agreement_count: int
    confidence: float
    individual_judgments: list[str]


@dataclass(frozen=True)
class SourceDomainJudgment:
    domain: str
    source_class: str
    source: str
    confidence: float
    prompt_hash: bytes | None = None
    raw_judgment: str | None = None


@dataclass(frozen=True)
class SourceConsensus:
    source_class: str
    confidence: float
    judgments: list[SourceDomainJudgment]


def prompt_hash(prompt_text: str) -> bytes:
    return hashlib.sha256(prompt_text.encode("utf-8")).digest()


def stance_prompt(*, target_name: str, question_text: str, answer_text: str) -> str:
    context = mention_window(answer_text, target_names=[target_name])
    return (
        f"TARGET: {target_name}\n"
        f"QUESTION: {question_text}\n"
        "ANSWER CONTEXT:\n"
        f"{context}\n"
        "Classify stance toward TARGET. Return JSON only."
    )


def source_prompt(*, domain: str, url: str, answer_excerpt: str) -> str:
    return (
        f"DOMAIN: {domain}\n"
        f"URL: {url}\n"
        "ANSWER EXCERPT:\n"
        f"{answer_excerpt[:2000]}\n"
        "Classify the citation domain. Return JSON only."
    )


def mention_window(text: str, *, target_names: list[str], radius_tokens: int = 200) -> str:
    tokens = text.split()
    if not tokens:
        return ""
    lowered_names = [name.lower() for name in target_names if name.strip()]
    if not lowered_names:
        return " ".join(tokens[: radius_tokens * 2])

    lowered_tokens = [token.lower() for token in tokens]
    match_index = None
    for index, token in enumerate(lowered_tokens):
        joined = " ".join(lowered_tokens[index : index + 5])
        if any(name in joined or name in token for name in lowered_names):
            match_index = index
            break
    if match_index is None:
        return " ".join(tokens[: radius_tokens * 2])
    start = max(0, match_index - radius_tokens)
    end = min(len(tokens), match_index + radius_tokens + 1)
    return " ".join(tokens[start:end])


def consensus_stance(raw_judgments: list[str]) -> StanceConsensus:
    labels = [parse_stance_label(raw) for raw in raw_judgments]
    counts = Counter(labels)
    agreement_count = max(counts.values()) if counts else 1
    top_labels = [label for label, count in counts.items() if count == agreement_count]
    if len(top_labels) == 1:
        label = top_labels[0]
    else:
        label = _ordinal_median(labels)
    return StanceConsensus(
        label=label,
        agreement_count=agreement_count,
        confidence=STANCE_CONFIDENCE_BY_AGREEMENT.get(agreement_count, 0.40),
        individual_judgments=raw_judgments,
    )


def consensus_source(judgments: list[SourceDomainJudgment]) -> SourceConsensus:
    if not judgments:
        return SourceConsensus(
            source_class="UNKNOWN",
            confidence=0.40,
            judgments=[],
        )
    class_counts = Counter(judgment.source_class for judgment in judgments)
    max_count = max(class_counts.values())
    candidates = [source_class for source_class, count in class_counts.items() if count == max_count]
    source_class = sorted(candidates, key=_source_rank)[0]
    confidences = [judgment.confidence for judgment in judgments if judgment.source_class == source_class]
    confidence = sum(confidences) / len(confidences) if confidences else 0.40
    return SourceConsensus(source_class=source_class, confidence=confidence, judgments=judgments)


def parse_stance_label(raw: str) -> str:
    payload = _json_object(raw)
    label = str(payload.get("label") or payload.get("stance") or "").strip().upper()
    label = label.replace(" ", "")
    if label in STANCE_LABELS:
        return label
    for candidate in sorted(STANCE_LABELS, key=len, reverse=True):
        if re.search(rf"(?<![A-Z0-9+-]){re.escape(candidate)}(?![A-Z0-9+-])", raw.upper()):
            return candidate
    return "N"


def parse_source_class(raw: str) -> str:
    payload = _json_object(raw)
    value = str(payload.get("class") or payload.get("source_class") or payload.get("label") or "").strip().upper()
    value = value.replace("_", "-")
    if value in SOURCE_CLASSES:
        return value
    for candidate in SOURCE_CLASSES:
        if candidate in raw.upper():
            return candidate
    return "UNKNOWN"


def citation_urls(text: str, raw_metadata: dict[str, Any] | None = None) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for value in _metadata_urls(raw_metadata or {}):
        if value not in seen:
            seen.add(value)
            urls.append(value)
    for match in re.findall(r"https?://[^\s)\]>\"']+", text):
        cleaned = match.rstrip(".,;:")
        if cleaned not in seen:
            seen.add(cleaned)
            urls.append(cleaned)
    return urls


def static_source_class(domain: str) -> str | None:
    lowered = domain.lower()
    if lowered.endswith(".gov") or lowered.endswith(".edu") or lowered in EARNED_HIGH_DOMAINS:
        return "EARNED-HIGH"
    if lowered in UGC_DOMAINS:
        return "UGC"
    if lowered in EARNED_MID_DOMAINS:
        return "EARNED-MID"
    return None


def host_from_url(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def registered_domain(host: str) -> str:
    """eTLD+1 of a host (e.g. ``blog.acme.co.uk`` -> ``acme.co.uk``).

    Uses publicsuffix2 when available; falls back to the last two labels.
    """
    if not host:
        return ""
    try:
        from publicsuffix2 import get_sld

        return (get_sld(host) or host).lower()
    except Exception:
        parts = host.lower().strip(".").split(".")
        if len(parts) <= 2:
            return host.lower().strip(".")
        return ".".join(parts[-2:])


def source_judgment_payload(judgments: list[SourceDomainJudgment]) -> list[dict[str, Any]]:
    return [
        {
            "domain": judgment.domain,
            "source_class": judgment.source_class,
            "source": judgment.source,
            "confidence": judgment.confidence,
            "prompt_hash": judgment.prompt_hash.hex() if judgment.prompt_hash else None,
            "raw_judgment": judgment.raw_judgment,
        }
        for judgment in judgments
    ]


def _ordinal_median(labels: list[str]) -> str:
    if not labels:
        return "N"
    ordered = sorted(STANCE_LABELS.index(label) for label in labels if label in STANCE_LABELS)
    if not ordered:
        return "N"
    return STANCE_LABELS[ordered[len(ordered) // 2]]


def _source_rank(source_class: str) -> int:
    priority = {
        "OWNED": 0,
        "COMPETITOR": 1,
        "EARNED-HIGH": 2,
        "EARNED-MID": 3,
        "UGC": 4,
        "UNKNOWN": 5,
    }
    return priority.get(source_class, 99)


def _json_object(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _metadata_urls(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in {"url", "uri"} and isinstance(item, str) and item.startswith(("http://", "https://")):
                yield item.rstrip(".,;:")
            yield from _metadata_urls(item)
    elif isinstance(value, list):
        for item in value:
            yield from _metadata_urls(item)
