"""Read-only public website ingestion for AISO client context discovery."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from ipaddress import ip_address
from http.client import HTTPConnection, HTTPSConnection, HTTPResponse
from typing import Callable, Iterable
from urllib.parse import urljoin, urlparse, urlunparse
import ssl
import json
import os
import re
import socket
import xml.etree.ElementTree as ET


class URLSafetyError(ValueError):
    """Raised when a URL would create SSRF or unsafe navigation risk."""


@dataclass(frozen=True)
class IngestionConfig:
    max_pages: int = 8
    max_depth: int = 1
    max_bytes: int = 1_200_000
    timeout_seconds: float = 8.0
    max_redirects: int = 5
    user_agent: str = "AISOContextBot/1.0 (+https://sapienic.com)"


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str
    status_code: int
    content_type: str
    text: str
    headers: dict[str, str] = field(default_factory=dict)


FetchPage = Callable[[str, IngestionConfig], FetchResult]
Resolver = Callable[..., list]

CTA_TERMS = (
    "facial",
    "facials",
    "skincare",
    "service",
    "services",
    "menu",
    "treatment",
    "treatments",
    "pricing",
    "price",
    "location",
    "locations",
    "book",
    "booking",
    "schedule",
    "appointment",
    "brow",
    "lash",
    "shop",
    "products",
    "faq",
)

ALLOWED_PUBLIC_CTA_HOSTS = {
    "acuityscheduling.com",
    "booksy.com",
    "boulevard.io",
    "boulevard-booking.com",
    "clover.com",
    "fresha.com",
    "glossgenius.com",
    "janeapp.com",
    "mindbodyonline.com",
    "opentable.com",
    "resy.com",
    "schedulicity.com",
    "square.site",
    "squareup.com",
    "toasttab.com",
    "vagaro.com",
    "zenoti.com",
}

STOP_TERMS = (
    "captcha",
    "i am not a robot",
    "checkout",
    "payment",
    "confirm appointment",
    "customer portal",
    "admin",
)

AUTH_STOP_TERMS = (
    "sign in",
    "log in",
    "login",
    "my account",
)

SENSITIVE_FIELD_TERMS = (
    "password",
    "credit card",
    "card number",
    "cvv",
    "social security",
    "ssn",
    "date of birth",
    "medical",
    "insurance",
)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _resolve_public_targets(
    host: str,
    port: int,
    *,
    resolver: Resolver = socket.getaddrinfo,
) -> list[str]:
    """Resolve host once and return only public targets for the actual connect."""
    clean = host.strip("[]").strip().lower()
    if not clean:
        raise URLSafetyError("Website URL must include a public host")
    if clean == "localhost" or clean.endswith(".localhost") or clean.endswith(".local"):
        raise URLSafetyError("Private, local, or internal hosts are blocked")

    try:
        literal = ip_address(clean)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise URLSafetyError("Private, local, or internal hosts are blocked")
        return [str(literal)]

    try:
        records = resolver(clean, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise URLSafetyError("Website host could not be resolved")

    targets: list[str] = []
    for record in records:
        sockaddr = record[4]
        if not sockaddr:
            continue
        resolved_ip = str(sockaddr[0])
        try:
            parsed = ip_address(resolved_ip)
        except ValueError as exc:
            raise URLSafetyError("Website host resolved to an invalid address") from exc
        if not parsed.is_global:
            raise URLSafetyError("Private, local, or internal hosts are blocked")
        if resolved_ip not in targets:
            targets.append(resolved_ip)

    if not targets:
        raise URLSafetyError("Website host could not be resolved")
    return targets


def validate_public_url(raw_url: str, *, resolver: Resolver = socket.getaddrinfo) -> str:
    """Return a normalized public http(s) URL or raise URLSafetyError."""
    raw = str(raw_url or "").strip()
    if not raw:
        raise URLSafetyError("Website URL is required")
    if "://" not in raw:
        raw = f"https://{raw}"

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise URLSafetyError("Only public http and https URLs are supported")
    if not parsed.netloc or parsed.username or parsed.password:
        raise URLSafetyError("Website URL must include a public host")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise URLSafetyError("Website URL includes an invalid port") from exc
    _resolve_public_targets(parsed.hostname or "", port, resolver=resolver)

    path = parsed.path or "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, ""))


def safe_join_url(base_url: str, href: str, *, resolver: Resolver = socket.getaddrinfo) -> str | None:
    href = str(href or "").strip()
    if not href or href.startswith(("#", "mailto:", "tel:", "sms:", "javascript:")):
        return None
    try:
        return validate_public_url(urljoin(base_url, href), resolver=resolver)
    except URLSafetyError:
        return None


def _read_limited_http_response(response: HTTPResponse, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise URLSafetyError("Website response is too large to ingest safely")
        chunks.append(chunk)
    return b"".join(chunks)


class PinnedHTTPConnection(HTTPConnection):
    def __init__(self, hostname: str, pinned_ip: str, port: int, timeout: float):
        super().__init__(hostname, port=port, timeout=timeout)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout, self.source_address)


class PinnedHTTPSConnection(HTTPSConnection):
    def __init__(self, hostname: str, pinned_ip: str, port: int, timeout: float):
        super().__init__(hostname, port=port, timeout=timeout, context=ssl.create_default_context())
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        raw_sock = socket.create_connection((self._pinned_ip, self.port), self.timeout, self.source_address)
        self.sock = self._context.wrap_socket(raw_sock, server_hostname=self.host)


def _fetch_once_pinned(url: str, config: IngestionConfig, *, resolver: Resolver) -> FetchResult:
    parsed = urlparse(validate_public_url(url, resolver=resolver))
    hostname = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    target_ip = _resolve_public_targets(hostname, port, resolver=resolver)[0]
    path = urlunparse(("", "", parsed.path or "/", "", parsed.query, ""))
    host_header = parsed.netloc
    headers = {
        "User-Agent": config.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5",
        "Host": host_header,
        "Connection": "close",
    }
    conn_cls = PinnedHTTPSConnection if parsed.scheme == "https" else PinnedHTTPConnection
    conn = conn_cls(hostname, target_ip, port, config.timeout_seconds)
    try:
        conn.request("GET", path or "/", headers=headers)
        response = conn.getresponse()
        content_type = response.getheader("content-type", "")
        body = b""
        if "text/html" in content_type or "xml" in content_type or "text/plain" in content_type:
            body = _read_limited_http_response(response, config.max_bytes)
        return FetchResult(
            url=url,
            final_url=url,
            status_code=response.status,
            content_type=content_type,
            text=body.decode("utf-8", errors="replace"),
            headers={key.lower(): value for key, value in response.getheaders()},
        )
    finally:
        conn.close()


def fetch_public_page(
    url: str,
    config: IngestionConfig,
    *,
    resolver: Resolver = socket.getaddrinfo,
) -> FetchResult:
    """Fetch a public page with pinned DNS resolution and redirect safety checks."""
    current_url = validate_public_url(url, resolver=resolver)

    for _ in range(config.max_redirects + 1):
        response = _fetch_once_pinned(current_url, config, resolver=resolver)
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location", "")
            next_url = safe_join_url(current_url, location, resolver=resolver)
            if not next_url:
                raise URLSafetyError("Website redirected to an unsafe URL")
            current_url = next_url
            continue

        validate_public_url(current_url, resolver=resolver)
        return FetchResult(
            url=url,
            final_url=current_url,
            status_code=response.status_code,
            content_type=response.content_type,
            text=response.text,
        )

    raise URLSafetyError("Website redirected too many times")


def render_public_page(
    url: str,
    config: IngestionConfig,
    *,
    resolver: Resolver = socket.getaddrinfo,
) -> FetchResult:
    """Render a public page with Playwright without storing session state."""
    safe_url = validate_public_url(url, resolver=resolver)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError("Playwright is unavailable for rendered extraction") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent=config.user_agent,
                java_script_enabled=True,
                ignore_https_errors=False,
            )
            page = context.new_page()
            page.goto(
                safe_url,
                wait_until="domcontentloaded",
                timeout=int(config.timeout_seconds * 1000),
            )
            final_url = validate_public_url(page.url, resolver=resolver)
            html = page.content()
            if len(html.encode("utf-8")) > config.max_bytes:
                raise URLSafetyError("Rendered website response is too large to ingest safely")
            return FetchResult(
                url=safe_url,
                final_url=final_url,
                status_code=200,
                content_type="text/html; rendered=playwright",
                text=html,
            )
        finally:
            browser.close()


class EvidenceHTMLParser(HTMLParser):
    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.title = ""
        self.headings: list[str] = []
        self.text_blocks: list[str] = []
        self.links: list[dict[str, str]] = []
        self.buttons: list[dict[str, str]] = []
        self.json_ld: list[object] = []
        self.forms: list[dict[str, object]] = []
        self._skip_depth = 0
        self._script_type: str | None = None
        self._script_text: list[str] = []
        self._in_title = False
        self._title_text: list[str] = []
        self._blocks: list[dict[str, object]] = []
        self._form: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.lower(): value or "" for key, value in attrs}
        if tag in {"style", "noscript"}:
            self._skip_depth += 1
            return
        if tag == "script":
            self._script_type = attr.get("type", "")
            self._script_text = []
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            self._title_text = []
        if tag == "form":
            self._form = {"action": attr.get("action", ""), "inputs": []}
        if tag in {"input", "textarea", "select"} and self._form is not None:
            inputs = self._form.setdefault("inputs", [])
            assert isinstance(inputs, list)
            inputs.append(
                {
                    "type": attr.get("type", tag),
                    "name": attr.get("name", ""),
                    "placeholder": attr.get("placeholder", ""),
                    "autocomplete": attr.get("autocomplete", ""),
                }
            )
        if tag in {"h1", "h2", "h3", "h4", "p", "li", "a", "button"}:
            self._blocks.append({"tag": tag, "attrs": attr, "text": []})

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            script = "".join(self._script_text).strip()
            if "ld+json" in (self._script_type or "") and script:
                try:
                    parsed = json.loads(script)
                    if isinstance(parsed, list):
                        self.json_ld.extend(parsed)
                    else:
                        self.json_ld.append(parsed)
                except json.JSONDecodeError:
                    pass
            self._script_type = None
            self._script_text = []
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag in {"style", "noscript"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "title":
            self.title = _clean_text(" ".join(self._title_text))
            self._in_title = False
        if tag == "form" and self._form is not None:
            self.forms.append(self._form)
            self._form = None
        if self._blocks and self._blocks[-1]["tag"] == tag:
            block = self._blocks.pop()
            text = _clean_text(" ".join(block["text"]))[:600]
            if not text:
                return
            if tag in {"h1", "h2", "h3", "h4"}:
                self.headings.append(text)
            elif tag == "a":
                href = str(block["attrs"].get("href", ""))
                self.links.append({"text": text, "href": href})
            elif tag == "button":
                self.buttons.append({"text": text, "href": str(block["attrs"].get("formaction", ""))})
            else:
                self.text_blocks.append(text)

    def handle_data(self, data: str) -> None:
        if self._script_type is not None:
            self._script_text.append(data)
            return
        if self._skip_depth:
            return
        text = _clean_text(data)
        if not text:
            return
        if self._in_title:
            self._title_text.append(text)
        for block in self._blocks:
            pieces = block["text"]
            assert isinstance(pieces, list)
            pieces.append(text)


def extract_html_evidence(html: str, page_url: str) -> dict[str, object]:
    parser = EvidenceHTMLParser(page_url)
    parser.feed(html or "")
    all_text = " ".join([parser.title, *parser.headings, *parser.text_blocks, *[item["text"] for item in parser.buttons]])
    return {
        "url": page_url,
        "title": parser.title,
        "headings": _dedupe(parser.headings, limit=40),
        "text_blocks": _dedupe(parser.text_blocks, limit=120),
        "links": parser.links[:120],
        "buttons": parser.buttons[:40],
        "json_ld": parser.json_ld[:20],
        "forms": parser.forms[:20],
        "stop_reason": detect_stop_reason(all_text, parser.forms),
    }


def _dedupe(values: Iterable[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = _clean_text(value)
        key = clean.casefold()
        if not clean or key in seen:
            continue
        seen.add(key)
        result.append(clean)
        if len(result) >= limit:
            break
    return result


def detect_stop_reason(text: str, forms: list[dict[str, object]] | None = None) -> str | None:
    lower = text.casefold()
    for term in STOP_TERMS:
        if term in lower:
            return term
    # Normal marketing pages often contain account links in the nav. Treat auth
    # copy as a stop condition only when the page appears to be auth-focused.
    if len(lower) < 1500:
        for term in AUTH_STOP_TERMS:
            if term in lower:
                return term
    for form in forms or []:
        for item in form.get("inputs", []):
            raw = " ".join(str(item.get(key, "")) for key in ("type", "name", "placeholder", "autocomplete"))
            lowered = raw.casefold()
            if any(term in lowered for term in SENSITIVE_FIELD_TERMS):
                return "sensitive form"
    return None


def _same_site(base_url: str, candidate_url: str) -> bool:
    def normalized_host(value: str) -> str:
        return (urlparse(value).hostname or "").lower().removeprefix("www.")

    return normalized_host(base_url) == normalized_host(candidate_url)


def _hostname_matches(hostname: str, allowed_host: str) -> bool:
    clean = hostname.lower().strip(".")
    allowed = allowed_host.lower().strip(".")
    return clean == allowed or clean.endswith(f".{allowed}")


def _allowed_external_cta(base_url: str, candidate_url: str, link: dict[str, str]) -> bool:
    if _same_site(base_url, candidate_url):
        return True
    if not _link_priority(link):
        return False
    candidate_host = urlparse(candidate_url).hostname or ""
    return any(_hostname_matches(candidate_host, allowed) for allowed in ALLOWED_PUBLIC_CTA_HOSTS)


def _link_priority(link: dict[str, str]) -> int:
    text = f"{link.get('text', '')} {link.get('href', '')}".casefold()
    return 1 if any(term in text for term in CTA_TERMS) else 0


def _parse_sitemap_urls(xml_text: str) -> list[str]:
    urls: list[str] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    for element in root.iter():
        if element.tag.endswith("loc") and element.text:
            urls.append(element.text.strip())
    return urls


def _robots_allows_homepage(robots_text: str) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    if re.search(r"(?im)^\s*disallow:\s*/\s*$", robots_text or ""):
        warnings.append("Crawl limited by robots/access rules.")
        return False, warnings
    return True, warnings


def discover_website(
    website_url: str,
    *,
    config: IngestionConfig | None = None,
    fetch_page: FetchPage | None = None,
    resolver: Resolver = socket.getaddrinfo,
) -> dict[str, object]:
    """Discover public website evidence without forms, logins, or private pages."""
    config = config or IngestionConfig()
    safe_home = validate_public_url(website_url, resolver=resolver)
    fetcher = fetch_page or (lambda url, cfg: fetch_public_page(url, cfg, resolver=resolver))
    warnings: list[str] = []
    pages: list[dict[str, object]] = []
    seen: set[str] = set()
    queue: list[tuple[str, int]] = [(safe_home, 0)]

    parsed_home = urlparse(safe_home)
    robots_url = f"{parsed_home.scheme}://{parsed_home.netloc}/robots.txt"
    sitemap_url = f"{parsed_home.scheme}://{parsed_home.netloc}/sitemap.xml"

    try:
        robots = fetcher(robots_url, config)
        if robots.status_code < 400:
            allowed, robot_warnings = _robots_allows_homepage(robots.text)
            warnings.extend(robot_warnings)
            if not allowed:
                return {"start_url": safe_home, "pages": [], "warnings": warnings, "page_count": 0}
    except Exception:
        warnings.append("Robots.txt could not be read; continuing with public homepage only.")

    try:
        sitemap = fetcher(sitemap_url, config)
        if sitemap.status_code < 400:
            for loc in _parse_sitemap_urls(sitemap.text):
                safe_loc = safe_join_url(safe_home, loc, resolver=resolver)
                if safe_loc and _same_site(safe_home, safe_loc):
                    priority = 1 if any(term in safe_loc.casefold() for term in CTA_TERMS) else 0
                    if priority:
                        queue.append((safe_loc, 1))
    except Exception:
        pass

    while queue and len(pages) < config.max_pages:
        url, depth = queue.pop(0)
        if url in seen or depth > config.max_depth:
            continue
        seen.add(url)
        try:
            fetched = fetcher(url, config)
        except URLSafetyError as exc:
            warnings.append(str(exc))
            continue
        except Exception:
            warnings.append("A public page could not be read during discovery.")
            continue

        page = extract_html_evidence(fetched.text, fetched.final_url)
        if os.getenv("AISO_INGEST_RENDERED", "0") == "1" and not page.get("stop_reason"):
            try:
                rendered = render_public_page(fetched.final_url, config, resolver=resolver)
                rendered_page = extract_html_evidence(rendered.text, rendered.final_url)
                if len(rendered_page.get("text_blocks", [])) > len(page.get("text_blocks", [])):
                    page = rendered_page
                    fetched = rendered
            except Exception:
                warnings.append("Rendered DOM extraction was unavailable; static public HTML was used.")
        page["status_code"] = fetched.status_code
        page["content_type"] = fetched.content_type
        if page.get("stop_reason"):
            warnings.append(f"Stopped before interacting with a page that looked like {page['stop_reason']}.")
            pages.append(page)
            continue

        pages.append(page)
        if depth >= config.max_depth:
            continue

        links = sorted(
            page.get("links", []),
            key=lambda item: _link_priority(item),
            reverse=True,
        )
        for link in links:
            href = str(link.get("href") or "")
            candidate = safe_join_url(fetched.final_url, href, resolver=resolver)
            if not candidate or candidate in seen or not _allowed_external_cta(safe_home, candidate, link):
                continue
            if _link_priority(link) or len(queue) < 3:
                queue.append((candidate, depth + 1))

    if len(seen) >= config.max_pages:
        warnings.append("Discovery reached the configured page limit.")

    return {
        "start_url": safe_home,
        "pages": pages,
        "warnings": _dedupe(warnings, limit=20),
        "page_count": len(pages),
        "rendered_dom": os.getenv("AISO_INGEST_RENDERED", "0") == "1",
    }
