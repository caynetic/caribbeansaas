#!/usr/bin/env python3
"""Local-only review ledger for CaribbeanSaaS discovery work.

This tool deliberately separates private research from the public catalog.  It
can add a narrowly sanitized, ``visibility: unlisted`` record to the catalog
only after a candidate has passed the review gate.  It never edits an existing
catalog record, lists a product, sends outreach, or performs network activity.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = next(
    (
        parent
        for parent in SCRIPT_PATH.parents
        if (parent / ".git").exists() and (parent / "data" / "products.json").is_file()
    ),
    SCRIPT_PATH.parents[4],
)
DEFAULT_PRIVATE_ROOT = REPO_ROOT / "private" / "reviews"
DEFAULT_CATALOG = REPO_ROOT / "data" / "products.json"
SCHEMA_VERSION = 5
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
PRIVATE_FIELD_NAMES = {
    "audit",
    "auditfindings",
    "auditnotes",
    "auditscope",
    "automatedreview",
    "automatedreviewjson",
    "catalogmatchid",
    "confidence",
    "contact",
    "duplicatekind",
    "duplicatesignals",
    "email",
    "evidence",
    "evidencea",
    "evidenceb",
    "holdcodes",
    "holds",
    "humandecision",
    "humandecisionjson",
    "internalnotes",
    "internalreason",
    "internalreview",
    "leadkey",
    "limitations",
    "modelprovenance",
    "phone",
    "privatenotes",
    "privatereview",
    "raw",
    "rawpayload",
    "recommendation",
    "reviewstate",
    "reviewnotes",
    "runid",
    "sideeffectattestation",
    "sourcefailures",
    "sourceids",
    "sources",
    "sourceurls",
    "syncedcatalogid",
}
SENSITIVE_PRIVATE_FIELD_NAMES = {
    "accesstoken",
    "apikey",
    "authorization",
    "browserstate",
    "contact",
    "contactdetails",
    "contactemail",
    "contactname",
    "contactphone",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "email",
    "emailaddress",
    "formdata",
    "forminput",
    "password",
    "phone",
    "phonenumber",
    "refreshtoken",
    "secret",
    "token",
}
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_CANDIDATE_PATTERN = re.compile(r"(?<!\w)\+?\d[\d().\s-]{5,}\d(?!\w)")
PUBLIC_INPUT_FIELDS = (
    "name",
    "websiteUrl",
    "companyName",
    "tagline",
    "description",
    "country",
    "countries",
    "category",
    "industry",
    "tags",
    "productKind",
    "aliases",
    "officialAppStoreIds",
    "caribbeanConnection",
)
ALLOWED_VISIBILITIES = {"listed", "unlisted"}
PRODUCT_KINDS = {
    "api_or_developer_tool",
    "digital_platform",
    "marketplace",
    "mobile_app",
    "open_source_project",
    "saas",
    "software_enabled_service",
    "web_tool",
}
REQUIRED_PUBLIC_PROJECTION_FIELDS = (
    "name",
    "websiteUrl",
    "tagline",
    "description",
    "productKind",
    "country",
    "category",
    "industry",
    "companyName",
    "caribbeanConnection",
)
PUBLIC_RECORD_FIELDS = {
    "id",
    "slug",
    "name",
    "tagline",
    "description",
    "productKind",
    "websiteUrl",
    "country",
    "countries",
    "category",
    "industry",
    "tags",
    "aliases",
    "officialAppStoreIds",
    "logoUrl",
    "logoAlt",
    "logoWidth",
    "logoHeight",
    "screenshotUrls",
    "companyName",
    "founderNames",
    "caribbeanConnection",
    "visibility",
    "publishedAt",
    "updatedAt",
}
PUBLIC_CONTACT_SCAN_FIELDS = {
    "name",
    "tagline",
    "description",
    "country",
    "countries",
    "category",
    "industry",
    "tags",
    "aliases",
    "companyName",
    "founderNames",
    "caribbeanConnection",
}
OFFICIAL_SOURCE_CLASSES = {"official_site", "official_app_store", "official_registry", "official_announcement"}
CORROBORATING_SOURCE_CLASSES = {
    "accelerator",
    "conference",
    "government_program",
    "github",
    "package_registry",
    "reputable_press",
    "university",
}
SOURCE_CLASSES = OFFICIAL_SOURCE_CLASSES | CORROBORATING_SOURCE_CLASSES | {
    "directory",
    "other",
    "search_result",
    "social",
}
INGEST_ATTESTATION_FIELDS = {
    "accountsCreated",
    "authenticatedOrMutationTesting",
    "catalogWrites",
    "contactsMade",
    "deploymentActions",
    "formsSubmitted",
    "listedVisibilityWrites",
    "paymentsOrTrialsStarted",
    "repositoryActions",
}
WORKER_REQUIREMENTS = {
    "scout": {
        "agent": "caribbean_scout",
        "models": {"gpt-5.6-luna", "gpt-5.6-terra"},
        "reasoningEffort": "low",
    },
    "verifier": {
        "agent": "caribbean_verifier",
        "models": {"gpt-5.6-terra"},
        "reasoningEffort": "medium",
    },
    "auditor": {
        "agent": "caribbean_auditor",
        "models": {"gpt-5.6-sol"},
        "reasoningEffort": "high",
    },
}
WORKER_STATUSES = {"complete", "partial", "stopped"}
WORKER_ATTESTATION_FIELDS = {
    "accountsCreated",
    "authenticatedOrMutationTesting",
    "catalogWrites",
    "contactsMade",
    "deploymentActions",
    "formsSubmitted",
    "localWrites",
    "paymentsOrTrialsStarted",
    "repositoryActions",
}
SOURCE_REFERENCE_FIELDS = {"sourceIds", "evidenceSourceIds"}
PUBLICATION_MODE_DISABLED = "disabled"
PUBLICATION_MODE_UNLISTED = "publish_unlisted"
PUBLICATION_PREPARE_STATUSES = {"prepared", "not_applicable", "blocked"}
PUBLICATION_RESULT_STATUSES = {
    "tests_failed",
    "commit_failed",
    "push_conflict",
    "push_failed",
    "pushed_not_verified",
    "deployment_failed",
    "live_verified",
}


class LedgerError(RuntimeError):
    """An expected safe-stop condition for the ledger CLI."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def normalize_name(value: Any) -> str:
    cleaned = text(value)
    if not cleaned:
        return ""
    ascii_value = unicodedata.normalize("NFKD", cleaned).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_value.casefold())


def slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")
    return slug or "digital-product"


def canonicalize_url(value: Any) -> str:
    candidate = text(value)
    if not candidate:
        raise LedgerError("A candidate requires an official websiteUrl.")
    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parts = urlsplit(candidate)
    scheme = parts.scheme.casefold()
    host = (parts.hostname or "").casefold().rstrip(".")
    if scheme not in {"http", "https"} or not host or parts.username or parts.password:
        raise LedgerError(f"websiteUrl must be a plain HTTP(S) URL: {value!r}")
    if host.startswith("www."):
        host = host[4:]

    try:
        port = parts.port
    except ValueError as error:
        raise LedgerError(f"websiteUrl contains an invalid port: {value!r}") from error
    netloc = host
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{host}:{port}"

    query_pairs = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in TRACKING_QUERY_KEYS
        and not sensitive_private_key(key)
    ]
    query = urlencode(sorted(query_pairs))
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, query, ""))


def canonical_domain(value: Any) -> str:
    canonical_url = canonicalize_url(value)
    return (urlsplit(canonical_url).hostname or "").casefold()


def normalize_app_store_id(value: Any) -> str | None:
    cleaned = text(value)
    if not cleaned:
        return None
    if EMAIL_PATTERN.search(cleaned):
        return None
    if cleaned.startswith(("http://", "https://")):
        parts = urlsplit(cleaned)
        host = (parts.hostname or "").casefold()
        if host.endswith("apps.apple.com"):
            match = re.search(r"/id(\d+)(?:[/?#]|$)", parts.path)
            if match:
                return f"apple:{match.group(1)}"
        if host.endswith("play.google.com"):
            package_id = dict(parse_qsl(parts.query)).get("id")
            if package_id:
                return f"google:{package_id.casefold()}"
        return f"url:{canonicalize_url(cleaned)}"
    lowered = cleaned.casefold()
    if re.fullmatch(r"(?:apple:|ios:|id)?\d+", lowered):
        digits = re.sub(r"\D", "", lowered)
        return f"apple:{digits}"
    if lowered.startswith(("google:", "android:")):
        package_id = lowered.split(":", 1)[1]
        if re.fullmatch(r"[a-z0-9_]+(?:\.[a-z0-9_]+)+", package_id):
            return f"google:{package_id}"
        return None
    if re.fullmatch(r"[a-z0-9_]+(?:\.[a-z0-9_]+)+", lowered):
        return f"google:{lowered}"
    return None


def candidate_app_store_ids(payload: dict[str, Any]) -> list[str]:
    raw_values: Any = None
    for key in (
        "officialAppStoreIds",
        "appStoreIds",
        "official_app_store_ids",
        "app_store_ids",
    ):
        if key in payload:
            raw_values = payload[key]
            break
    values = raw_values if isinstance(raw_values, list) else ([raw_values] if raw_values else [])
    normalized: list[str] = []
    for value in values:
        app_store_id = normalize_app_store_id(value)
        if app_store_id and app_store_id not in normalized:
            normalized.append(app_store_id)
    return normalized


def candidate_aliases(payload: dict[str, Any], candidate_name: str | None = None) -> list[str]:
    aliases = safe_list(payload.get("aliases"))
    candidate_key = normalize_name(candidate_name)
    result: list[str] = []
    for alias in aliases:
        if contains_contact_detail(alias):
            continue
        alias_key = normalize_name(alias)
        if alias_key and alias_key != candidate_key and alias_key not in {
            normalize_name(value) for value in result
        }:
            result.append(alias)
    return result


def safe_list(value: Any) -> list[str]:
    if value is None:
        return []
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list):
        return []

    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        cleaned = text(item)
        if cleaned and cleaned.casefold() not in seen:
            seen.add(cleaned.casefold())
            result.append(cleaned)
    return result


def optional_text(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        cleaned = text(payload.get(key))
        if cleaned:
            return cleaned
    return None


def normalised_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def sensitive_private_key(value: str) -> bool:
    normalized = normalised_key(value)
    if normalized in SENSITIVE_PRIVATE_FIELD_NAMES or normalized.startswith("contact"):
        return True
    return normalized.endswith(
        (
            "accesstoken",
            "apikey",
            "authorization",
            "cookie",
            "credential",
            "email",
            "password",
            "phone",
            "refreshtoken",
            "secret",
        )
    )


def redact_contact_text(value: str) -> str:
    redacted = EMAIL_PATTERN.sub("[redacted email]", value)

    def redact_phone(match: re.Match[str]) -> str:
        candidate = match.group(0).strip()
        if re.fullmatch(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", candidate):
            return match.group(0)
        if len(re.sub(r"\D", "", candidate)) >= 7:
            return "[redacted phone]"
        return match.group(0)

    return PHONE_CANDIDATE_PATTERN.sub(redact_phone, redacted)


def sanitize_private_value(value: Any, path: str = "") -> tuple[Any, list[str]]:
    """Retain review evidence while removing contact, credential, and browser data."""
    redacted_paths: list[str] = []
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            item_path = f"{path}.{key}" if path else str(key)
            if sensitive_private_key(str(key)):
                redacted_paths.append(item_path)
                continue
            sanitized_item, item_redactions = sanitize_private_value(item, item_path)
            sanitized[str(key)] = sanitized_item
            redacted_paths.extend(item_redactions)
        return sanitized, redacted_paths
    if isinstance(value, list):
        sanitized_list: list[Any] = []
        for index, item in enumerate(value):
            item_path = f"{path}[{index}]"
            sanitized_item, item_redactions = sanitize_private_value(item, item_path)
            sanitized_list.append(sanitized_item)
            redacted_paths.extend(item_redactions)
        return sanitized_list, redacted_paths
    if isinstance(value, str):
        normalized_path = normalised_key(path)
        if "officialappstoreids" in normalized_path:
            return value, redacted_paths
        if normalized_path.endswith(
            ("url", "sourceurl", "websiteurl", "finalurl", "canonicalofficialurl")
        ) and value.startswith(("http://", "https://")):
            if EMAIL_PATTERN.search(value):
                redacted_paths.append(f"{path}:contact-in-url")
            return value, redacted_paths
        sanitized_text = redact_contact_text(value)
        if sanitized_text != value:
            redacted_paths.append(f"{path}:contact-in-text")
        return sanitized_text, redacted_paths
    return value, redacted_paths


def contains_contact_detail(value: Any) -> bool:
    values = value if isinstance(value, list) else [value]
    for item in values:
        if not isinstance(item, str):
            continue
        if redact_contact_text(item) != item:
            return True
    return False


def compact_private_payload(
    payload: dict[str, Any],
    evidence_a: dict[str, str] | None,
    evidence_b: dict[str, str] | None,
    sources: list[dict[str, str]],
) -> tuple[dict[str, Any], list[str]]:
    private_review = payload.get("privateReview") or payload.get("private_review") or {}
    sanitized_review, review_redactions = sanitize_private_value(private_review, "privateReview")
    _sanitized_input, input_redactions = sanitize_private_value(payload)
    sanitized_evidence, evidence_redactions = sanitize_private_value(
        {"A": evidence_a, "B": evidence_b},
        "evidence",
    )
    compact = {
        "leadKey": optional_text(payload, "leadKey"),
        "privateReview": sanitized_review if isinstance(sanitized_review, (dict, list)) else {},
        "evidence": sanitized_evidence,
        "aliases": candidate_aliases(payload, text(payload.get("name"))),
        "officialAppStoreIds": candidate_app_store_ids(payload),
        "sourceIds": [
            source["sourceId"]
            for source in sources
            if isinstance(source.get("sourceId"), str) and source["sourceId"]
        ],
    }
    redactions = sorted(set(review_redactions + input_redactions + evidence_redactions))
    return compact, redactions


def normalise_evidence(value: Any) -> dict[str, str] | None:
    if isinstance(value, str):
        source: dict[str, Any] = {"url": value}
    elif isinstance(value, dict):
        source = value
    else:
        return None

    raw_url = optional_text(source, "url", "sourceUrl", "websiteUrl")
    if not raw_url:
        return None
    try:
        url = canonicalize_url(raw_url)
    except LedgerError:
        return None

    evidence = {"url": url}
    for output_key, keys in {
        "title": ("title", "sourceTitle"),
        "summary": ("summary", "claim", "note"),
    }.items():
        value_text = optional_text(source, *keys)
        if value_text:
            evidence[output_key] = redact_contact_text(value_text)
    return evidence


def extract_evidence(payload: dict[str, Any]) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    evidence_a: Any = payload.get("evidenceA") or payload.get("evidence_a")
    evidence_b: Any = payload.get("evidenceB") or payload.get("evidence_b")
    evidence = payload.get("evidence")

    if isinstance(evidence, dict):
        evidence_a = evidence_a or evidence.get("A") or evidence.get("a")
        evidence_b = evidence_b or evidence.get("B") or evidence.get("b")
    elif isinstance(evidence, list):
        for item in evidence:
            if not isinstance(item, dict):
                continue
            label = normalised_key(str(item.get("label") or item.get("id") or item.get("key") or ""))
            if label in {"a", "evidencea"} and not evidence_a:
                evidence_a = item
            elif label in {"b", "evidenceb"} and not evidence_b:
                evidence_b = item

    return normalise_evidence(evidence_a), normalise_evidence(evidence_b)


def safe_public_payload(
    payload: dict[str, Any],
    website_url: str,
) -> tuple[dict[str, Any], list[str]]:
    country = optional_text(payload, "country")
    countries = safe_list(payload.get("countries"))
    if country and country.casefold() not in {item.casefold() for item in countries}:
        countries.insert(0, country)
    if not country and countries:
        country = countries[0]

    result: dict[str, Any] = {
        "name": text(payload.get("name")),
        "websiteUrl": website_url,
    }
    string_fields = {
        "companyName": ("companyName", "company_name"),
        "tagline": ("tagline",),
        "description": ("description",),
        "country": ("country",),
        "category": ("category",),
        "industry": ("industry",),
        "productKind": ("productKind", "product_kind"),
        "caribbeanConnection": ("caribbeanConnection", "caribbean_connection"),
    }
    for output_key, keys in string_fields.items():
        value = country if output_key == "country" else optional_text(payload, *keys)
        if value:
            result[output_key] = value
    if countries:
        result["countries"] = countries
    tags = safe_list(payload.get("tags"))
    if tags:
        result["tags"] = tags
    aliases = candidate_aliases(payload, text(payload.get("name")))
    if aliases:
        result["aliases"] = aliases
    app_store_ids = candidate_app_store_ids(payload)
    if app_store_ids:
        result["officialAppStoreIds"] = app_store_ids
    compact = {key: value for key, value in result.items() if value not in (None, "", [])}
    removed_contact_fields = sorted(
        key
        for key, value in compact.items()
        if key not in {"websiteUrl", "officialAppStoreIds"}
        and contains_contact_detail(value)
    )
    for key in removed_contact_fields:
        compact.pop(key, None)
    return compact, removed_contact_fields


def public_projection_reasons(public_payload: dict[str, Any]) -> list[str]:
    reasons = [
        f"public projection field {field} is required"
        for field in REQUIRED_PUBLIC_PROJECTION_FIELDS
        if not text(public_payload.get(field))
    ]
    product_kind = text(public_payload.get("productKind"))
    if product_kind and product_kind not in PRODUCT_KINDS:
        reasons.append(f"unsupported public productKind: {product_kind}")
    for field, value in public_payload.items():
        if field not in {"websiteUrl", "officialAppStoreIds"} and contains_contact_detail(value):
            reasons.append(f"public projection field {field} contains a contact detail")
    return reasons


def gate_reasons(
    recommendation: str,
    confidence: float | None,
    evidence_a: dict[str, str] | None,
    evidence_b: dict[str, str] | None,
    caribbean_evidence_tier: str,
    sources: list[dict[str, str]],
) -> list[str]:
    reasons: list[str] = []
    usable_sources = [
        source
        for source in sources
        if source.get("access") == "public_read_only"
        and source.get("confidence") in {"high", "medium"}
    ]
    if recommendation != "ready_for_human_review":
        reasons.append("recommendation is not ready_for_human_review")
    if confidence is None or confidence < 0.8:
        reasons.append("confidence is below 0.8")
    if not evidence_a:
        reasons.append("evidence A is missing a valid URL")
    if not evidence_b:
        reasons.append("evidence B is missing a valid URL")
    if evidence_a and evidence_b and evidence_a["url"] == evidence_b["url"]:
        reasons.append("evidence A and B must use distinct URLs")
    source_urls = {
        source.get("url")
        for source in usable_sources
        if source.get("url")
    }
    usable_by_url = {
        str(source["url"]): source
        for source in usable_sources
        if source.get("url")
    }
    evidence_a_source = (
        usable_by_url.get(evidence_a["url"])
        if evidence_a
        else None
    )
    evidence_b_source = (
        usable_by_url.get(evidence_b["url"])
        if evidence_b
        else None
    )
    if evidence_a and evidence_a["url"] not in source_urls:
        reasons.append("evidence A URL is not present in the resolved source set")
    if evidence_b and evidence_b["url"] not in source_urls:
        reasons.append("evidence B URL is not present in the resolved source set")
    if (
        evidence_a_source
        and evidence_a_source.get("sourceClass") not in OFFICIAL_SOURCE_CLASSES
    ):
        reasons.append("evidence A must be an official public source")
    if caribbean_evidence_tier not in {"A", "B"}:
        reasons.append("Caribbean evidence tier must be A or B")
    official_sources = [
        source
        for source in usable_sources
        if source.get("sourceClass") in OFFICIAL_SOURCE_CLASSES
    ]
    official_caribbean_sources = [
        source
        for source in official_sources
        if "caribbean_connection" in source.get("supports", [])
    ]
    distinct_sources = {
        source.get("url")
        for source in usable_sources
        if source.get("url")
    }
    corroborating_sources = [
        source
        for source in usable_sources
        if source.get("sourceClass") in CORROBORATING_SOURCE_CLASSES
        and "caribbean_connection" in source.get("supports", [])
        and all(source["url"] != official["url"] for official in official_sources)
    ]
    if not official_sources:
        reasons.append("an official source is required")
    if caribbean_evidence_tier == "A" and len(distinct_sources) < 2:
        reasons.append("tier A requires a second distinct public source")
    if caribbean_evidence_tier == "A" and not official_caribbean_sources:
        reasons.append(
            "tier A requires an official source that supports the Caribbean connection"
        )
    if caribbean_evidence_tier == "A" and (
        not evidence_a_source
        or "caribbean_connection" not in evidence_a_source.get("supports", [])
    ):
        reasons.append(
            "tier A evidence A must directly support the Caribbean connection"
        )
    if caribbean_evidence_tier == "A" and (
        not evidence_b_source
        or not {
            "identity",
            "operator",
            "caribbean_connection",
        }.intersection(evidence_b_source.get("supports", []))
    ):
        reasons.append(
            "tier A evidence B must provide distinct identity or Caribbean support"
        )
    if caribbean_evidence_tier == "B" and not corroborating_sources:
        reasons.append("an independent corroborating source is required")
    if caribbean_evidence_tier == "B" and (
        not evidence_b_source
        or evidence_b_source.get("sourceClass") not in CORROBORATING_SOURCE_CLASSES
        or "caribbean_connection" not in evidence_b_source.get("supports", [])
    ):
        reasons.append(
            "tier B evidence B must be independent corroboration of the Caribbean connection"
        )
    return reasons


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise LedgerError(f"Missing JSON file: {path}") from error
    except json.JSONDecodeError as error:
        raise LedgerError(f"Invalid JSON in {path}: {error}") from error


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_bytes(path, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def catalog_is_clean(catalog: Path, allow_dirty_catalog: bool) -> bool:
    try:
        is_real_catalog = catalog.resolve() == DEFAULT_CATALOG.resolve()
    except FileNotFoundError:
        is_real_catalog = False
    if allow_dirty_catalog and is_real_catalog:
        raise LedgerError(
            "--allow-dirty-catalog is restricted to isolated non-production catalog fixtures."
        )
    if allow_dirty_catalog:
        return True
    if not is_real_catalog:
        return True

    result = subprocess.run(
        ["git", "status", "--porcelain", "--", "data/products.json"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise LedgerError("Could not confirm whether the real public catalog is clean.")
    return not bool(result.stdout.strip())


def ensure_clean_real_catalog(catalog: Path, allow_dirty_catalog: bool) -> None:
    if not catalog_is_clean(catalog, allow_dirty_catalog):
        raise LedgerError(
            "Refusing to use a dirty real data/products.json. Commit or stash its changes first, "
            "or use --allow-dirty-catalog only for an isolated test fixture."
        )


def git_text(repository: Path, *arguments: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stdout.strip()


def git_paths(repository: Path, *arguments: str) -> tuple[bool, list[str]]:
    result = subprocess.run(
        ["git", *arguments, "-z"],
        cwd=repository,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        return False, []
    return True, sorted(
        part.decode("utf-8", errors="surrogateescape")
        for part in result.stdout.split(b"\0")
        if part
    )


def repository_preflight(catalog: Path) -> dict[str, Any]:
    """Capture local-only Git facts used by the coordinator publication gate."""
    captured_at = utc_now()
    probe = subprocess.run(
        ["git", "-C", str(catalog.parent), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0 or not probe.stdout.strip():
        return {
            "capturedAt": captured_at,
            "repositoryDetected": False,
            "eligible": False,
            "errors": ["catalog is not inside a Git worktree"],
        }

    repository = Path(probe.stdout.strip()).resolve()
    errors: list[str] = []
    try:
        catalog_path = catalog.resolve().relative_to(repository).as_posix()
    except ValueError:
        return {
            "capturedAt": captured_at,
            "repositoryDetected": True,
            "eligible": False,
            "errors": ["catalog is outside its detected Git worktree"],
        }

    branch_ok, branch = git_text(repository, "symbolic-ref", "--quiet", "--short", "HEAD")
    head_ok, head_sha = git_text(repository, "rev-parse", "--verify", "HEAD")
    upstream_ref_ok, upstream_ref = git_text(
        repository,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
    )
    upstream_sha_ok, upstream_sha = git_text(
        repository,
        "rev-parse",
        "--verify",
        "@{upstream}",
    )
    tracked_ok, _tracked_path = git_text(
        repository,
        "ls-files",
        "--error-unmatch",
        "--",
        catalog_path,
    )
    staged_ok, staged_paths = git_paths(
        repository,
        "diff",
        "--cached",
        "--name-only",
        "--no-renames",
    )
    unstaged_ok, unstaged_paths = git_paths(
        repository,
        "diff",
        "--name-only",
        "--no-renames",
    )
    untracked_ok, untracked_paths = git_paths(
        repository,
        "ls-files",
        "--others",
        "--exclude-standard",
    )

    ahead = None
    behind = None
    if head_ok and upstream_sha_ok:
        counts_ok, counts = git_text(
            repository,
            "rev-list",
            "--left-right",
            "--count",
            "HEAD...@{upstream}",
        )
        if counts_ok:
            parts = counts.split()
            if len(parts) == 2 and all(part.isdigit() for part in parts):
                ahead, behind = (int(parts[0]), int(parts[1]))
            else:
                errors.append("could not parse local upstream divergence")
        else:
            errors.append("could not inspect local upstream divergence")

    for succeeded, message in (
        (branch_ok, "could not identify the current Git branch"),
        (head_ok, "could not identify the current Git HEAD"),
        (upstream_ref_ok, "current branch has no locally resolvable upstream"),
        (upstream_sha_ok, "could not identify the local upstream commit"),
        (tracked_ok, "catalog is not tracked by Git"),
        (staged_ok, "could not inspect staged paths"),
        (unstaged_ok, "could not inspect unstaged paths"),
        (untracked_ok, "could not inspect untracked paths"),
    ):
        if not succeeded:
            errors.append(message)

    clean = bool(
        staged_ok
        and unstaged_ok
        and untracked_ok
        and not staged_paths
        and not unstaged_paths
        and not untracked_paths
    )
    aligned = bool(
        head_ok
        and upstream_sha_ok
        and head_sha == upstream_sha
        and ahead == 0
        and behind == 0
    )
    eligible = bool(
        not errors
        and catalog_path == "data/products.json"
        and branch == "main"
        and upstream_ref == "origin/main"
        and clean
        and aligned
    )
    if catalog_path != "data/products.json":
        errors.append("publication catalog path must be data/products.json")
    if branch_ok and branch != "main":
        errors.append("publication requires the main branch")
    if upstream_ref_ok and upstream_ref != "origin/main":
        errors.append("publication requires main to track origin/main")
    if not clean:
        errors.append("publication requires a clean whole worktree at run start")
    if not aligned:
        errors.append("HEAD must match the locally resolved upstream commit")

    return {
        "capturedAt": captured_at,
        "repositoryDetected": True,
        "repositoryRoot": str(repository),
        "catalogPath": catalog_path,
        "catalogTracked": tracked_ok,
        "branch": branch if branch_ok else None,
        "headSha": head_sha if head_ok else None,
        "upstreamRef": upstream_ref if upstream_ref_ok else None,
        "upstreamSha": upstream_sha if upstream_sha_ok else None,
        "ahead": ahead,
        "behind": behind,
        "stagedPaths": staged_paths,
        "unstagedPaths": unstaged_paths,
        "untrackedPaths": untracked_paths,
        "clean": clean,
        "aligned": aligned,
        "eligible": eligible,
        "errors": list(dict.fromkeys(errors)),
    }


def load_catalog(catalog: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = read_json(catalog)
    if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
        raise LedgerError("Catalog JSON must be an object with a products array.")
    products = [item for item in payload["products"] if isinstance(item, dict)]
    if len(products) != len(payload["products"]):
        raise LedgerError("Catalog products must all be JSON objects.")
    return payload, products


def catalog_exact_match(
    products: Iterable[dict[str, Any]],
    candidate_domain: str,
    candidate_app_ids: Iterable[str] = (),
) -> tuple[str, str] | None:
    product_list = list(products)
    for product in product_list:
        product_url = product.get("websiteUrl") or product.get("website_url")
        try:
            if product_url and canonical_domain(product_url) == candidate_domain:
                return "catalog_domain", str(product.get("id") or product.get("slug") or product.get("name"))
        except LedgerError:
            pass
    wanted_app_ids = set(candidate_app_ids)
    if wanted_app_ids:
        for product in product_list:
            if wanted_app_ids & set(candidate_app_store_ids(product)):
                return "catalog_app_store_id", str(
                    product.get("id") or product.get("slug") or product.get("name")
                )
    return None


def catalog_name_match(
    products: Iterable[dict[str, Any]], candidate_names: set[str]
) -> tuple[str, str] | None:
    for product in products:
        product_names = {normalize_name(product.get("name"))}
        product_names.update(
            normalize_name(alias)
            for alias in candidate_aliases(product, text(product.get("name")))
        )
        if product_names & candidate_names:
            return "possible_catalog_name", str(
                product.get("id") or product.get("slug") or product.get("name")
            )
    return None


def catalog_has_private_fields(value: Any, path: str = "") -> list[str]:
    issues: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            current_path = f"{path}.{key}" if path else key
            if normalised_key(key) in PRIVATE_FIELD_NAMES:
                issues.append(current_path)
            issues.extend(catalog_has_private_fields(item, current_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            issues.extend(catalog_has_private_fields(item, f"{path}[{index}]"))
    return issues


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def ensure_private_storage(root: Path, catalog: Path, allow_dirty_catalog: bool) -> None:
    """Fail closed for real-repo writes while allowing isolated test fixtures."""
    try:
        is_real_catalog = catalog.resolve() == DEFAULT_CATALOG.resolve()
    except FileNotFoundError:
        is_real_catalog = False
    if not is_real_catalog:
        return

    private_root = (REPO_ROOT / "private").resolve()
    if not is_within(root, private_root):
        raise LedgerError("The real catalog requires a private ledger under the ignored repo private/ directory.")
    for public_root in (REPO_ROOT / "dist", REPO_ROOT / "data", REPO_ROOT / "assets"):
        if is_within(root, public_root):
            raise LedgerError("Private review storage must not resolve inside a public deployment path.")

    try:
        relative_root = root.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError as error:
        raise LedgerError("Private review storage must resolve inside the repository private/ directory.") from error
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", "--", relative_root],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if ignored.returncode != 0:
        raise LedgerError("Private review storage is not Git-ignored; refusing to create local review records.")


def normalise_sources(raw_sources: Any, source_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    values = raw_sources if isinstance(raw_sources, list) else []
    sources: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for value in values:
        if isinstance(value, str):
            source = source_index.get(value)
            if source is None:
                raise LedgerError(f"Unresolved source reference: {value!r}")
        elif isinstance(value, dict):
            source = value
        else:
            raise LedgerError("Candidate source references must be source IDs or source objects.")
        raw_url = optional_text(source, "url", "sourceUrl", "websiteUrl")
        if not raw_url:
            raise LedgerError("Every referenced source requires a public HTTP(S) URL.")
        try:
            source_url = canonicalize_url(raw_url)
        except LedgerError as error:
            raise LedgerError(f"Referenced source has an invalid URL: {raw_url!r}") from error
        if source_url in seen_urls:
            continue
        seen_urls.add(source_url)
        source_id = optional_text(source, "sourceId", "source_id", "id")
        if not source_id:
            raise LedgerError("Every referenced source requires a sourceId.")
        source_class_text = optional_text(source, "sourceClass", "source_class")
        if not source_class_text:
            raise LedgerError(f"Referenced source {source_id!r} requires a sourceClass.")
        source_class = source_class_text.casefold()
        if source_class not in SOURCE_CLASSES:
            raise LedgerError(
                f"Referenced source {source_id!r} has unsupported sourceClass {source_class!r}."
            )
        compact: dict[str, Any] = {
            "url": source_url,
            "sourceClass": source_class,
            "sourceId": source_id,
        }
        for output_key, keys in {
            "capturedAt": ("capturedAt", "captured_at"),
            "summary": ("summary", "claim", "note"),
        }.items():
            source_text = optional_text(source, *keys)
            if source_text:
                compact[output_key] = (
                    redact_contact_text(source_text)
                    if output_key == "summary"
                    else source_text
                )
        access = optional_text(source, "access")
        confidence = optional_text(source, "confidence")
        supports = source.get("supports")
        if access:
            compact["access"] = access
        if confidence:
            compact["confidence"] = confidence
        if isinstance(supports, list):
            compact["supports"] = list(supports)
        sources.append(compact)
    return sources


def candidate_tier(payload: dict[str, Any]) -> str:
    direct = optional_text(
        payload,
        "caribbeanEvidenceTier",
        "caribbean_evidence_tier",
        "recommendedCaribbeanTier",
    )
    evidence = payload.get("caribbeanEvidence") or payload.get("caribbean_evidence")
    if not direct and isinstance(evidence, dict):
        direct = optional_text(evidence, "tier", "recommendedTier")
    if not direct and isinstance(evidence, list):
        tiers = [optional_text(item, "tier") for item in evidence if isinstance(item, dict)]
        direct = next((tier for tier in tiers if tier), None)
    return (direct or "unknown").upper()


def source_refs(payload: dict[str, Any]) -> list[Any]:
    references: list[Any] = []
    if isinstance(payload.get("sources"), list):
        references.extend(payload["sources"])
    if isinstance(payload.get("sourceIds"), list):
        references.extend(payload["sourceIds"])
    evidence = payload.get("caribbeanEvidence") or payload.get("caribbean_evidence")
    if isinstance(evidence, dict) and isinstance(evidence.get("sourceIds"), list):
        references.extend(evidence["sourceIds"])
    elif isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict) and isinstance(item.get("sourceIds"), list):
                references.extend(item["sourceIds"])
    return references


def collect_source_references(value: Any, path: str = "result") -> set[str]:
    references: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = f"{path}.{key}"
            if key in SOURCE_REFERENCE_FIELDS:
                if not isinstance(item, list) or any(not text(source_id) for source_id in item):
                    raise LedgerError(f"{item_path} must be an array of non-empty source IDs.")
                references.update(str(source_id) for source_id in item)
            else:
                references.update(collect_source_references(item, item_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            references.update(collect_source_references(item, f"{path}[{index}]"))
    return references


def require_exact_keys(
    value: Any,
    path: str,
    required: set[str],
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LedgerError(f"{path} must be a JSON object.")
    optional = optional or set()
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required - optional)
    if missing:
        raise LedgerError(f"{path} is missing required fields: " + ", ".join(missing))
    if unknown:
        raise LedgerError(f"{path} contains unsupported fields: " + ", ".join(unknown))
    return value


def require_text(value: Any, path: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise LedgerError(f"{path} must be a string.")
    if value == "" and allow_empty:
        return value
    if not text(value):
        raise LedgerError(f"{path} must be a non-empty string.")
    return value


def require_text_list(
    value: Any,
    path: str,
    *,
    allowed: set[str] | None = None,
    min_items: int = 0,
) -> list[str]:
    if not isinstance(value, list):
        raise LedgerError(f"{path} must be an array.")
    if len(value) < min_items:
        raise LedgerError(f"{path} must contain at least {min_items} item(s).")
    result: list[str] = []
    for index, item in enumerate(value):
        item_text = require_text(item, f"{path}[{index}]")
        if allowed is not None and item_text not in allowed:
            raise LedgerError(
                f"{path}[{index}] has unsupported value {item_text!r}."
            )
        result.append(item_text)
    return result


def require_enum(value: Any, path: str, allowed: set[str]) -> str:
    value_text = require_text(value, path)
    if value_text not in allowed:
        raise LedgerError(f"{path} has unsupported value {value_text!r}.")
    return value_text


def require_bool(value: Any, path: str) -> bool:
    if type(value) is not bool:
        raise LedgerError(f"{path} must be a boolean.")
    return value


def require_url(value: Any, path: str, allow_empty: bool = False) -> str:
    value_text = require_text(value, path, allow_empty=allow_empty)
    if value_text == "" and allow_empty:
        return value_text
    if not value_text.startswith(("http://", "https://")):
        raise LedgerError(f"{path} must be a public HTTP(S) URL.")
    try:
        canonicalize_url(value_text)
    except LedgerError as error:
        raise LedgerError(f"{path} must be a valid public HTTP(S) URL.") from error
    return value_text


def require_url_list(value: Any, path: str, min_items: int = 0) -> list[str]:
    if not isinstance(value, list):
        raise LedgerError(f"{path} must be an array.")
    if len(value) < min_items:
        raise LedgerError(f"{path} must contain at least {min_items} item(s).")
    return [
        require_url(item, f"{path}[{index}]")
        for index, item in enumerate(value)
    ]


def require_utc_timestamp(value: Any, path: str) -> str:
    value_text = require_text(value, path)
    try:
        parsed = datetime.fromisoformat(value_text.replace("Z", "+00:00"))
    except ValueError as error:
        raise LedgerError(f"{path} must be an ISO 8601 UTC timestamp.") from error
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise LedgerError(f"{path} must be an ISO 8601 UTC timestamp.")
    return value_text


def validate_worker_scope(value: Any, path: str) -> None:
    scope = require_exact_keys(
        value,
        path,
        {
            "territorySlices",
            "languageSlices",
            "sectorSlices",
            "candidateIds",
            "startedAt",
            "finishedAt",
        },
    )
    for field in (
        "territorySlices",
        "languageSlices",
        "sectorSlices",
        "candidateIds",
    ):
        require_text_list(scope[field], f"{path}.{field}")
    started_at = require_utc_timestamp(scope["startedAt"], f"{path}.startedAt")
    finished_at = require_utc_timestamp(scope["finishedAt"], f"{path}.finishedAt")
    if datetime.fromisoformat(finished_at.replace("Z", "+00:00")) < datetime.fromisoformat(
        started_at.replace("Z", "+00:00")
    ):
        raise LedgerError(f"{path}.finishedAt cannot precede startedAt.")


def validate_worker_source(value: Any, path: str) -> None:
    source = require_exact_keys(
        value,
        path,
        {
            "sourceId",
            "url",
            "sourceClass",
            "capturedAt",
            "access",
            "supports",
            "summary",
            "confidence",
        },
    )
    require_text(source["sourceId"], f"{path}.sourceId")
    require_url(source["url"], f"{path}.url")
    require_enum(source["sourceClass"], f"{path}.sourceClass", SOURCE_CLASSES)
    require_utc_timestamp(source["capturedAt"], f"{path}.capturedAt")
    require_enum(
        source["access"],
        f"{path}.access",
        {"public_read_only", "unavailable", "access_blocked", "restricted"},
    )
    require_text_list(
        source["supports"],
        f"{path}.supports",
        allowed={
            "identity",
            "operator",
            "product_purpose",
            "product_kind",
            "caribbean_connection",
            "privacy_policy",
            "terms",
            "availability",
            "security_observation",
            "ux_observation",
        },
    )
    require_text(source["summary"], f"{path}.summary")
    require_enum(
        source["confidence"],
        f"{path}.confidence",
        {"low", "medium", "high"},
    )


def validate_worker_hold(value: Any, path: str) -> None:
    hold = require_exact_keys(
        value,
        path,
        {
            "candidateKey",
            "code",
            "severity",
            "reason",
            "evidenceSourceIds",
            "safeNextHumanAction",
            "terminalForThisRun",
        },
    )
    require_text(hold["candidateKey"], f"{path}.candidateKey")
    require_enum(
        hold["code"],
        f"{path}.code",
        {
            "duplicate_known",
            "possible_duplicate",
            "not_eligible",
            "official_source_unavailable",
            "access_blocked",
            "identity_conflict",
            "caribbean_evidence_insufficient",
            "public_risk",
            "restricted_interaction_required",
            "sensitive_domain_review",
            "storage_safety_failure",
            "catalog_dirty_at_start",
            "run_locked",
            "budget_cap",
            "rate_limited",
            "other",
        },
    )
    require_enum(hold["severity"], f"{path}.severity", {"info", "caution", "high"})
    require_text(hold["reason"], f"{path}.reason")
    require_text_list(hold["evidenceSourceIds"], f"{path}.evidenceSourceIds")
    require_text(
        hold["safeNextHumanAction"],
        f"{path}.safeNextHumanAction",
        allow_empty=True,
    )
    require_bool(hold["terminalForThisRun"], f"{path}.terminalForThisRun")


def validate_scout_result(value: Any, path: str) -> None:
    result = require_exact_keys(value, path, {"queries", "leads", "coverage"})
    queries = result["queries"]
    if not isinstance(queries, list):
        raise LedgerError(f"{path}.queries must be an array.")
    for index, raw_query in enumerate(queries):
        query_path = f"{path}.queries[{index}]"
        query = require_exact_keys(
            raw_query,
            query_path,
            {
                "queryId",
                "territorySlice",
                "languageSlice",
                "sectorSlice",
                "query",
                "sourceClassTarget",
                "executedAt",
                "outcome",
            },
        )
        for field in (
            "queryId",
            "territorySlice",
            "languageSlice",
            "sectorSlice",
            "query",
        ):
            require_text(query[field], f"{query_path}.{field}")
        require_enum(
            query["sourceClassTarget"],
            f"{query_path}.sourceClassTarget",
            SOURCE_CLASSES,
        )
        require_utc_timestamp(query["executedAt"], f"{query_path}.executedAt")
        require_enum(
            query["outcome"],
            f"{query_path}.outcome",
            {"complete", "partial", "restricted", "rate_limited"},
        )

    leads = result["leads"]
    if not isinstance(leads, list):
        raise LedgerError(f"{path}.leads must be an array.")
    for index, raw_lead in enumerate(leads):
        lead_path = f"{path}.leads[{index}]"
        lead = require_exact_keys(
            raw_lead,
            lead_path,
            {
                "leadKey",
                "displayName",
                "candidateUrls",
                "sourceIds",
                "territoryHints",
                "languageHints",
                "productKindHints",
                "sectorHints",
                "aliases",
                "whyItIsALead",
                "confidence",
            },
        )
        for field in ("leadKey", "displayName", "whyItIsALead"):
            require_text(lead[field], f"{lead_path}.{field}")
        require_url_list(lead["candidateUrls"], f"{lead_path}.candidateUrls", min_items=1)
        require_text_list(lead["sourceIds"], f"{lead_path}.sourceIds", min_items=1)
        for field in (
            "territoryHints",
            "languageHints",
            "sectorHints",
            "aliases",
        ):
            require_text_list(lead[field], f"{lead_path}.{field}")
        require_text_list(
            lead["productKindHints"],
            f"{lead_path}.productKindHints",
            allowed=PRODUCT_KINDS,
        )
        require_enum(
            lead["confidence"],
            f"{lead_path}.confidence",
            {"low", "medium", "high"},
        )

    coverage_path = f"{path}.coverage"
    coverage = require_exact_keys(
        result["coverage"],
        coverage_path,
        {"searchedSlices", "unsearchedSlices", "reasonForGaps"},
    )
    for field in ("searchedSlices", "unsearchedSlices", "reasonForGaps"):
        require_text_list(coverage[field], f"{coverage_path}.{field}")


def validate_verifier_result(value: Any, path: str) -> None:
    result = require_exact_keys(value, path, {"entities"})
    entities = result["entities"]
    if not isinstance(entities, list):
        raise LedgerError(f"{path}.entities must be an array.")
    for index, raw_entity in enumerate(entities):
        entity_path = f"{path}.entities[{index}]"
        entity = require_exact_keys(
            raw_entity,
            entity_path,
            {
                "leadKey",
                "resolution",
                "canonical",
                "duplicateSignals",
                "softwareFit",
                "caribbeanEvidence",
                "recommendedCaribbeanTier",
                "auditEligibility",
                "auditTargets",
                "outstandingQuestions",
            },
        )
        require_text(entity["leadKey"], f"{entity_path}.leadKey")
        resolution = require_enum(
            entity["resolution"],
            f"{entity_path}.resolution",
            {
                "new_candidate",
                "duplicate_known",
                "possible_duplicate",
                "existing_recheck",
                "hold",
            },
        )

        canonical_path = f"{entity_path}.canonical"
        canonical = require_exact_keys(
            entity["canonical"],
            canonical_path,
            {
                "officialUrl",
                "finalUrl",
                "canonicalHost",
                "officialAppStoreIds",
                "companyName",
                "productName",
                "aliases",
            },
        )
        official_url = require_url(
            canonical["officialUrl"],
            f"{canonical_path}.officialUrl",
        )
        final_url = require_url(
            canonical["finalUrl"],
            f"{canonical_path}.finalUrl",
        )
        canonical_host = require_text(
            canonical["canonicalHost"],
            f"{canonical_path}.canonicalHost",
        ).casefold().removeprefix("www.").rstrip(".")
        if canonical_host not in {
            canonical_domain(official_url),
            canonical_domain(final_url),
        }:
            raise LedgerError(
                f"{canonical_path}.canonicalHost conflicts with the canonical URLs."
            )
        app_store_ids = require_text_list(
            canonical["officialAppStoreIds"],
            f"{canonical_path}.officialAppStoreIds",
        )
        for app_index, app_store_id in enumerate(app_store_ids):
            if not normalize_app_store_id(app_store_id):
                raise LedgerError(
                    f"{canonical_path}.officialAppStoreIds[{app_index}] "
                    "must be a normalized public app-store ID or URL."
                )
        require_text(canonical["companyName"], f"{canonical_path}.companyName", allow_empty=True)
        require_text(canonical["productName"], f"{canonical_path}.productName")
        require_text_list(canonical["aliases"], f"{canonical_path}.aliases")

        duplicate_signals = entity["duplicateSignals"]
        if not isinstance(duplicate_signals, list):
            raise LedgerError(f"{entity_path}.duplicateSignals must be an array.")
        for signal_index, raw_signal in enumerate(duplicate_signals):
            signal_path = f"{entity_path}.duplicateSignals[{signal_index}]"
            signal = require_exact_keys(
                raw_signal,
                signal_path,
                {"type", "matchedRecord", "confidence", "explanation"},
            )
            require_enum(
                signal["type"],
                f"{signal_path}.type",
                {
                    "exact_domain",
                    "exact_app_store_id",
                    "exact_alias",
                    "fuzzy_name",
                    "same_company",
                    "redirect_match",
                },
            )
            require_text(signal["matchedRecord"], f"{signal_path}.matchedRecord", allow_empty=True)
            require_enum(
                signal["confidence"],
                f"{signal_path}.confidence",
                {"low", "medium", "high"},
            )
            require_text(signal["explanation"], f"{signal_path}.explanation")

        fit_path = f"{entity_path}.softwareFit"
        software_fit = require_exact_keys(
            entity["softwareFit"],
            fit_path,
            {"classification", "reason"},
            {"productKind"},
        )
        classification = require_enum(
            software_fit["classification"],
            f"{fit_path}.classification",
            {"eligible_online_software", "not_eligible", "unclear"},
        )
        require_text(software_fit["reason"], f"{fit_path}.reason")
        product_kind = software_fit.get("productKind")
        if product_kind is not None:
            require_enum(product_kind, f"{fit_path}.productKind", PRODUCT_KINDS)
        if classification == "eligible_online_software" and product_kind not in PRODUCT_KINDS:
            raise LedgerError(
                f"{fit_path}.productKind is required for eligible online software."
            )

        caribbean_evidence = entity["caribbeanEvidence"]
        if not isinstance(caribbean_evidence, list):
            raise LedgerError(f"{entity_path}.caribbeanEvidence must be an array.")
        for evidence_index, raw_evidence in enumerate(caribbean_evidence):
            evidence_path = f"{entity_path}.caribbeanEvidence[{evidence_index}]"
            evidence = require_exact_keys(
                raw_evidence,
                evidence_path,
                {"tier", "claim", "sourceIds", "confidence"},
            )
            require_enum(
                evidence["tier"],
                f"{evidence_path}.tier",
                {"A", "B", "C", "D", "unknown"},
            )
            require_text(evidence["claim"], f"{evidence_path}.claim")
            require_text_list(
                evidence["sourceIds"],
                f"{evidence_path}.sourceIds",
                min_items=1,
            )
            require_enum(
                evidence["confidence"],
                f"{evidence_path}.confidence",
                {"low", "medium", "high"},
            )

        recommended_tier = require_enum(
            entity["recommendedCaribbeanTier"],
            f"{entity_path}.recommendedCaribbeanTier",
            {"A", "B", "C", "D", "unknown"},
        )
        audit_eligibility = require_enum(
            entity["auditEligibility"],
            f"{entity_path}.auditEligibility",
            {"eligible", "hold"},
        )
        require_url_list(entity["auditTargets"], f"{entity_path}.auditTargets")
        require_text_list(
            entity["outstandingQuestions"],
            f"{entity_path}.outstandingQuestions",
        )
        if audit_eligibility == "eligible" and (
            resolution != "new_candidate"
            or classification != "eligible_online_software"
            or product_kind not in PRODUCT_KINDS
        ):
            raise LedgerError(
                f"{entity_path}.auditEligibility may be eligible only for a new, "
                "eligible online-software candidate."
            )
        if audit_eligibility == "eligible" and (
            recommended_tier not in {"A", "B"}
            or not caribbean_evidence
            or not any(
                evidence.get("tier") == recommended_tier
                for evidence in caribbean_evidence
                if isinstance(evidence, dict)
            )
            or not entity["auditTargets"]
        ):
            raise LedgerError(
                f"{entity_path}.auditEligibility requires matching Tier A/B evidence "
                "and at least one public audit target."
            )
        if (
            recommended_tier != "unknown"
            and caribbean_evidence
            and not any(
                evidence.get("tier") == recommended_tier
                for evidence in caribbean_evidence
                if isinstance(evidence, dict)
            )
        ):
            raise LedgerError(
                f"{entity_path}.recommendedCaribbeanTier is not supported by its evidence."
            )
        if recommended_tier in {"C", "D", "unknown"} and audit_eligibility != "hold":
            raise LedgerError(
                f"{entity_path}.auditEligibility must be hold for tier "
                f"{recommended_tier!r}."
            )


def validate_auditor_result(value: Any, path: str) -> None:
    result = require_exact_keys(value, path, {"audits", "synthesis"})
    audits = result["audits"]
    if not isinstance(audits, list):
        raise LedgerError(f"{path}.audits must be an array.")
    for index, raw_audit in enumerate(audits):
        audit_path = f"{path}.audits[{index}]"
        audit = require_exact_keys(
            raw_audit,
            audit_path,
            {
                "leadKey",
                "canonicalOfficialUrl",
                "auditScope",
                "observed",
                "findings",
                "recommendedOutcome",
                "holdCodes",
                "proposedPublicSafeSummary",
                "outstandingQuestions",
                "limitations",
            },
        )
        require_text(audit["leadKey"], f"{audit_path}.leadKey")
        require_url(audit["canonicalOfficialUrl"], f"{audit_path}.canonicalOfficialUrl")
        require_enum(
            audit["auditScope"],
            f"{audit_path}.auditScope",
            {"public_credential_free_surface_only"},
        )

        observed_path = f"{audit_path}.observed"
        observed = require_exact_keys(
            audit["observed"],
            observed_path,
            {
                "identityAndFit",
                "operations",
                "claimConcordance",
                "privacyAndTerms",
                "passivePublicPosture",
                "publicUxSmoke",
            },
        )

        identity_path = f"{observed_path}.identityAndFit"
        identity = require_exact_keys(
            observed["identityAndFit"],
            identity_path,
            {"operator", "productPurpose", "productKind", "sourceIds"},
        )
        require_text(identity["operator"], f"{identity_path}.operator", allow_empty=True)
        require_text(identity["productPurpose"], f"{identity_path}.productPurpose")
        require_enum(identity["productKind"], f"{identity_path}.productKind", PRODUCT_KINDS)
        require_text_list(identity["sourceIds"], f"{identity_path}.sourceIds")

        operations_path = f"{observed_path}.operations"
        operations = require_exact_keys(
            observed["operations"],
            operations_path,
            {
                "sampledAt",
                "rootStatus",
                "finalUrl",
                "httpsObserved",
                "certificateObservation",
                "supportOrContactPath",
                "sourceIds",
            },
        )
        require_utc_timestamp(operations["sampledAt"], f"{operations_path}.sampledAt")
        require_enum(
            operations["rootStatus"],
            f"{operations_path}.rootStatus",
            {"2xx", "3xx", "4xx", "5xx", "unavailable", "access_blocked", "unknown"},
        )
        require_url(operations["finalUrl"], f"{operations_path}.finalUrl", allow_empty=True)
        require_bool(operations["httpsObserved"], f"{operations_path}.httpsObserved")
        require_enum(
            operations["certificateObservation"],
            f"{operations_path}.certificateObservation",
            {"valid_at_sample", "invalid_or_mismatch", "not_checked", "unknown"},
        )
        require_url(
            operations["supportOrContactPath"],
            f"{operations_path}.supportOrContactPath",
            allow_empty=True,
        )
        require_text_list(operations["sourceIds"], f"{operations_path}.sourceIds")

        claims = observed["claimConcordance"]
        if not isinstance(claims, list):
            raise LedgerError(f"{observed_path}.claimConcordance must be an array.")
        for claim_index, raw_claim in enumerate(claims):
            claim_path = f"{observed_path}.claimConcordance[{claim_index}]"
            claim = require_exact_keys(
                raw_claim,
                claim_path,
                {"claimType", "proposedClaim", "supported", "sourceIds", "note"},
            )
            require_enum(
                claim["claimType"],
                f"{claim_path}.claimType",
                {"name", "operator", "description", "category", "country", "caribbean_connection"},
            )
            require_text(claim["proposedClaim"], f"{claim_path}.proposedClaim")
            require_bool(claim["supported"], f"{claim_path}.supported")
            require_text_list(claim["sourceIds"], f"{claim_path}.sourceIds")
            require_text(claim["note"], f"{claim_path}.note", allow_empty=True)

        policy_path = f"{observed_path}.privacyAndTerms"
        policy = require_exact_keys(
            observed["privacyAndTerms"],
            policy_path,
            {"privacyPolicy", "terms", "publicContactIdentity", "sourceIds"},
        )
        for field in ("privacyPolicy", "terms"):
            require_enum(
                policy[field],
                f"{policy_path}.{field}",
                {"present", "absent", "inaccessible", "not_applicable", "unknown"},
            )
        require_enum(
            policy["publicContactIdentity"],
            f"{policy_path}.publicContactIdentity",
            {"present", "absent", "unknown"},
        )
        require_text_list(policy["sourceIds"], f"{policy_path}.sourceIds")

        posture_path = f"{observed_path}.passivePublicPosture"
        posture = require_exact_keys(
            observed["passivePublicPosture"],
            posture_path,
            {
                "headersObserved",
                "mixedContentObserved",
                "publicExposureClues",
                "landingPageTrackers",
                "sourceIds",
            },
        )
        require_text_list(posture["headersObserved"], f"{posture_path}.headersObserved")
        require_enum(
            posture["mixedContentObserved"],
            f"{posture_path}.mixedContentObserved",
            {"yes", "no", "not_checked", "unknown"},
        )
        require_text_list(posture["publicExposureClues"], f"{posture_path}.publicExposureClues")
        require_text_list(posture["landingPageTrackers"], f"{posture_path}.landingPageTrackers")
        require_text_list(posture["sourceIds"], f"{posture_path}.sourceIds")

        ux_path = f"{observed_path}.publicUxSmoke"
        ux = require_exact_keys(
            observed["publicUxSmoke"],
            ux_path,
            {
                "desktopRender",
                "mobileRender",
                "obviousBrokenNavigation",
                "notes",
                "sourceIds",
            },
        )
        for field in ("desktopRender", "mobileRender"):
            require_enum(
                ux[field],
                f"{ux_path}.{field}",
                {"observed", "blocked", "not_checked"},
            )
        require_enum(
            ux["obviousBrokenNavigation"],
            f"{ux_path}.obviousBrokenNavigation",
            {"yes", "no", "unknown"},
        )
        require_text(ux["notes"], f"{ux_path}.notes", allow_empty=True)
        require_text_list(ux["sourceIds"], f"{ux_path}.sourceIds")

        findings = audit["findings"]
        if not isinstance(findings, list):
            raise LedgerError(f"{audit_path}.findings must be an array.")
        finding_requires_hold = False
        for finding_index, raw_finding in enumerate(findings):
            finding_path = f"{audit_path}.findings[{finding_index}]"
            finding = require_exact_keys(
                raw_finding,
                finding_path,
                {"code", "severity", "statement", "sourceIds"},
            )
            finding_code = require_enum(
                finding["code"],
                f"{finding_path}.code",
                {
                    "unsupported_claim",
                    "missing_privacy_transparency",
                    "unavailable_source",
                    "public_risk",
                    "sensitive_domain",
                    "other",
                },
            )
            finding_severity = require_enum(
                finding["severity"],
                f"{finding_path}.severity",
                {"info", "caution", "high"},
            )
            require_text(finding["statement"], f"{finding_path}.statement")
            require_text_list(
                finding["sourceIds"],
                f"{finding_path}.sourceIds",
                min_items=1,
            )
            if finding_severity == "high" or finding_code in {
                "public_risk",
                "sensitive_domain",
            }:
                finding_requires_hold = True

        recommended_outcome = require_enum(
            audit["recommendedOutcome"],
            f"{audit_path}.recommendedOutcome",
            {"ready_for_human_review", "hold"},
        )
        hold_codes = require_text_list(audit["holdCodes"], f"{audit_path}.holdCodes")
        if finding_requires_hold and recommended_outcome != "hold":
            raise LedgerError(
                f"{audit_path}.recommendedOutcome must be hold for high-risk findings."
            )
        if recommended_outcome == "hold" and not hold_codes:
            raise LedgerError(
                f"{audit_path}.holdCodes must explain a held audit."
            )
        if recommended_outcome == "ready_for_human_review" and hold_codes:
            raise LedgerError(
                f"{audit_path}.holdCodes must be empty for a ready audit."
            )
        require_text(
            audit["proposedPublicSafeSummary"],
            f"{audit_path}.proposedPublicSafeSummary",
            allow_empty=True,
        )
        require_text_list(
            audit["outstandingQuestions"],
            f"{audit_path}.outstandingQuestions",
        )
        require_text_list(
            audit["limitations"],
            f"{audit_path}.limitations",
            min_items=1,
        )

    synthesis_path = f"{path}.synthesis"
    synthesis = require_exact_keys(
        result["synthesis"],
        synthesis_path,
        {
            "readyForHumanReviewLeadKeys",
            "holdLeadKeys",
            "coverageGaps",
            "humanDecisionsRequired",
        },
    )
    for field in (
        "readyForHumanReviewLeadKeys",
        "holdLeadKeys",
        "coverageGaps",
        "humanDecisionsRequired",
    ):
        require_text_list(synthesis[field], f"{synthesis_path}.{field}")


def validate_worker_role_result(role: str, value: Any, path: str) -> None:
    if role == "scout":
        validate_scout_result(value, path)
    elif role == "verifier":
        validate_verifier_result(value, path)
    elif role == "auditor":
        validate_auditor_result(value, path)
    else:
        raise LedgerError(f"{path} has unsupported worker role {role!r}.")


def keyed_worker_items(
    items: list[dict[str, Any]],
    path: str,
) -> dict[str, dict[str, Any]]:
    keyed: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(items):
        lead_key = require_text(item.get("leadKey"), f"{path}[{index}].leadKey")
        if lead_key in keyed:
            raise LedgerError(f"{path} contains duplicate leadKey {lead_key!r}.")
        keyed[lead_key] = item
    return keyed


def validate_worker_cross_role(
    envelopes: dict[str, dict[str, Any]],
) -> None:
    scout = envelopes["scout"]
    verifier = envelopes["verifier"]
    auditor = envelopes["auditor"]
    scout_leads = keyed_worker_items(
        scout["result"]["leads"],
        "workerResults[scout].result.leads",
    )
    verifier_entities = keyed_worker_items(
        verifier["result"]["entities"],
        "workerResults[verifier].result.entities",
    )
    unknown_verifier_leads = sorted(set(verifier_entities) - set(scout_leads))
    if unknown_verifier_leads:
        raise LedgerError(
            "Verifier entities were not returned by the scout: "
            + ", ".join(unknown_verifier_leads)
        )
    if verifier["status"] == "complete" and set(verifier_entities) != set(scout_leads):
        missing = sorted(set(scout_leads) - set(verifier_entities))
        raise LedgerError(
            "A complete verifier result must resolve every scout lead"
            + (": " + ", ".join(missing) if missing else ".")
        )

    eligible_entities = {
        lead_key: entity
        for lead_key, entity in verifier_entities.items()
        if entity["auditEligibility"] == "eligible"
    }
    audits = keyed_worker_items(
        auditor["result"]["audits"],
        "workerResults[auditor].result.audits",
    )
    unknown_audits = sorted(set(audits) - set(eligible_entities))
    if unknown_audits:
        raise LedgerError(
            "Auditor results were not approved as eligible by the verifier: "
            + ", ".join(unknown_audits)
        )
    if auditor["status"] == "complete" and set(audits) != set(eligible_entities):
        missing = sorted(set(eligible_entities) - set(audits))
        raise LedgerError(
            "A complete auditor result must cover every verifier-eligible lead"
            + (": " + ", ".join(missing) if missing else ".")
        )

    for lead_key, audit in audits.items():
        entity = eligible_entities[lead_key]
        canonical = entity["canonical"]
        audit_domain = canonical_domain(audit["canonicalOfficialUrl"])
        verifier_domain = canonical_domain(canonical["officialUrl"])
        if audit_domain != verifier_domain:
            raise LedgerError(
                f"Auditor lead {lead_key!r} does not use the verifier's canonical identity."
            )
        target_domains = {
            canonical_domain(target)
            for target in entity["auditTargets"]
        }
        if audit_domain not in target_domains:
            raise LedgerError(
                f"Auditor lead {lead_key!r} is outside the verifier-approved audit targets."
            )
        verifier_product_kind = entity["softwareFit"].get("productKind")
        auditor_product_kind = audit["observed"]["identityAndFit"]["productKind"]
        if verifier_product_kind != auditor_product_kind:
            raise LedgerError(
                f"Auditor lead {lead_key!r} conflicts with the verifier product kind."
            )

    synthesis = auditor["result"]["synthesis"]
    ready_keys_list = synthesis["readyForHumanReviewLeadKeys"]
    hold_keys_list = synthesis["holdLeadKeys"]
    if len(ready_keys_list) != len(set(ready_keys_list)):
        raise LedgerError("Auditor synthesis contains duplicate ready lead keys.")
    if len(hold_keys_list) != len(set(hold_keys_list)):
        raise LedgerError("Auditor synthesis contains duplicate hold lead keys.")
    ready_keys = set(ready_keys_list)
    hold_keys = set(hold_keys_list)
    if ready_keys & hold_keys:
        raise LedgerError("Auditor synthesis cannot mark the same lead ready and held.")
    observed_ready = {
        lead_key
        for lead_key, audit in audits.items()
        if audit["recommendedOutcome"] == "ready_for_human_review"
    }
    observed_holds = {
        lead_key
        for lead_key, audit in audits.items()
        if audit["recommendedOutcome"] == "hold"
    }
    if ready_keys != observed_ready or hold_keys != observed_holds:
        raise LedgerError(
            "Auditor synthesis does not exactly match the validated audit outcomes."
        )


def validate_normalized_candidate_links(
    raw_candidates: list[Any],
    envelopes: dict[str, dict[str, Any]],
    source_index: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    verifier_entities = keyed_worker_items(
        envelopes["verifier"]["result"]["entities"],
        "workerResults[verifier].result.entities",
    )
    audits = keyed_worker_items(
        envelopes["auditor"]["result"]["audits"],
        "workerResults[auditor].result.audits",
    )
    candidates_by_lead: dict[str, dict[str, Any]] = {}
    for index, raw_candidate in enumerate(raw_candidates):
        if not isinstance(raw_candidate, dict):
            raise LedgerError("Each ingest candidate must be a JSON object.")
        lead_key = require_text(
            raw_candidate.get("leadKey"),
            f"candidates[{index}].leadKey",
        )
        if lead_key in candidates_by_lead:
            raise LedgerError(
                f"Normalized candidates contain duplicate leadKey {lead_key!r}."
            )
        candidates_by_lead[lead_key] = raw_candidate
    if set(candidates_by_lead) != set(audits):
        missing_candidates = sorted(set(audits) - set(candidates_by_lead))
        unaudited_candidates = sorted(set(candidates_by_lead) - set(audits))
        details: list[str] = []
        if missing_candidates:
            details.append("missing normalized candidates: " + ", ".join(missing_candidates))
        if unaudited_candidates:
            details.append("candidates without auditor results: " + ", ".join(unaudited_candidates))
        raise LedgerError(
            "Normalized candidates must map one-to-one to auditor results ("
            + "; ".join(details)
            + ")."
        )

    worker_holds: dict[str, list[dict[str, Any]]] = {}
    for envelope in envelopes.values():
        for hold in envelope["holds"]:
            worker_holds.setdefault(str(hold["candidateKey"]), []).append(hold)

    hold_reasons: dict[str, list[str]] = {}
    for lead_key, candidate in candidates_by_lead.items():
        entity = verifier_entities[lead_key]
        audit = audits[lead_key]
        reasons: list[str] = []
        candidate_name = text(candidate.get("name"))
        candidate_url = text(candidate.get("websiteUrl") or candidate.get("website_url"))
        if not candidate_name or not candidate_url:
            continue
        canonical = entity["canonical"]
        known_names = {
            normalize_name(canonical["productName"]),
            *{
                normalize_name(alias)
                for alias in canonical["aliases"]
                if normalize_name(alias)
            },
        }
        if normalize_name(candidate_name) not in known_names:
            reasons.append("normalized name conflicts with verifier identity")
        candidate_company = optional_text(
            candidate,
            "companyName",
            "company_name",
        ) or ""
        if normalize_name(candidate_company) != normalize_name(canonical["companyName"]):
            reasons.append("normalized companyName conflicts with verifier identity")
        audited_operator = audit["observed"]["identityAndFit"]["operator"]
        if normalize_name(candidate_company) != normalize_name(audited_operator):
            reasons.append("normalized companyName conflicts with auditor identity")
        candidate_alias_keys = {
            normalize_name(alias)
            for alias in candidate_aliases(candidate, candidate_name)
            if normalize_name(alias)
        }
        canonical_alias_keys = {
            normalize_name(alias)
            for alias in canonical["aliases"]
            if normalize_name(alias)
        }
        if candidate_alias_keys != canonical_alias_keys:
            reasons.append("normalized aliases conflict with verifier identity")
        candidate_app_ids = set(candidate_app_store_ids(candidate))
        canonical_app_ids = {
            normalized_id
            for value in canonical["officialAppStoreIds"]
            if (normalized_id := normalize_app_store_id(value))
        }
        if candidate_app_ids != canonical_app_ids:
            reasons.append(
                "normalized officialAppStoreIds conflict with verifier identity"
            )
        try:
            if canonical_domain(candidate_url) != canonical_domain(audit["canonicalOfficialUrl"]):
                reasons.append("normalized website conflicts with audited canonical identity")
        except LedgerError:
            reasons.append("normalized website is not a valid audited identity")
        candidate_product_kind = text(
            candidate.get("productKind") or candidate.get("product_kind")
        )
        audited_product_kind = audit["observed"]["identityAndFit"]["productKind"]
        if candidate_product_kind != audited_product_kind:
            reasons.append("normalized productKind conflicts with audited software fit")
        normalized_tier = candidate_tier(candidate)
        if normalized_tier != entity["recommendedCaribbeanTier"]:
            reasons.append("normalized Caribbean tier conflicts with verifier evidence")
        candidate_source_ids = {
            source_id
            for source_id in candidate.get("sourceIds", [])
            if isinstance(source_id, str) and source_id
        } if isinstance(candidate.get("sourceIds"), list) else set()
        required_source_ids = collect_source_references(
            {
                "entity": entity,
                "audit": audit,
            },
            f"candidates[{lead_key}]",
        )
        if required_source_ids != candidate_source_ids:
            reasons.append(
                "normalized candidate sources do not exactly match verifier and auditor references"
            )
        matching_tier_source_ids = {
            source_id
            for evidence in entity["caribbeanEvidence"]
            if evidence["tier"] == entity["recommendedCaribbeanTier"]
            for source_id in evidence["sourceIds"]
        }
        matching_tier_source_urls = {
            canonicalize_url(source_index[source_id]["url"])
            for source_id in matching_tier_source_ids
        }
        evidence_a, evidence_b = extract_evidence(candidate)
        candidate_evidence_urls = {
            evidence["url"]
            for evidence in (evidence_a, evidence_b)
            if evidence
        }
        if (
            evidence_a is None
            or evidence_b is None
            or not candidate_evidence_urls.issubset(matching_tier_source_urls)
        ):
            reasons.append(
                "normalized evidence A and B must come from the matching verifier tier evidence"
            )
        recommendation = (
            optional_text(
                candidate,
                "recommendation",
                "reviewRecommendation",
                "review_recommendation",
            )
            or "hold"
        ).casefold()
        if recommendation != audit["recommendedOutcome"]:
            reasons.append("normalized recommendation conflicts with auditor outcome")
        for hold in worker_holds.get(lead_key, []):
            if hold["terminalForThisRun"] is True or hold["severity"] == "high":
                reasons.append(f"worker hold requires human review: {hold['code']}")
        if reasons:
            hold_reasons[lead_key] = list(dict.fromkeys(reasons))
    return hold_reasons


def validate_worker_results(
    raw_results: Any,
    run_id: str,
    provenance: dict[str, Any],
    source_index: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_results, list):
        raise LedgerError("Normalized ingest requires a workerResults array.")
    provenance_workers = provenance.get("workers")
    if not isinstance(provenance_workers, list):
        raise LedgerError("modelProvenance requires a workers array.")
    provenance_by_role = {
        str(worker.get("role")): worker
        for worker in provenance_workers
        if isinstance(worker, dict) and text(worker.get("role"))
    }
    observed_roles: set[str] = set()
    validated_envelopes: dict[str, dict[str, Any]] = {}
    observed_source_ids: set[str] = set()
    top_source_identity: dict[str, str] = {}
    for source_id, source in source_index.items():
        normalized = normalise_sources([source], {})
        if len(normalized) != 1:
            raise LedgerError(f"Top-level source {source_id!r} did not normalize uniquely.")
        top_source_identity[source_id] = stable_json(normalized[0])

    for index, result_envelope in enumerate(raw_results):
        path = f"workerResults[{index}]"
        result_envelope = require_exact_keys(
            result_envelope,
            path,
            {
                "contractVersion",
                "role",
                "runId",
                "worker",
                "status",
                "scope",
                "sideEffectAttestation",
                "sources",
                "holds",
                "errors",
                "result",
            },
        )
        safety_scan_value = {
            key: value
            for key, value in result_envelope.items()
            if key != "sideEffectAttestation"
        }
        _sanitized, redactions = sanitize_private_value(safety_scan_value, path)
        if redactions:
            raise LedgerError(
                f"{path} contains prohibited contact, credential, or browser data: "
                + ", ".join(sorted(redactions))
            )
        if result_envelope.get("contractVersion") != "1.0":
            raise LedgerError(f"{path} requires contractVersion '1.0'.")
        if optional_text(result_envelope, "runId", "run_id") != run_id:
            raise LedgerError(f"{path} does not use the active normalized runId.")
        role = optional_text(result_envelope, "role")
        if not role or role not in WORKER_REQUIREMENTS:
            raise LedgerError(f"{path} has unsupported or missing role {role!r}.")
        if role in observed_roles:
            raise LedgerError(f"workerResults contains duplicate role {role!r}.")
        expected = provenance_by_role.get(role)
        if not expected:
            raise LedgerError(f"{path} has no matching modelProvenance worker.")
        worker = require_exact_keys(
            result_envelope.get("worker"),
            f"{path}.worker",
            {"agent", "model", "reasoningEffort", "modelFallback"},
        )
        for field in ("agent", "model", "reasoningEffort", "modelFallback"):
            if worker.get(field) != expected.get(field):
                raise LedgerError(
                    f"{path}.worker.{field} does not match modelProvenance."
                )
        status = optional_text(result_envelope, "status")
        if status != expected.get("status"):
            raise LedgerError(f"{path}.status does not match modelProvenance.")
        validate_worker_scope(result_envelope.get("scope"), f"{path}.scope")
        attestation = result_envelope.get("sideEffectAttestation")
        if not isinstance(attestation, dict) or set(attestation) != WORKER_ATTESTATION_FIELDS:
            raise LedgerError(
                f"{path}.sideEffectAttestation must contain the exact worker field set."
            )
        non_false = sorted(
            field
            for field in WORKER_ATTESTATION_FIELDS
            if attestation.get(field) is not False
        )
        if non_false:
            raise LedgerError(
                f"{path}.sideEffectAttestation must be all false: "
                + ", ".join(non_false)
            )
        raw_holds = result_envelope.get("holds")
        if not isinstance(raw_holds, list):
            raise LedgerError(f"{path}.holds must be an array.")
        for hold_index, raw_hold in enumerate(raw_holds):
            validate_worker_hold(raw_hold, f"{path}.holds[{hold_index}]")
        if status == "complete" and any(
            hold.get("candidateKey") == run_id
            and (
                hold.get("terminalForThisRun") is True
                or hold.get("severity") == "high"
            )
            for hold in raw_holds
        ):
            raise LedgerError(
                f"{path}.status cannot be complete with a blocking run-level hold."
            )
        raw_errors = result_envelope.get("errors")
        if not isinstance(raw_errors, list):
            raise LedgerError(f"{path}.errors must be an array.")
        require_text_list(raw_errors, f"{path}.errors")
        if status == "complete" and raw_errors:
            raise LedgerError(
                f"{path}.status cannot be complete while worker errors are present."
            )
        role_result = result_envelope.get("result")
        if not isinstance(role_result, dict):
            raise LedgerError(f"{path}.result must be a JSON object.")
        validate_worker_role_result(role, role_result, f"{path}.result")

        raw_sources = result_envelope.get("sources")
        if not isinstance(raw_sources, list):
            raise LedgerError(f"{path}.sources must be an array.")
        for source_index_position, raw_source in enumerate(raw_sources):
            validate_worker_source(
                raw_source,
                f"{path}.sources[{source_index_position}]",
            )
        normalized_sources = normalise_sources(raw_sources, {})
        worker_source_ids = {source["sourceId"] for source in normalized_sources}
        if len(worker_source_ids) != len(normalized_sources):
            raise LedgerError(f"{path}.sources contains duplicate source IDs.")
        for source in normalized_sources:
            source_id = source["sourceId"]
            expected_identity = top_source_identity.get(source_id)
            if not expected_identity:
                raise LedgerError(
                    f"{path}.sources references sourceId {source_id!r} "
                    "that is absent from the normalized source matrix."
                )
            if stable_json(source) != expected_identity:
                raise LedgerError(
                    f"{path}.sources conflicts with normalized sourceId {source_id!r}."
                )
        referenced_ids = collect_source_references(
            {
                "scope": result_envelope["scope"],
                "holds": result_envelope["holds"],
                "result": role_result,
            },
            path,
        )
        unresolved = sorted(referenced_ids - worker_source_ids)
        if unresolved:
            raise LedgerError(
                f"{path} has unresolved source references: " + ", ".join(unresolved)
            )
        observed_source_ids.update(worker_source_ids)
        observed_roles.add(role)
        validated_envelopes[role] = result_envelope

    missing_roles = sorted(set(WORKER_REQUIREMENTS) - observed_roles)
    if missing_roles:
        raise LedgerError(
            "workerResults is missing required roles: " + ", ".join(missing_roles)
        )
    missing_sources = sorted(set(source_index) - observed_source_ids)
    if missing_sources:
        raise LedgerError(
            "Normalized sources are not present in any validated worker result: "
            + ", ".join(missing_sources)
        )
    validate_worker_cross_role(validated_envelopes)
    return validated_envelopes


class ReviewLedger:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.database_path = self.root / "registry.sqlite3"
        self.events_path = self.root / "events.jsonl"
        self.snapshots_path = self.root / "snapshots"
        self.queue_path = self.root / "review-packets"
        self.publication_receipts_path = self.root / "publication-receipts"
        self.ledger_lock_path = self.root / "ledger.lock"
        self.lock_path = self.root / "run.lock"

    @contextmanager
    def ledger_lock(self) -> Iterable[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        handle = self.ledger_lock_path.open("a+", encoding="utf-8")
        os.chmod(self.ledger_lock_path, 0o600)
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise LedgerError(
                    "Another process is operating on the private review ledger."
                ) from error
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    def initialize(self) -> bool:
        created = not self.database_path.exists()
        migrated_candidate_ids: list[str] = []
        self.root.mkdir(parents=True, exist_ok=True)
        self.snapshots_path.mkdir(parents=True, exist_ok=True)
        self.queue_path.mkdir(parents=True, exist_ok=True)
        self.publication_receipts_path.mkdir(parents=True, exist_ok=True)
        self.events_path.touch(exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS candidates (
                    candidate_id TEXT PRIMARY KEY,
                    canonical_domain TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    name TEXT NOT NULL,
                    website_url TEXT NOT NULL,
                    company_name TEXT,
                    public_payload_json TEXT NOT NULL,
                    private_payload_json TEXT NOT NULL DEFAULT '{}',
                    automated_review_json TEXT NOT NULL DEFAULT '{}',
                    human_decision_json TEXT,
                    recommendation TEXT NOT NULL,
                    confidence REAL,
                    evidence_a_json TEXT,
                    evidence_b_json TEXT,
                    caribbean_evidence_tier TEXT,
                    sources_json TEXT NOT NULL DEFAULT '[]',
                    app_store_ids_json TEXT NOT NULL DEFAULT '[]',
                    aliases_json TEXT NOT NULL DEFAULT '[]',
                    run_id TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL,
                    hold_reasons_json TEXT NOT NULL,
                    duplicate_kind TEXT,
                    catalog_match_id TEXT,
                    source_digest TEXT NOT NULL,
                    synced_catalog_id TEXT,
                    synced_public_record_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    provenance_json TEXT NOT NULL,
                    coverage_json TEXT NOT NULL,
                    source_failures_json TEXT NOT NULL,
                    attestation_json TEXT NOT NULL DEFAULT '{}',
                    worker_contracts_validated INTEGER NOT NULL DEFAULT 0,
                    lifecycle_stage TEXT NOT NULL DEFAULT 'started',
                    catalog_clean_at_start INTEGER NOT NULL DEFAULT 0,
                    catalog_sha256_at_start TEXT NOT NULL DEFAULT '',
                    publication_mode TEXT NOT NULL DEFAULT 'disabled',
                    publication_status TEXT NOT NULL DEFAULT 'disabled',
                    publication_attempt_id TEXT,
                    repository_preflight_json TEXT NOT NULL DEFAULT '{}',
                    finished_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS publication_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    plan_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    prepared_at TEXT NOT NULL,
                    recorded_at TEXT,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS observations (
                    event_key TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    source_digest TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(candidate_id) REFERENCES candidates(candidate_id)
                );
                CREATE INDEX IF NOT EXISTS candidate_domain_index ON candidates(canonical_domain);
                CREATE INDEX IF NOT EXISTS candidate_name_index ON candidates(normalized_name);
                CREATE INDEX IF NOT EXISTS candidate_state_index ON candidates(state);
                CREATE INDEX IF NOT EXISTS observation_run_index ON observations(run_id);
                CREATE INDEX IF NOT EXISTS publication_attempt_run_index
                    ON publication_attempts(run_id);
                """
            )
            self.ensure_column(connection, "candidates", "automated_review_json", "TEXT NOT NULL DEFAULT '{}'")
            self.ensure_column(connection, "candidates", "private_payload_json", "TEXT NOT NULL DEFAULT '{}'")
            self.ensure_column(connection, "candidates", "human_decision_json", "TEXT")
            self.ensure_column(connection, "candidates", "caribbean_evidence_tier", "TEXT")
            self.ensure_column(connection, "candidates", "sources_json", "TEXT NOT NULL DEFAULT '[]'")
            self.ensure_column(connection, "candidates", "app_store_ids_json", "TEXT NOT NULL DEFAULT '[]'")
            self.ensure_column(connection, "candidates", "aliases_json", "TEXT NOT NULL DEFAULT '[]'")
            self.ensure_column(connection, "candidates", "run_id", "TEXT NOT NULL DEFAULT ''")
            self.ensure_column(
                connection,
                "candidates",
                "synced_public_record_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            self.ensure_column(connection, "runs", "catalog_clean_at_start", "INTEGER NOT NULL DEFAULT 0")
            self.ensure_column(connection, "runs", "catalog_sha256_at_start", "TEXT NOT NULL DEFAULT ''")
            self.ensure_column(
                connection,
                "runs",
                "publication_mode",
                "TEXT NOT NULL DEFAULT 'disabled'",
            )
            self.ensure_column(
                connection,
                "runs",
                "publication_status",
                "TEXT NOT NULL DEFAULT 'disabled'",
            )
            self.ensure_column(connection, "runs", "publication_attempt_id", "TEXT")
            self.ensure_column(
                connection,
                "runs",
                "repository_preflight_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            self.ensure_column(connection, "runs", "finished_at", "TEXT")
            self.ensure_column(connection, "runs", "attestation_json", "TEXT NOT NULL DEFAULT '{}'")
            self.ensure_column(
                connection,
                "runs",
                "worker_contracts_validated",
                "INTEGER NOT NULL DEFAULT 0",
            )
            run_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(runs)")
            }
            lifecycle_stage_was_missing = "lifecycle_stage" not in run_columns
            self.ensure_column(
                connection,
                "runs",
                "lifecycle_stage",
                "TEXT NOT NULL DEFAULT 'started'",
            )
            if lifecycle_stage_was_missing:
                connection.execute(
                    """
                    UPDATE runs
                    SET lifecycle_stage = CASE
                        WHEN finished_at IS NOT NULL THEN 'finished'
                        WHEN worker_contracts_validated = 1 THEN 'ingested'
                        ELSE 'started'
                    END
                    """
                )
            else:
                connection.execute(
                    """
                    UPDATE runs
                    SET lifecycle_stage = CASE
                        WHEN finished_at IS NOT NULL THEN 'finished'
                        WHEN worker_contracts_validated = 1 THEN 'ingested'
                        ELSE 'started'
                    END
                    WHERE lifecycle_stage NOT IN (
                        'started', 'ingested', 'packeted', 'validated', 'finished'
                    )
                    """
                )
            connection.execute(
                """
                UPDATE runs
                SET finished_at = created_at
                WHERE finished_at IS NULL AND catalog_sha256_at_start = ''
                """
            )
            connection.execute(
                """
                UPDATE runs
                SET publication_mode = 'disabled',
                    publication_status = 'disabled',
                    repository_preflight_json = '{}'
                WHERE publication_mode IS NULL
                   OR publication_mode NOT IN ('disabled', 'publish_unlisted')
                """
            )
            for row in connection.execute(
                """
                SELECT candidate_id, run_id, private_payload_json, automated_review_json,
                       evidence_a_json, evidence_b_json, sources_json,
                       app_store_ids_json, aliases_json
                FROM candidates
                """
            ).fetchall():
                try:
                    prior_private = json.loads(row["private_payload_json"] or "{}")
                    automated_review = json.loads(row["automated_review_json"] or "{}")
                    evidence_a = json.loads(row["evidence_a_json"]) if row["evidence_a_json"] else None
                    evidence_b = json.loads(row["evidence_b_json"]) if row["evidence_b_json"] else None
                    sources = json.loads(row["sources_json"] or "[]")
                    app_store_ids = json.loads(row["app_store_ids_json"] or "[]")
                    aliases = json.loads(row["aliases_json"] or "[]")
                except json.JSONDecodeError as error:
                    raise LedgerError(
                        f"Private candidate {row['candidate_id']} contains invalid JSON."
                    ) from error
                if not isinstance(prior_private, dict):
                    prior_private = {}
                if not isinstance(automated_review, dict):
                    automated_review = {}
                if not isinstance(sources, list):
                    sources = []
                prior_private_json = stable_json(prior_private)
                prior_automated_json = stable_json(automated_review)

                compact_private, redacted_fields = compact_private_payload(
                    prior_private,
                    evidence_a,
                    evidence_b,
                    sources,
                )
                if isinstance(app_store_ids, list) and app_store_ids:
                    compact_private["officialAppStoreIds"] = [
                        str(value) for value in app_store_ids if text(value)
                    ]
                if isinstance(aliases, list) and aliases:
                    compact_private["aliases"] = [
                        str(value) for value in aliases if text(value)
                    ]
                automated_review.pop("candidate", None)
                prior_redactions = automated_review.pop("redactedInputFields", [])
                if not isinstance(prior_redactions, list):
                    prior_redactions = []
                prior_redactions = [
                    str(item)
                    for item in prior_redactions
                    if isinstance(item, str)
                    and not item.endswith("runId:contact-in-text")
                ]
                automated_review["runId"] = str(row["run_id"])
                sanitized_automated, automated_redactions = sanitize_private_value(
                    automated_review,
                    "automatedReview",
                )
                if not isinstance(sanitized_automated, dict):
                    sanitized_automated = {}
                all_redactions = sorted(
                    set(prior_redactions + redacted_fields + automated_redactions)
                )
                if all_redactions:
                    sanitized_automated["redactedInputFields"] = all_redactions

                compact_json = stable_json(compact_private)
                automated_json = stable_json(sanitized_automated)
                if (
                    compact_json != prior_private_json
                    or automated_json != prior_automated_json
                ):
                    connection.execute(
                        """
                        UPDATE candidates
                        SET private_payload_json = ?, automated_review_json = ?, updated_at = ?
                        WHERE candidate_id = ?
                        """,
                        (compact_json, automated_json, utc_now(), row["candidate_id"]),
                    )
                    migrated_candidate_ids.append(str(row["candidate_id"]))
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
        if created:
            self.append_event({"event": "ledger_initialized", "schemaVersion": SCHEMA_VERSION})
        if migrated_candidate_ids:
            self.append_event(
                {
                    "event": "private_payloads_compacted",
                    "eventKey": f"private_payloads_compacted:v{SCHEMA_VERSION}",
                    "schemaVersion": SCHEMA_VERSION,
                    "candidateIds": sorted(migrated_candidate_ids),
                }
            )
        return created

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def read_lock(self) -> dict[str, Any] | None:
        if not self.lock_path.exists():
            return None
        try:
            payload = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise LedgerError(
                f"Private run lock is malformed: {self.lock_path}. Inspect it manually before continuing."
            ) from error
        if not isinstance(payload, dict) or not text(payload.get("runId")):
            raise LedgerError(
                f"Private run lock is invalid: {self.lock_path}. Inspect it manually before continuing."
            )
        return payload

    def require_active_run(self, run_id: str) -> sqlite3.Row:
        lock = self.read_lock()
        if not lock:
            raise LedgerError(
                f"Run {run_id!r} is not active. Call begin-run before ingest or sync."
            )
        if lock["runId"] != run_id:
            raise LedgerError(
                f"Run {lock['runId']!r} holds the private review lock; refusing run {run_id!r}."
            )
        with self.connect() as connection:
            run = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if not run or run["finished_at"]:
            raise LedgerError(f"Run {run_id!r} has no active ledger record.")
        return run

    @contextmanager
    def command_lock(self, run_id: str) -> Iterable[None]:
        self.require_active_run(run_id)
        handle = self.lock_path.open("r+", encoding="utf-8")
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise LedgerError(
                    f"Another process is already operating on active run {run_id!r}."
                ) from error
            self.require_active_run(run_id)
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    def begin_run(
        self,
        catalog: Path,
        run_id: str,
        allow_dirty_catalog: bool,
        publish_unlisted: bool = False,
    ) -> dict[str, Any]:
        cleaned_run_id = text(run_id)
        if not cleaned_run_id:
            raise LedgerError("begin-run requires a non-empty run ID.")
        if self.read_lock():
            lock = self.read_lock()
            raise LedgerError(
                f"Run {lock['runId']!r} already holds the private review lock. "
                "Finish that run before starting another."
            )
        with self.connect() as connection:
            if connection.execute("SELECT 1 FROM runs WHERE run_id = ?", (cleaned_run_id,)).fetchone():
                raise LedgerError(f"Run ID {cleaned_run_id!r} already exists; use a unique run ID.")

        catalog_bytes = catalog.read_bytes()
        read_json(catalog)
        catalog_digest = hashlib.sha256(catalog_bytes).hexdigest()
        clean_at_start = catalog_is_clean(catalog, allow_dirty_catalog)
        publication_mode = (
            PUBLICATION_MODE_UNLISTED
            if publish_unlisted
            else PUBLICATION_MODE_DISABLED
        )
        preflight = repository_preflight(catalog) if publish_unlisted else {}
        publication_status = "pending" if publish_unlisted else "disabled"
        started_at = utc_now()
        lock_payload = {
            "runId": cleaned_run_id,
            "startedAt": started_at,
            "catalogCleanAtStart": clean_at_start,
            "catalogSha256AtStart": catalog_digest,
            "publicationMode": publication_mode,
        }
        descriptor: int | None = None
        lock_created = False
        try:
            descriptor = os.open(self.lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            lock_created = True
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            os.write(descriptor, (stable_json(lock_payload) + "\n").encode("utf-8"))
            os.fsync(descriptor)
            with self.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO runs (
                        run_id, provenance_json, coverage_json, source_failures_json,
                        attestation_json, worker_contracts_validated,
                        catalog_clean_at_start, catalog_sha256_at_start,
                        publication_mode, publication_status, repository_preflight_json,
                        finished_at, created_at
                    ) VALUES (?, '{}', '{}', '[]', '{}', 0, ?, ?, ?, ?, ?, NULL, ?)
                    """,
                    (
                        cleaned_run_id,
                        int(clean_at_start),
                        catalog_digest,
                        publication_mode,
                        publication_status,
                        stable_json(preflight),
                        started_at,
                    ),
                )
            snapshot = self.snapshot(catalog)
            self.append_event(
                {
                    "event": "run_started",
                    "eventKey": f"run_started:{cleaned_run_id}",
                    **lock_payload,
                }
            )
        except FileExistsError as error:
            raise LedgerError("Another private review run acquired the lock first.") from error
        except Exception:
            with self.connect() as connection:
                connection.execute("DELETE FROM runs WHERE run_id = ?", (cleaned_run_id,))
            if lock_created:
                self.lock_path.unlink(missing_ok=True)
            raise
        finally:
            if descriptor is not None:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)
        return {
            **lock_payload,
            "lock": str(self.lock_path),
            "snapshot": snapshot["snapshot"],
            "publicationPreflight": self.publication_preflight_summary(preflight),
        }

    def finish_run(self, catalog: Path, run_id: str) -> dict[str, Any]:
        run = self.require_active_run(run_id)
        if not bool(run["worker_contracts_validated"]):
            raise LedgerError(
                f"Run {run_id!r} has not completed a validated ingest; "
                "the private lock remains in place."
            )
        if run["lifecycle_stage"] != "validated":
            raise LedgerError(
                f"Run {run_id!r} is at lifecycle stage {run['lifecycle_stage']!r}; "
                "generate its packet and complete successful validation before finishing."
            )
        if run["publication_mode"] == PUBLICATION_MODE_UNLISTED:
            attempt_id = text(run["publication_attempt_id"])
            if not attempt_id:
                raise LedgerError(
                    f"Run {run_id!r} enabled guarded publication but has no resolved "
                    "publication attempt; call prepare-publication before finishing."
                )
            with self.connect() as connection:
                publication_attempt = connection.execute(
                    """
                    SELECT status, plan_json FROM publication_attempts
                    WHERE run_id = ? AND attempt_id = ?
                    """,
                    (run_id, attempt_id),
                ).fetchone()
            if (
                not publication_attempt
                or publication_attempt["status"] not in PUBLICATION_PREPARE_STATUSES
            ):
                raise LedgerError(
                    f"Run {run_id!r} has not resolved its guarded publication gate; "
                    "the private lock remains in place."
                )
            if publication_attempt["status"] == "prepared":
                try:
                    plan = json.loads(publication_attempt["plan_json"] or "{}")
                    start_preflight = json.loads(
                        run["repository_preflight_json"] or "{}"
                    )
                except json.JSONDecodeError as error:
                    raise LedgerError(
                        f"Run {run_id!r} has malformed publication proof data; "
                        "the private lock remains in place."
                    ) from error
                current_catalog_digest = hashlib.sha256(catalog.read_bytes()).hexdigest()
                if current_catalog_digest != plan.get("catalogSha256Prepared"):
                    raise LedgerError(
                        f"Run {run_id!r} catalog changed after publication preparation; "
                        "the private lock remains in place."
                    )
                current_preflight = repository_preflight(catalog)
                expected_catalog_path = str(
                    start_preflight.get("catalogPath") or "data/products.json"
                )
                unresolved_preflight_errors = [
                    error
                    for error in current_preflight.get("errors") or []
                    if error
                    != "publication requires a clean whole worktree at run start"
                ]
                repository_still_prepared = bool(
                    not unresolved_preflight_errors
                    and current_preflight.get("repositoryRoot")
                    == start_preflight.get("repositoryRoot")
                    and current_preflight.get("catalogPath") == expected_catalog_path
                    and current_preflight.get("branch") == "main"
                    and current_preflight.get("headSha")
                    == start_preflight.get("headSha")
                    and current_preflight.get("upstreamRef") == "origin/main"
                    and current_preflight.get("upstreamSha")
                    == start_preflight.get("upstreamSha")
                    and current_preflight.get("aligned")
                    and not current_preflight.get("stagedPaths")
                    and not current_preflight.get("untrackedPaths")
                    and current_preflight.get("unstagedPaths")
                    == [expected_catalog_path]
                )
                if not repository_still_prepared:
                    raise LedgerError(
                        f"Run {run_id!r} repository changed after publication preparation; "
                        "the private lock remains in place."
                    )
        queue_file, queue_json = self.packet_paths(run_id)
        if not queue_file.is_file() or not queue_json.is_file():
            raise LedgerError(
                f"Run {run_id!r} is missing its final private review packet; "
                "the private lock remains in place."
            )
        try:
            packet = json.loads(queue_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise LedgerError(
                f"Run {run_id!r} has a malformed private JSON packet."
            ) from error
        if (
            not isinstance(packet, dict)
            or packet.get("runId") != run_id
            or packet.get("workerContractsValidated") is not True
        ):
            raise LedgerError(
                f"Run {run_id!r} has a packet that does not match its validated ingest."
            )
        packet_publication = packet.get("publication")
        if (
            not isinstance(packet_publication, dict)
            or packet_publication.get("mode") != run["publication_mode"]
            or packet_publication.get("status") != run["publication_status"]
            or packet_publication.get("currentAttemptId")
            != run["publication_attempt_id"]
        ):
            raise LedgerError(
                f"Run {run_id!r} has a stale publication summary in its private packet; "
                "replay the current publication command before finishing."
            )
        validation = self.validate(catalog)
        if not validation["valid"]:
            raise LedgerError(
                f"Run {run_id!r} no longer passes final ledger/catalog validation: "
                + "; ".join(validation["issues"])
            )
        finished_at = utc_now()
        self.append_event(
            {
                "event": "run_finished",
                "eventKey": f"run_finished:{run_id}",
                "runId": run_id,
                "finishedAt": finished_at,
            }
        )
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE runs
                SET lifecycle_stage = 'finished', finished_at = ?
                WHERE run_id = ?
                """,
                (finished_at, run_id),
            )
        self.lock_path.unlink()
        return {
            "runId": run_id,
            "finishedAt": finished_at,
            "catalogCleanAtStart": bool(run["catalog_clean_at_start"]),
            "lifecycleStage": "finished",
            "lockReleased": True,
            "publicationStatus": run["publication_status"],
            "publicationAttemptId": run["publication_attempt_id"],
        }

    @staticmethod
    def ensure_column(connection: sqlite3.Connection, table: str, name: str, definition: str) -> None:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if name not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def append_event(self, event: dict[str, Any]) -> None:
        event_key = str(event.get("eventKey") or sha256_text(stable_json(event)))
        known_keys: set[str] = set()
        if self.events_path.exists():
            for line in self.events_path.read_text(encoding="utf-8").splitlines():
                try:
                    existing = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(existing, dict) and isinstance(existing.get("eventKey"), str):
                    known_keys.add(existing["eventKey"])
        if event_key in known_keys:
            return
        payload = {"at": utc_now(), "eventKey": event_key, **event}
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(stable_json(payload))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def packet_paths(self, run_id: str) -> tuple[Path, Path]:
        safe_run_id = re.sub(r"[^A-Za-z0-9._-]+", "-", run_id).strip("-") or "run"
        return (
            self.queue_path / f"review-{safe_run_id}.md",
            self.queue_path / f"review-{safe_run_id}.json",
        )

    def snapshot(self, catalog: Path) -> dict[str, Any]:
        raw_catalog = catalog.read_bytes()
        read_json(catalog)
        digest = hashlib.sha256(raw_catalog).hexdigest()
        snapshot_path = self.snapshots_path / f"products-{digest}.json"
        created = not snapshot_path.exists()
        if created:
            atomic_write_bytes(snapshot_path, raw_catalog)
            self.append_event(
                {
                    "event": "catalog_snapshot_created",
                    "eventKey": f"catalog_snapshot_created:{digest}",
                    "catalogSha256": digest,
                    "snapshot": str(snapshot_path.relative_to(self.root)),
                }
            )
        return {
            "created": created,
            "catalogSha256": digest,
            "snapshot": str(snapshot_path),
        }

    @staticmethod
    def publication_preflight_summary(preflight: dict[str, Any]) -> dict[str, Any]:
        if not preflight:
            return {}
        return {
            "capturedAt": preflight.get("capturedAt"),
            "repositoryDetected": bool(preflight.get("repositoryDetected")),
            "catalogPath": preflight.get("catalogPath"),
            "catalogTracked": bool(preflight.get("catalogTracked")),
            "branch": preflight.get("branch"),
            "headSha": preflight.get("headSha"),
            "upstreamRef": preflight.get("upstreamRef"),
            "upstreamSha": preflight.get("upstreamSha"),
            "ahead": preflight.get("ahead"),
            "behind": preflight.get("behind"),
            "clean": bool(preflight.get("clean")),
            "aligned": bool(preflight.get("aligned")),
            "eligible": bool(preflight.get("eligible")),
            "stagedPathCount": len(preflight.get("stagedPaths") or []),
            "unstagedPathCount": len(preflight.get("unstagedPaths") or []),
            "untrackedPathCount": len(preflight.get("untrackedPaths") or []),
            "errors": list(preflight.get("errors") or []),
        }

    @staticmethod
    def publication_attempt_id(run_id: str, attempt_id: str | None) -> str:
        cleaned = text(attempt_id) or f"{run_id}-publication"
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", cleaned):
            raise LedgerError(
                "Publication attempt IDs must be 1-128 letters, digits, dots, underscores, or hyphens."
            )
        return cleaned

    def publication_receipt_path(self, run_id: str, attempt_id: str) -> Path:
        safe_run = re.sub(r"[^A-Za-z0-9._-]+", "-", run_id).strip("-") or "run"
        safe_attempt = re.sub(r"[^A-Za-z0-9._-]+", "-", attempt_id).strip("-") or "attempt"
        return self.publication_receipts_path / f"{safe_run}--{safe_attempt}.json"

    def write_publication_receipt(
        self,
        run_id: str,
        attempt_id: str,
        plan: dict[str, Any],
        result: dict[str, Any],
    ) -> Path:
        receipt_path = self.publication_receipt_path(run_id, attempt_id)
        atomic_write_json(
            receipt_path,
            {
                "schemaVersion": 1,
                "runId": run_id,
                "attemptId": attempt_id,
                "plan": plan,
                "result": result,
            },
        )
        os.chmod(receipt_path, 0o600)
        return receipt_path

    def publication_summary(self, run_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            run = connection.execute(
                """
                SELECT publication_mode, publication_status, publication_attempt_id,
                       repository_preflight_json
                FROM runs WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if not run:
                raise LedgerError(f"Unknown private review run: {run_id}")
            attempts = connection.execute(
                """
                SELECT attempt_id, status, plan_json, result_json, prepared_at, recorded_at
                FROM publication_attempts
                WHERE run_id = ?
                ORDER BY prepared_at ASC, attempt_id ASC
                """,
                (run_id,),
            ).fetchall()
        try:
            preflight = json.loads(run["repository_preflight_json"] or "{}")
        except json.JSONDecodeError:
            preflight = {}
        attempt_summaries: list[dict[str, Any]] = []
        for attempt in attempts:
            try:
                plan = json.loads(attempt["plan_json"] or "{}")
                result = json.loads(attempt["result_json"] or "{}")
            except json.JSONDecodeError:
                plan, result = {}, {}
            attempt_summaries.append(
                {
                    "attemptId": attempt["attempt_id"],
                    "status": attempt["status"],
                    "preparedAt": attempt["prepared_at"],
                    "recordedAt": attempt["recorded_at"],
                    "publicationAllowed": bool(plan.get("publicationAllowed")),
                    "additionsCount": int(plan.get("additionsCount") or 0),
                    "addedIds": list(plan.get("addedIds") or []),
                    "blockingReasons": list(plan.get("blockingReasons") or []),
                    "commitSha": result.get("commitSha"),
                    "deploymentCommitSha": result.get("deploymentCommitSha"),
                    "deploymentUrl": result.get("deploymentUrl"),
                    "liveCatalogSha256": result.get("liveCatalogSha256"),
                    "failureCode": result.get("failureCode"),
                    "liveVerified": bool(result.get("liveVerified")),
                }
            )
        return {
            "mode": run["publication_mode"],
            "status": run["publication_status"],
            "currentAttemptId": run["publication_attempt_id"],
            "preflight": self.publication_preflight_summary(
                preflight if isinstance(preflight, dict) else {}
            ),
            "attempts": attempt_summaries,
        }

    def prepare_publication(
        self,
        catalog: Path,
        run_id: str,
        attempt_id: str | None = None,
    ) -> dict[str, Any]:
        run = self.require_active_run(run_id)
        if run["publication_mode"] != PUBLICATION_MODE_UNLISTED:
            raise LedgerError(
                f"Run {run_id!r} did not enable guarded publication at begin-run."
            )
        if run["lifecycle_stage"] != "validated":
            raise LedgerError(
                f"Run {run_id!r} is at lifecycle stage {run['lifecycle_stage']!r}; "
                "prepare-publication requires successful packet and catalog validation."
            )
        cleaned_attempt_id = self.publication_attempt_id(run_id, attempt_id)
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM publication_attempts WHERE attempt_id = ?",
                (cleaned_attempt_id,),
            ).fetchone()
        if existing:
            if existing["run_id"] != run_id:
                raise LedgerError(
                    f"Publication attempt ID {cleaned_attempt_id!r} belongs to another run."
                )
            try:
                plan = json.loads(existing["plan_json"])
                result = json.loads(existing["result_json"] or "{}")
            except json.JSONDecodeError as error:
                raise LedgerError(
                    f"Publication attempt {cleaned_attempt_id!r} contains malformed private JSON."
                ) from error
            receipt_path = self.write_publication_receipt(
                run_id,
                cleaned_attempt_id,
                plan,
                result,
            )
            self.append_event(
                {
                    "event": "publication_prepared",
                    "eventKey": (
                        f"publication_prepared:{run_id}:{cleaned_attempt_id}"
                    ),
                    "runId": run_id,
                    "attemptId": cleaned_attempt_id,
                    "status": existing["status"],
                    "publicationAllowed": bool(plan.get("publicationAllowed")),
                    "addedIds": list(plan.get("addedIds") or []),
                    "blockingReasons": list(plan.get("blockingReasons") or []),
                }
            )
            self.queue(run_id)
            return {
                **plan,
                "idempotentReplay": True,
                "receipt": str(receipt_path),
            }

        blocking_reasons: list[str] = []
        try:
            start_preflight = json.loads(run["repository_preflight_json"] or "{}")
        except json.JSONDecodeError:
            start_preflight = {}
            blocking_reasons.append("run-start repository preflight is malformed")
        if not isinstance(start_preflight, dict):
            start_preflight = {}
            blocking_reasons.append("run-start repository preflight is invalid")
        if not bool(start_preflight.get("eligible")):
            blocking_reasons.append(
                "run-start repository preflight was not clean, main, tracked, and upstream-aligned"
            )

        snapshot_path = self.snapshots_path / f"products-{run['catalog_sha256_at_start']}.json"
        try:
            snapshot_bytes = snapshot_path.read_bytes()
        except FileNotFoundError:
            snapshot_bytes = b""
            blocking_reasons.append("run-start catalog snapshot is missing")
        if snapshot_bytes and hashlib.sha256(snapshot_bytes).hexdigest() != run["catalog_sha256_at_start"]:
            blocking_reasons.append("run-start catalog snapshot digest does not match the run")

        start_payload: dict[str, Any] = {}
        start_products: list[dict[str, Any]] = []
        if snapshot_bytes:
            try:
                parsed_start = json.loads(snapshot_bytes)
                if (
                    isinstance(parsed_start, dict)
                    and isinstance(parsed_start.get("products"), list)
                    and all(isinstance(item, dict) for item in parsed_start["products"])
                ):
                    start_payload = parsed_start
                    start_products = parsed_start["products"]
                else:
                    blocking_reasons.append("run-start catalog snapshot has an invalid shape")
            except json.JSONDecodeError:
                blocking_reasons.append("run-start catalog snapshot is invalid JSON")

        try:
            current_payload, current_products = load_catalog(catalog)
        except LedgerError as error:
            current_payload, current_products = {}, []
            blocking_reasons.append(str(error))

        if start_payload and current_payload:
            start_metadata = {key: value for key, value in start_payload.items() if key != "products"}
            current_metadata = {key: value for key, value in current_payload.items() if key != "products"}
            if current_metadata != start_metadata:
                blocking_reasons.append("catalog top-level metadata changed after run start")
            if len(current_products) < len(start_products):
                blocking_reasons.append("catalog records were deleted after run start")
            elif current_products[: len(start_products)] != start_products:
                blocking_reasons.append(
                    "run-start catalog records were modified or reordered"
                )

        additions = (
            current_products[len(start_products) :]
            if start_payload
            and len(current_products) >= len(start_products)
            and current_products[: len(start_products)] == start_products
            else []
        )
        added_ids = [text(record.get("id")) for record in additions]
        if any(identifier is None for identifier in added_ids):
            blocking_reasons.append("every appended catalog record requires a public ID")
        if len({identifier for identifier in added_ids if identifier}) != len(added_ids):
            blocking_reasons.append("appended catalog record IDs must be unique")

        with self.connect() as connection:
            owned_rows = connection.execute(
                """
                SELECT candidate_id, synced_catalog_id, synced_public_record_json
                FROM candidates
                WHERE run_id = ?
                  AND state = 'synced_unlisted'
                  AND synced_catalog_id IS NOT NULL
                ORDER BY created_at ASC, candidate_id ASC
                """,
                (run_id,),
            ).fetchall()
        expected_records: list[dict[str, Any]] = []
        for row in owned_rows:
            try:
                synced_record = json.loads(row["synced_public_record_json"] or "{}")
            except json.JSONDecodeError:
                synced_record = {}
            if (
                not isinstance(synced_record, dict)
                or not synced_record
                or synced_record.get("id") != row["synced_catalog_id"]
            ):
                blocking_reasons.append(
                    f"{row['candidate_id']}: stored synced public projection is missing or invalid"
                )
                continue
            expected_records.append(synced_record)
        expected_ids = sorted(str(row["synced_catalog_id"]) for row in owned_rows)
        actual_ids = sorted(identifier for identifier in added_ids if identifier)
        if actual_ids != expected_ids:
            blocking_reasons.append(
                "catalog additions do not exactly match candidates synced by this run"
            )
        if additions != expected_records:
            blocking_reasons.append(
                "catalog addition content or order differs from this run's stored public projection"
            )

        for record in additions:
            identifier = text(record.get("id")) or "<missing-id>"
            if record.get("visibility") != "unlisted":
                blocking_reasons.append(
                    f"{identifier}: publication additions must remain visibility=unlisted"
                )
            leaked = catalog_has_private_fields(record)
            if leaked:
                blocking_reasons.append(
                    f"{identifier}: private fields present ({', '.join(leaked)})"
                )
            unexpected_fields = sorted(set(record) - PUBLIC_RECORD_FIELDS)
            if unexpected_fields:
                blocking_reasons.append(
                    f"{identifier}: fields outside the public schema "
                    f"({', '.join(unexpected_fields)})"
                )
            contact_fields = sorted(
                field
                for field in PUBLIC_CONTACT_SCAN_FIELDS
                if field in record and contains_contact_detail(record[field])
            )
            if contact_fields:
                blocking_reasons.append(
                    f"{identifier}: contact details found in public fields "
                    f"({', '.join(contact_fields)})"
                )
            if record.get("productKind") not in PRODUCT_KINDS:
                blocking_reasons.append(
                    f"{identifier}: invalid productKind {record.get('productKind')!r}"
                )

        current_preflight = repository_preflight(catalog)
        catalog_path = str(start_preflight.get("catalogPath") or "data/products.json")
        if not bool(current_preflight.get("repositoryDetected")):
            blocking_reasons.append("catalog is no longer inside its Git worktree")
        if current_preflight.get("repositoryRoot") != start_preflight.get("repositoryRoot"):
            blocking_reasons.append("catalog Git worktree changed after run start")
        if current_preflight.get("catalogPath") != catalog_path:
            blocking_reasons.append("catalog Git path changed after run start")
        if not bool(current_preflight.get("catalogTracked")):
            blocking_reasons.append("catalog is no longer tracked by Git")
        if current_preflight.get("branch") != "main":
            blocking_reasons.append("publication preparation requires the main branch")
        if current_preflight.get("headSha") != start_preflight.get("headSha"):
            blocking_reasons.append("Git HEAD changed after run start")
        if current_preflight.get("upstreamRef") != start_preflight.get("upstreamRef"):
            blocking_reasons.append("Git upstream changed after run start")
        if current_preflight.get("upstreamSha") != start_preflight.get("upstreamSha"):
            blocking_reasons.append("local upstream commit changed after run start")
        if not bool(current_preflight.get("aligned")):
            blocking_reasons.append("Git HEAD no longer matches the local upstream commit")
        if current_preflight.get("stagedPaths"):
            blocking_reasons.append("publication preparation requires an empty Git index")
        if current_preflight.get("untrackedPaths"):
            blocking_reasons.append("publication preparation forbids untracked files")
        expected_unstaged = [catalog_path] if additions else []
        if current_preflight.get("unstagedPaths") != expected_unstaged:
            blocking_reasons.append(
                "worktree changes must be exactly one unstaged data/products.json change"
                if additions
                else "zero-addition publication preparation requires a clean worktree"
            )
        permitted_current_errors = (
            {"publication requires a clean whole worktree at run start"}
            if additions
            else set()
        )
        current_probe_errors = [
            error
            for error in current_preflight.get("errors") or []
            if error not in permitted_current_errors
        ]
        if current_probe_errors:
            blocking_reasons.append(
                "current Git preflight reported unresolved errors: "
                + "; ".join(current_probe_errors)
            )

        blocking_reasons = list(dict.fromkeys(blocking_reasons))
        if blocking_reasons:
            status = "blocked"
        elif additions:
            status = "prepared"
        else:
            status = "not_applicable"
        prepared_at = utc_now()
        current_catalog_digest = (
            hashlib.sha256(catalog.read_bytes()).hexdigest()
            if catalog.is_file()
            else None
        )
        manifest = {
            "runId": run_id,
            "attemptId": cleaned_attempt_id,
            "baseHeadSha": start_preflight.get("headSha"),
            "catalogSha256AtStart": run["catalog_sha256_at_start"],
            "catalogSha256Prepared": current_catalog_digest,
            "addedIds": [identifier for identifier in added_ids if identifier],
        }
        plan = {
            "contractVersion": "1.0",
            "runId": run_id,
            "attemptId": cleaned_attempt_id,
            "status": status,
            "preparedAt": prepared_at,
            "publicationAllowed": status == "prepared",
            "catalogSha256AtStart": run["catalog_sha256_at_start"],
            "catalogSha256Prepared": current_catalog_digest,
            "additionsCount": len(additions),
            "addedIds": [identifier for identifier in added_ids if identifier],
            "manifestSha256": sha256_text(stable_json(manifest)),
            "blockingReasons": blocking_reasons,
            "repositoryAtStart": self.publication_preflight_summary(start_preflight),
            "repositoryAtPreparation": self.publication_preflight_summary(
                current_preflight
            ),
        }
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO publication_attempts (
                    attempt_id, run_id, status, plan_json, result_json,
                    prepared_at, recorded_at
                ) VALUES (?, ?, ?, ?, '{}', ?, NULL)
                """,
                (
                    cleaned_attempt_id,
                    run_id,
                    status,
                    stable_json(plan),
                    prepared_at,
                ),
            )
            connection.execute(
                """
                UPDATE runs
                SET publication_status = ?, publication_attempt_id = ?
                WHERE run_id = ?
                """,
                (status, cleaned_attempt_id, run_id),
            )
        receipt_path = self.write_publication_receipt(
            run_id,
            cleaned_attempt_id,
            plan,
            {},
        )
        self.append_event(
            {
                "event": "publication_prepared",
                "eventKey": f"publication_prepared:{run_id}:{cleaned_attempt_id}",
                "runId": run_id,
                "attemptId": cleaned_attempt_id,
                "status": status,
                "publicationAllowed": status == "prepared",
                "addedIds": plan["addedIds"],
                "blockingReasons": blocking_reasons,
            }
        )
        self.queue(run_id)
        return {
            **plan,
            "idempotentReplay": False,
            "receipt": str(receipt_path),
        }

    @staticmethod
    def verify_local_publication_commit(
        plan: dict[str, Any],
        start_preflight: dict[str, Any],
        commit_sha: str,
        require_pushed: bool,
    ) -> str:
        repository_value = start_preflight.get("repositoryRoot")
        if not isinstance(repository_value, str) or not repository_value:
            raise LedgerError("Publication run is missing its private repository root.")
        repository = Path(repository_value).resolve()
        commit_ok, resolved_commit = git_text(
            repository,
            "rev-parse",
            "--verify",
            f"{commit_sha}^{{commit}}",
        )
        if not commit_ok or not resolved_commit:
            raise LedgerError("commit-sha is not a locally available Git commit.")
        if not resolved_commit.casefold().startswith(commit_sha.casefold()):
            raise LedgerError("commit-sha does not resolve to the supplied Git commit.")

        head_ok, current_head = git_text(repository, "rev-parse", "--verify", "HEAD")
        if not head_ok or current_head != resolved_commit:
            raise LedgerError("The publication commit must be the current local HEAD.")
        parent_ok, parent_sha = git_text(
            repository,
            "rev-parse",
            "--verify",
            f"{resolved_commit}^",
        )
        if not parent_ok or parent_sha != plan.get("repositoryAtStart", {}).get("headSha"):
            raise LedgerError(
                "The publication commit parent does not match the prepared base commit."
            )
        paths_ok, changed_paths = git_paths(
            repository,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "--no-renames",
            "-r",
            resolved_commit,
        )
        if not paths_ok or changed_paths != ["data/products.json"]:
            raise LedgerError(
                "The publication commit must change only data/products.json."
            )
        blob = subprocess.run(
            ["git", "show", f"{resolved_commit}:data/products.json"],
            cwd=repository,
            check=False,
            capture_output=True,
        )
        if (
            blob.returncode != 0
            or hashlib.sha256(blob.stdout).hexdigest()
            != plan.get("catalogSha256Prepared")
        ):
            raise LedgerError(
                "The publication commit catalog blob does not match the prepared target."
            )
        if require_pushed:
            upstream_ok, upstream_sha = git_text(
                repository,
                "rev-parse",
                "--verify",
                "origin/main",
            )
            if not upstream_ok or upstream_sha != resolved_commit:
                raise LedgerError(
                    "origin/main does not match the publication commit; fetch after push "
                    "before recording a pushed result."
                )
        return resolved_commit

    def record_publication(
        self,
        run_id: str,
        attempt_id: str | None,
        status: str,
        commit_sha: str | None,
        deployment_commit_sha: str | None,
        deployment_url: str | None,
        live_catalog_sha256: str | None,
        failure_code: str | None,
        live_verified: bool,
    ) -> dict[str, Any]:
        cleaned_attempt_id = self.publication_attempt_id(run_id, attempt_id)
        if status not in PUBLICATION_RESULT_STATUSES:
            raise LedgerError(f"Unsupported publication result status: {status!r}")
        cleaned_commit_sha = text(commit_sha)
        if cleaned_commit_sha and not re.fullmatch(r"[0-9a-fA-F]{7,64}", cleaned_commit_sha):
            raise LedgerError("commit-sha must be a 7-64 character hexadecimal Git object ID.")
        cleaned_deployment_commit_sha = text(deployment_commit_sha)
        if cleaned_deployment_commit_sha and not re.fullmatch(
            r"[0-9a-fA-F]{7,64}",
            cleaned_deployment_commit_sha,
        ):
            raise LedgerError(
                "deployment-commit-sha must be a 7-64 character hexadecimal Git object ID."
            )
        cleaned_live_catalog_sha256 = text(live_catalog_sha256)
        if cleaned_live_catalog_sha256 and not re.fullmatch(
            r"[0-9a-fA-F]{64}",
            cleaned_live_catalog_sha256,
        ):
            raise LedgerError("live-catalog-sha256 must be a 64-character hexadecimal digest.")
        cleaned_failure_code = text(failure_code)
        if cleaned_failure_code and not re.fullmatch(
            r"[a-z0-9][a-z0-9._-]{0,63}",
            cleaned_failure_code,
        ):
            raise LedgerError(
                "failure-code must be 1-64 lowercase letters, digits, dots, underscores, or hyphens."
            )
        cleaned_deployment_url = text(deployment_url)
        if cleaned_deployment_url:
            parts = urlsplit(cleaned_deployment_url)
            if (
                parts.scheme.casefold() not in {"http", "https"}
                or not parts.hostname
                or parts.username
                or parts.password
            ):
                raise LedgerError("deployment-url must be a plain public HTTP(S) URL.")
        if status in {"pushed_not_verified", "deployment_failed", "live_verified"} and not cleaned_commit_sha:
            raise LedgerError(f"{status} requires --commit-sha.")
        if status == "live_verified" and (
            not live_verified or not cleaned_deployment_url
        ):
            raise LedgerError(
                "live_verified requires --live-verified and --deployment-url."
            )
        if status != "live_verified" and live_verified:
            raise LedgerError("--live-verified is only valid with status live_verified.")
        if status == "live_verified" and (
            not cleaned_deployment_commit_sha or not cleaned_live_catalog_sha256
        ):
            raise LedgerError(
                "live_verified requires --deployment-commit-sha and "
                "--live-catalog-sha256."
            )

        with self.connect() as connection:
            run = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            attempt = connection.execute(
                "SELECT * FROM publication_attempts WHERE attempt_id = ?",
                (cleaned_attempt_id,),
            ).fetchone()
        if not run:
            raise LedgerError(f"Unknown private review run: {run_id}")
        if run["publication_mode"] != PUBLICATION_MODE_UNLISTED:
            raise LedgerError(f"Run {run_id!r} did not enable guarded publication.")
        if run["finished_at"] is None or run["lifecycle_stage"] != "finished":
            raise LedgerError(
                f"Run {run_id!r} must finish and release its private run lock "
                "before recording an external publication result."
            )
        if not attempt or attempt["run_id"] != run_id:
            raise LedgerError(
                f"Unknown publication attempt {cleaned_attempt_id!r} for run {run_id!r}."
            )
        if run["publication_attempt_id"] != cleaned_attempt_id:
            raise LedgerError(
                f"Publication attempt {cleaned_attempt_id!r} is not the current "
                f"resolved attempt for run {run_id!r}."
            )
        try:
            plan = json.loads(attempt["plan_json"])
            prior_result = json.loads(attempt["result_json"] or "{}")
        except json.JSONDecodeError as error:
            raise LedgerError(
                f"Publication attempt {cleaned_attempt_id!r} contains malformed private JSON."
            ) from error
        try:
            start_preflight = json.loads(run["repository_preflight_json"] or "{}")
        except json.JSONDecodeError as error:
            raise LedgerError(
                f"Publication run {run_id!r} has malformed repository proof data."
            ) from error

        if attempt["status"] in PUBLICATION_RESULT_STATUSES:
            expected_input = {
                "status": status,
                "deploymentCommitSha": cleaned_deployment_commit_sha,
                "deploymentUrl": cleaned_deployment_url,
                "liveCatalogSha256": cleaned_live_catalog_sha256,
                "failureCode": cleaned_failure_code,
                "liveVerified": live_verified,
            }
            observed = {key: prior_result.get(key) for key in expected_input}
            prior_commit = text(prior_result.get("commitSha"))
            same_commit = bool(
                (not prior_commit and not cleaned_commit_sha)
                or (
                    prior_commit
                    and cleaned_commit_sha
                    and prior_commit.casefold().startswith(
                        cleaned_commit_sha.casefold()
                    )
                )
            )
            if observed != expected_input or not same_commit:
                raise LedgerError(
                    f"Publication attempt {cleaned_attempt_id!r} already has a different "
                    "terminal result."
                )
            receipt_path = self.write_publication_receipt(
                run_id,
                cleaned_attempt_id,
                plan,
                prior_result,
            )
            self.append_event(
                {
                    "event": "publication_result_recorded",
                    "eventKey": (
                        f"publication_result_recorded:{run_id}:"
                        f"{cleaned_attempt_id}:{status}"
                    ),
                    "runId": run_id,
                    "attemptId": cleaned_attempt_id,
                    **prior_result,
                }
            )
            self.queue(run_id)
            return {
                "runId": run_id,
                "attemptId": cleaned_attempt_id,
                **prior_result,
                "idempotentReplay": True,
                "receipt": str(receipt_path),
            }

        resolved_commit_sha = cleaned_commit_sha
        if cleaned_commit_sha:
            resolved_commit_sha = self.verify_local_publication_commit(
                plan,
                start_preflight,
                cleaned_commit_sha,
                status
                in {"pushed_not_verified", "deployment_failed", "live_verified"},
            )
        if status == "live_verified":
            if cleaned_deployment_commit_sha.casefold() != resolved_commit_sha.casefold():
                raise LedgerError(
                    "deployment-commit-sha must equal the verified pushed commit."
                )
            if (
                cleaned_live_catalog_sha256.casefold()
                != str(plan.get("catalogSha256Prepared") or "").casefold()
            ):
                raise LedgerError(
                    "live-catalog-sha256 must equal the prepared catalog digest."
                )
            deployment_host = (urlsplit(cleaned_deployment_url).hostname or "").casefold()
            if deployment_host != "caribbeansaas.com" and not deployment_host.endswith(
                ".caribbeansaas.pages.dev"
            ):
                raise LedgerError(
                    "A live-verified deployment URL must use caribbeansaas.com "
                    "or the caribbeansaas.pages.dev project."
                )
        if attempt["status"] != "prepared" or not bool(plan.get("publicationAllowed")):
            raise LedgerError(
                f"Publication attempt {cleaned_attempt_id!r} is {attempt['status']!r}; "
                "no external publication result may be recorded."
            )

        recorded_at = utc_now()
        result = {
            "status": status,
            "commitSha": resolved_commit_sha,
            "deploymentCommitSha": cleaned_deployment_commit_sha,
            "deploymentUrl": cleaned_deployment_url,
            "liveCatalogSha256": cleaned_live_catalog_sha256,
            "failureCode": cleaned_failure_code,
            "liveVerified": live_verified,
            "recordedAt": recorded_at,
        }
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE publication_attempts
                SET status = ?, result_json = ?, recorded_at = ?
                WHERE attempt_id = ? AND run_id = ?
                """,
                (
                    status,
                    stable_json(result),
                    recorded_at,
                    cleaned_attempt_id,
                    run_id,
                ),
            )
            if run["publication_attempt_id"] == cleaned_attempt_id:
                connection.execute(
                    """
                    UPDATE runs SET publication_status = ?
                    WHERE run_id = ?
                    """,
                    (status, run_id),
                )
        receipt_path = self.write_publication_receipt(
            run_id,
            cleaned_attempt_id,
            plan,
            result,
        )
        self.append_event(
            {
                "event": "publication_result_recorded",
                "eventKey": (
                    f"publication_result_recorded:{run_id}:{cleaned_attempt_id}:{status}"
                ),
                "runId": run_id,
                "attemptId": cleaned_attempt_id,
                **result,
            }
        )
        self.queue(run_id)
        return {
            "runId": run_id,
            "attemptId": cleaned_attempt_id,
            **result,
            "idempotentReplay": False,
            "receipt": str(receipt_path),
        }

    def inventory(self, catalog: Path) -> dict[str, Any]:
        _catalog_payload, products = load_catalog(catalog)
        public_records = []
        for product in products:
            website_url = text(product.get("websiteUrl"))
            public_records.append(
                {
                    "id": product.get("id"),
                    "name": product.get("name"),
                    "aliases": candidate_aliases(product, text(product.get("name"))),
                    "canonicalDomain": canonical_domain(website_url) if website_url else None,
                    "officialAppStoreIds": candidate_app_store_ids(product),
                    "visibility": product.get("visibility"),
                    "productKind": product.get("productKind"),
                }
            )
        with self.connect() as connection:
            private_rows = connection.execute(
                """
                SELECT candidate_id, name, canonical_domain, aliases_json,
                       app_store_ids_json, state, catalog_match_id
                FROM candidates
                ORDER BY name COLLATE NOCASE ASC
                """
            ).fetchall()
        private_records = [
            {
                "candidateId": row["candidate_id"],
                "name": row["name"],
                "aliases": json.loads(row["aliases_json"] or "[]"),
                "canonicalDomain": row["canonical_domain"],
                "officialAppStoreIds": json.loads(row["app_store_ids_json"] or "[]"),
                "state": row["state"],
                "catalogMatchId": row["catalog_match_id"],
            }
            for row in private_rows
        ]
        return {
            "public": public_records,
            "private": private_records,
            "counts": {
                "public": len(public_records),
                "private": len(private_records),
            },
        }

    def existing_candidate(
        self,
        connection: sqlite3.Connection,
        domain: str,
        app_store_ids: list[str],
    ) -> sqlite3.Row | None:
        domain_match = connection.execute(
            """
            SELECT * FROM candidates
            WHERE canonical_domain = ?
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (domain,),
        ).fetchone()
        if domain_match:
            return domain_match
        if app_store_ids:
            wanted = set(app_store_ids)
            for row in connection.execute(
                """
                SELECT * FROM candidates
                WHERE app_store_ids_json != '[]'
                ORDER BY created_at ASC
                """
            ).fetchall():
                try:
                    known_ids = set(json.loads(row["app_store_ids_json"] or "[]"))
                except json.JSONDecodeError:
                    known_ids = set()
                if wanted & known_ids:
                    return row
        return None

    @staticmethod
    def existing_name_candidate(
        connection: sqlite3.Connection,
        normalized_names: set[str],
    ) -> sqlite3.Row | None:
        for row in connection.execute(
            "SELECT * FROM candidates ORDER BY created_at ASC"
        ).fetchall():
            known_names = {str(row["normalized_name"])}
            try:
                known_names.update(
                    normalize_name(alias)
                    for alias in json.loads(row["aliases_json"] or "[]")
                    if text(alias)
                )
            except json.JSONDecodeError:
                pass
            if normalized_names & known_names:
                return row
        return None

    @staticmethod
    def ingest_context(payload: Any) -> tuple[list[Any], dict[str, Any]]:
        if not isinstance(payload, dict):
            raise LedgerError("Ingest JSON must be a normalized coordinator envelope.")
        envelope = payload
        if envelope.get("contractVersion") != "1.0":
            raise LedgerError("Normalized ingest requires contractVersion '1.0'.")
        if envelope.get("workerContractsValidated") is not True:
            raise LedgerError(
                "Normalized ingest requires workerContractsValidated to be explicitly true."
            )
        raw_candidates = envelope.get("candidates")
        if not isinstance(raw_candidates, list):
            raise LedgerError("Normalized ingest requires a candidates array, including when empty.")

        run_id = optional_text(envelope, "runId", "run_id")
        if not run_id:
            raise LedgerError("Normalized ingest requires the active runId.")
        provenance = envelope.get("modelProvenance")
        coverage = envelope.get("coverage")
        source_failures = envelope.get("sourceFailures")
        raw_sources = envelope.get("sources")
        raw_worker_results = envelope.get("workerResults")
        attestation = envelope.get("sideEffectAttestation")
        if not isinstance(provenance, dict) or not provenance:
            raise LedgerError("Normalized ingest requires non-empty modelProvenance.")
        workers = provenance.get("workers")
        if not isinstance(workers, list):
            raise LedgerError("modelProvenance requires a workers array.")
        validated_roles: set[str] = set()
        worker_models: set[str] = set()
        for worker in workers:
            if not isinstance(worker, dict):
                raise LedgerError("Every modelProvenance worker must be a JSON object.")
            if worker.get("contractVersion") != "1.0":
                raise LedgerError("Every modelProvenance worker requires contractVersion '1.0'.")
            role = optional_text(worker, "role")
            if not role or role not in WORKER_REQUIREMENTS:
                raise LedgerError(f"Unsupported or missing worker role: {role!r}.")
            if role in validated_roles:
                raise LedgerError(f"modelProvenance contains duplicate worker role {role!r}.")
            requirement = WORKER_REQUIREMENTS[role]
            agent = optional_text(worker, "agent")
            model = optional_text(worker, "model")
            reasoning_effort = optional_text(worker, "reasoningEffort", "reasoning_effort")
            status = optional_text(worker, "status")
            if agent != requirement["agent"]:
                raise LedgerError(
                    f"Worker role {role!r} requires agent {requirement['agent']!r}."
                )
            if model not in requirement["models"]:
                raise LedgerError(
                    f"Worker role {role!r} has unsupported model {model!r}."
                )
            if reasoning_effort != requirement["reasoningEffort"]:
                raise LedgerError(
                    f"Worker role {role!r} requires reasoning effort "
                    f"{requirement['reasoningEffort']!r}."
                )
            if status not in WORKER_STATUSES:
                raise LedgerError(f"Worker role {role!r} has unsupported status {status!r}.")
            fallback = worker.get("modelFallback")
            if role == "scout" and model == "gpt-5.6-terra":
                if fallback != "gpt-5.6-terra-low":
                    raise LedgerError(
                        "The scout's Luna-to-Terra fallback must be recorded as "
                        "modelFallback 'gpt-5.6-terra-low'."
                    )
            elif fallback not in (None, ""):
                raise LedgerError(
                    f"Worker role {role!r} records an unexpected modelFallback."
                )
            validated_roles.add(role)
            worker_models.add(str(model))
        missing_roles = sorted(set(WORKER_REQUIREMENTS) - validated_roles)
        if missing_roles:
            raise LedgerError(
                "modelProvenance is missing required worker roles: " + ", ".join(missing_roles)
            )
        declared_models = provenance.get("models")
        if (
            not isinstance(declared_models, list)
            or not declared_models
            or {text(model) for model in declared_models if text(model)} != worker_models
        ):
            raise LedgerError(
                "modelProvenance.models must exactly match the validated worker models."
            )
        if not isinstance(provenance.get("fallbacks"), list):
            raise LedgerError("modelProvenance requires a fallbacks array.")
        if not isinstance(coverage, dict):
            raise LedgerError("Normalized ingest requires a coverage object.")
        if not isinstance(source_failures, list):
            raise LedgerError("Normalized ingest requires a sourceFailures array.")
        if not isinstance(raw_sources, list):
            raise LedgerError("Normalized ingest requires a sources array.")
        if not isinstance(attestation, dict):
            raise LedgerError("Normalized ingest requires sideEffectAttestation.")
        missing_attestations = sorted(INGEST_ATTESTATION_FIELDS - set(attestation))
        if missing_attestations:
            raise LedgerError(
                "sideEffectAttestation is missing: " + ", ".join(missing_attestations)
            )
        unknown_attestations = sorted(set(attestation) - INGEST_ATTESTATION_FIELDS)
        if unknown_attestations:
            raise LedgerError(
                "sideEffectAttestation contains unsupported fields: "
                + ", ".join(unknown_attestations)
            )
        non_false_attestations = sorted(
            field
            for field in INGEST_ATTESTATION_FIELDS
            if attestation.get(field) is not False
        )
        if non_false_attestations:
            raise LedgerError(
                "sideEffectAttestation must explicitly set every protected action to false: "
                + ", ".join(non_false_attestations)
            )
        source_index: dict[str, dict[str, Any]] = {}
        for source_position, source in enumerate(raw_sources):
            validate_worker_source(
                source,
                f"sources[{source_position}]",
            )
            source_id = optional_text(source, "sourceId", "source_id", "id")
            if not source_id:
                raise LedgerError("Every top-level source requires a sourceId.")
            existing_source = source_index.get(source_id)
            if existing_source and stable_json(existing_source) != stable_json(source):
                raise LedgerError(f"Conflicting top-level sources share sourceId {source_id!r}.")
            source_index[source_id] = source
        validated_worker_results = validate_worker_results(
            raw_worker_results,
            run_id,
            provenance,
            source_index,
        )
        cross_role_hold_reasons = validate_normalized_candidate_links(
            raw_candidates,
            validated_worker_results,
            source_index,
        )
        safe_provenance, _provenance_redactions = sanitize_private_value(
            provenance if isinstance(provenance, dict) else {"value": str(provenance)},
            "modelProvenance",
        )
        safe_coverage, _coverage_redactions = sanitize_private_value(
            coverage if isinstance(coverage, dict) else {"value": coverage},
            "coverage",
        )
        safe_failures, _failure_redactions = sanitize_private_value(
            source_failures,
            "sourceFailures",
        )
        return raw_candidates, {
            "runId": run_id,
            "provenance": safe_provenance if isinstance(safe_provenance, dict) else {},
            "coverage": safe_coverage if isinstance(safe_coverage, dict) else {},
            "sourceFailures": safe_failures if isinstance(safe_failures, list) else [],
            "sideEffectAttestation": {
                field: False for field in sorted(INGEST_ATTESTATION_FIELDS)
            },
            "workerContractsValidated": True,
            "sourceIndex": source_index,
            "crossRoleHoldReasons": cross_role_hold_reasons,
        }

    @staticmethod
    def observation_key(candidate_id: str, run_id: str, source_digest: str, outcome: str) -> str:
        # Outcome can evolve as a candidate is processed, but the same candidate,
        # run, and evidence payload is one observation. This makes retries no-ops.
        return f"observation:{candidate_id}:{run_id}:{source_digest[:16]}"

    @staticmethod
    def record_observation(
        connection: sqlite3.Connection,
        event_key: str,
        run_id: str,
        candidate_id: str,
        outcome: str,
        source_digest: str,
    ) -> bool:
        result = connection.execute(
            """
            INSERT OR IGNORE INTO observations(event_key, run_id, candidate_id, outcome, source_digest, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (event_key, run_id, candidate_id, outcome, source_digest, utc_now()),
        )
        return result.rowcount == 1

    def ingest(self, catalog: Path, input_path: Path) -> dict[str, Any]:
        payload = read_json(input_path)
        raw_candidates, context = self.ingest_context(payload)
        self.require_active_run(str(context["runId"]))
        _catalog_payload, products = load_catalog(catalog)
        inserted: list[str] = []
        events: list[dict[str, Any]] = []
        duplicate_catalog = 0
        duplicate_candidates = 0
        holds = 0

        with self.connect() as connection:
            connection.execute(
                """
                UPDATE runs
                SET provenance_json = ?, coverage_json = ?, source_failures_json = ?,
                    attestation_json = ?, worker_contracts_validated = 1,
                    lifecycle_stage = 'ingested'
                WHERE run_id = ?
                """,
                (
                    stable_json(context["provenance"]),
                    stable_json(context["coverage"]),
                    stable_json(context["sourceFailures"]),
                    stable_json(context["sideEffectAttestation"]),
                    context["runId"],
                ),
            )
            for raw_candidate in raw_candidates:
                if not isinstance(raw_candidate, dict):
                    raise LedgerError("Each ingest candidate must be a JSON object.")
                if "sources" in raw_candidate:
                    raise LedgerError(
                        "Normalized candidates must reference top-level sources by sourceIds; "
                        "candidate-local source objects are not accepted."
                    )
                lead_key = optional_text(raw_candidate, "leadKey")
                if not lead_key:
                    raise LedgerError("Each normalized ingest candidate requires a leadKey.")
                candidate_name = text(raw_candidate.get("name"))
                if not candidate_name:
                    raise LedgerError("Each ingest candidate requires a name.")
                if contains_contact_detail(candidate_name):
                    raise LedgerError("Candidate names must not contain email addresses or phone numbers.")
                website_url = canonicalize_url(raw_candidate.get("websiteUrl") or raw_candidate.get("website_url"))
                domain = canonical_domain(website_url)
                normalized = normalize_name(candidate_name)
                app_store_ids = candidate_app_store_ids(raw_candidate)
                aliases = candidate_aliases(raw_candidate, candidate_name)
                normalized_names = {normalized} | {
                    normalize_name(alias) for alias in aliases if normalize_name(alias)
                }
                if not normalized:
                    raise LedgerError("Each ingest candidate requires a normalizable name.")

                confidence_value = raw_candidate.get("confidence")
                confidence: float | None
                if confidence_value is None:
                    confidence = None
                else:
                    try:
                        confidence = float(confidence_value)
                    except (TypeError, ValueError) as error:
                        raise LedgerError(f"Candidate {candidate_name!r} has an invalid confidence value.") from error
                    if not 0 <= confidence <= 1:
                        raise LedgerError(f"Candidate {candidate_name!r} confidence must be between 0 and 1.")

                sources = normalise_sources(source_refs(raw_candidate), context["sourceIndex"])
                evidence_a, evidence_b = extract_evidence(raw_candidate)
                official_sources = [source for source in sources if source.get("sourceClass") in OFFICIAL_SOURCE_CLASSES]
                secondary_sources = [
                    source
                    for source in sources
                    if not official_sources or source["url"] != official_sources[0]["url"]
                ]
                evidence_a = evidence_a or (normalise_evidence(official_sources[0]) if official_sources else None)
                evidence_b = evidence_b or (normalise_evidence(secondary_sources[0]) if secondary_sources else None)
                public_payload, removed_public_contact_fields = safe_public_payload(
                    raw_candidate,
                    website_url,
                )
                recommendation = (
                    optional_text(raw_candidate, "recommendation", "reviewRecommendation", "review_recommendation")
                    or "hold"
                ).casefold()
                tier = candidate_tier(raw_candidate)
                hold_reasons = gate_reasons(recommendation, confidence, evidence_a, evidence_b, tier, sources)
                hold_reasons.extend(
                    context["crossRoleHoldReasons"].get(lead_key, [])
                )
                hold_reasons.extend(
                    f"public projection field {field} contained a contact detail and was removed"
                    for field in removed_public_contact_fields
                )
                hold_reasons.extend(public_projection_reasons(public_payload))
                hold_reasons = list(dict.fromkeys(hold_reasons))
                source_digest = sha256_text(stable_json({"candidate": raw_candidate, "sources": sources}))

                existing = self.existing_candidate(connection, domain, app_store_ids)
                if existing:
                    duplicate_candidates += 1
                    event_key = self.observation_key(
                        str(existing["candidate_id"]), context["runId"], source_digest, "duplicate_candidate"
                    )
                    if self.record_observation(
                        connection,
                        event_key,
                        context["runId"],
                        str(existing["candidate_id"]),
                        "duplicate_candidate",
                        source_digest,
                    ):
                        events.append(
                            {
                                "event": "candidate_observed",
                                "eventKey": event_key,
                                "candidateId": existing["candidate_id"],
                                "runId": context["runId"],
                                "outcome": "duplicate_candidate",
                            }
                        )
                    continue

                matched_catalog = catalog_exact_match(products, domain, app_store_ids)
                possible_private_name = self.existing_name_candidate(connection, normalized_names)
                possible_catalog_name = catalog_name_match(products, normalized_names)
                if possible_private_name:
                    hold_reasons.append(
                        "possible private duplicate: normalized name matches a different identity"
                    )
                if possible_catalog_name:
                    hold_reasons.append(
                        "possible catalog duplicate: normalized name matches a different domain"
                    )
                hold_reasons = list(dict.fromkeys(hold_reasons))
                if matched_catalog:
                    state = "duplicate_catalog"
                    duplicate_kind, catalog_match_id = matched_catalog
                    duplicate_catalog += 1
                elif hold_reasons:
                    state = "hold"
                    if possible_private_name:
                        duplicate_kind = "possible_private_name"
                        catalog_match_id = str(possible_private_name["candidate_id"])
                    elif possible_catalog_name:
                        duplicate_kind, catalog_match_id = possible_catalog_name
                    else:
                        duplicate_kind = None
                        catalog_match_id = None
                    holds += 1
                else:
                    state = "ready_for_human_review"
                    duplicate_kind = None
                    catalog_match_id = None

                candidate_id = f"candidate-{sha256_text(domain + '|' + normalized)[:16]}"
                now = utc_now()
                private_payload, redacted_input_fields = compact_private_payload(
                    raw_candidate,
                    evidence_a,
                    evidence_b,
                    sources,
                )
                automated_review = {
                    "runId": context["runId"],
                    "modelProvenance": context["provenance"],
                    "coverage": context["coverage"],
                    "sourceFailures": context["sourceFailures"],
                    "sideEffectAttestation": context["sideEffectAttestation"],
                    "sources": sources,
                    "officialAppStoreIds": app_store_ids,
                    "aliases": aliases,
                    "caribbeanEvidenceTier": tier,
                    "gateReasons": hold_reasons,
                    "recommendation": recommendation,
                    "confidence": confidence,
                }
                if redacted_input_fields:
                    automated_review["redactedInputFields"] = redacted_input_fields
                sanitized_automated_review, _automated_redactions = sanitize_private_value(
                    automated_review,
                    "automatedReview",
                )
                connection.execute(
                    """
                    INSERT INTO candidates (
                        candidate_id, canonical_domain, normalized_name, name, website_url, company_name,
                        public_payload_json, private_payload_json, automated_review_json, human_decision_json,
                        recommendation, confidence, evidence_a_json, evidence_b_json, caribbean_evidence_tier,
                        sources_json, app_store_ids_json, aliases_json, run_id, state, hold_reasons_json, duplicate_kind, catalog_match_id,
                        source_digest, synced_catalog_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        candidate_id,
                        domain,
                        normalized,
                        candidate_name,
                        website_url,
                        text(public_payload.get("companyName")),
                        stable_json(public_payload),
                        stable_json(private_payload),
                        stable_json(sanitized_automated_review),
                        recommendation,
                        confidence,
                        stable_json(evidence_a) if evidence_a else None,
                        stable_json(evidence_b) if evidence_b else None,
                        tier,
                        stable_json(sources),
                        stable_json(app_store_ids),
                        stable_json(aliases),
                        context["runId"],
                        state,
                        stable_json(hold_reasons),
                        duplicate_kind,
                        catalog_match_id,
                        source_digest,
                        now,
                        now,
                    ),
                )
                inserted.append(candidate_id)
                event_key = self.observation_key(candidate_id, context["runId"], source_digest, state)
                if self.record_observation(connection, event_key, context["runId"], candidate_id, state, source_digest):
                    events.append(
                        {
                            "event": "candidate_ingested",
                            "eventKey": event_key,
                            "candidateId": candidate_id,
                            "runId": context["runId"],
                            "outcome": state,
                        }
                    )

        for event in events:
            self.append_event(event)
        return {
            "runId": context["runId"],
            "inserted": len(inserted),
            "candidateIds": inserted,
            "duplicateCatalog": duplicate_catalog,
            "duplicateCandidates": duplicate_candidates,
            "holds": holds,
            "observations": len(events),
        }

    def queue(self, run_id: str | None = None) -> dict[str, Any]:
        with self.connect() as connection:
            if not run_id:
                latest = connection.execute("SELECT run_id FROM runs ORDER BY created_at DESC LIMIT 1").fetchone()
                if not latest:
                    raise LedgerError("The private ledger has no runs to queue.")
                run_id = str(latest["run_id"])
            run = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if not run:
                raise LedgerError(f"Unknown private review run: {run_id}")
            active_lock = self.read_lock()
            active_run = bool(
                active_lock
                and active_lock.get("runId") == run_id
                and not run["finished_at"]
            )
            if active_run and not bool(run["worker_contracts_validated"]):
                raise LedgerError(
                    f"Run {run_id!r} has no successful validated ingest to package."
                )
            rows = connection.execute(
                """
                SELECT candidates.*, observations.outcome, observations.created_at AS observed_at
                FROM observations
                JOIN candidates ON candidates.candidate_id = observations.candidate_id
                WHERE observations.run_id = ?
                  AND observations.rowid = (
                      SELECT latest.rowid
                      FROM observations AS latest
                      WHERE latest.run_id = ?
                        AND latest.candidate_id = observations.candidate_id
                      ORDER BY latest.created_at DESC, latest.rowid DESC
                      LIMIT 1
                  )
                ORDER BY candidates.state ASC, candidates.name COLLATE NOCASE ASC
                """,
                (run_id, run_id),
            ).fetchall()

        grouped: dict[str, list[sqlite3.Row]] = {
            "ready_for_human_review": [],
            "hold": [],
            "duplicate_catalog": [],
            "duplicate_candidate": [],
            "synced_unlisted": [],
        }
        for row in rows:
            packet_state = "duplicate_candidate" if row["outcome"] == "duplicate_candidate" else str(row["state"])
            grouped.setdefault(packet_state, []).append(row)

        coverage = json.loads(run["coverage_json"])
        source_failures = json.loads(run["source_failures_json"])
        provenance = json.loads(run["provenance_json"])
        side_effect_attestation = json.loads(run["attestation_json"] or "{}")
        worker_contracts_validated = bool(run["worker_contracts_validated"])
        publication = self.publication_summary(run_id)
        packet_candidates: list[dict[str, Any]] = []
        lines = [
            "# CaribbeanSaaS private review queue",
            "",
            f"Run ID: {run_id}",
            f"Recorded: {run['created_at']}",
            "",
            "## Run context",
            "",
            f"- Model provenance: `{stable_json(provenance)}`",
            f"- Coverage: `{stable_json(coverage)}`",
            f"- Source failures: `{stable_json(source_failures)}`",
            f"- Side-effect attestation: `{stable_json(side_effect_attestation)}`",
            f"- Worker contracts validated: `{str(worker_contracts_validated).lower()}`",
            "",
            "## Coordinator publication gate",
            "",
            f"- Mode: `{publication['mode']}`",
            f"- Status: `{publication['status']}`",
            f"- Run-start preflight: `{stable_json(publication['preflight'])}`",
            f"- Private attempts: `{stable_json(publication['attempts'])}`",
            "",
        ]
        titles = {
            "ready_for_human_review": "Ready for human review",
            "hold": "Held candidates",
            "duplicate_catalog": "Catalog duplicates",
            "duplicate_candidate": "Previously known candidates observed again",
            "synced_unlisted": "Synced as unlisted",
        }
        for state in (
            "ready_for_human_review",
            "hold",
            "duplicate_catalog",
            "duplicate_candidate",
            "synced_unlisted",
        ):
            lines.extend([f"## {titles[state]}", ""])
            state_rows = grouped.get(state, [])
            if not state_rows:
                lines.extend(["None.", ""])
                continue
            lines.extend(["| Candidate | Website | Confidence | Reason |", "| --- | --- | ---: | --- |"])
            for row in state_rows:
                reasons = json.loads(row["hold_reasons_json"] or "[]")
                evidence_a = json.loads(row["evidence_a_json"]) if row["evidence_a_json"] else None
                evidence_b = json.loads(row["evidence_b_json"]) if row["evidence_b_json"] else None
                if state == "duplicate_catalog":
                    reason = f"{row['duplicate_kind']}: {row['catalog_match_id']}"
                elif state == "duplicate_candidate":
                    reason = f"previously known private candidate: {row['candidate_id']}"
                elif state == "synced_unlisted":
                    reason = f"catalog id: {row['synced_catalog_id']}"
                else:
                    reason = "; ".join(reasons) if reasons else "ready"
                name = str(row["name"]).replace("|", "\\|")
                website = str(row["website_url"]).replace("|", "%7C")
                confidence = "" if row["confidence"] is None else f"{float(row['confidence']):.2f}"
                safe_reason = reason.replace("|", "\\|")
                lines.append(f"| {name} | {website} | {confidence} | {safe_reason} |")
                packet_candidates.append(
                    {
                        "candidateId": row["candidate_id"],
                        "name": row["name"],
                        "websiteUrl": row["website_url"],
                        "aliases": json.loads(row["aliases_json"] or "[]"),
                        "officialAppStoreIds": json.loads(row["app_store_ids_json"] or "[]"),
                        "state": state,
                        "outcome": row["outcome"],
                        "confidence": row["confidence"],
                        "caribbeanEvidenceTier": row["caribbean_evidence_tier"],
                        "evidence": {"A": evidence_a, "B": evidence_b},
                        "holdReasons": reasons,
                        "catalogMatchId": row["catalog_match_id"],
                        "syncedCatalogId": row["synced_catalog_id"],
                    }
                )
            lines.append("")

        lines.extend(
            [
                "## Safety attestation",
                "",
                "The worker research represented in this packet created no account, submitted "
                "no form, contacted nobody, mutated no third-party system, set no record to "
                "`visibility: listed`, and performed no repository or deployment action. "
                "Any authorized coordinator preflight or publication action is recorded "
                "separately in the repository proof and private publication receipt.",
                "",
            ]
        )
        queue_file, queue_json = self.packet_paths(run_id)
        content = "\n".join(lines) + "\n"
        if not queue_file.exists() or queue_file.read_text(encoding="utf-8") != content:
            atomic_write_bytes(queue_file, content.encode("utf-8"))
        packet = {
            "runId": run_id,
            "recordedAt": run["created_at"],
            "modelProvenance": provenance,
            "coverage": coverage,
            "sourceFailures": source_failures,
            "sideEffectAttestation": side_effect_attestation,
            "workerContractsValidated": worker_contracts_validated,
            "publication": publication,
            "candidates": packet_candidates,
            "counts": {
                "readyForHumanReview": len(grouped.get("ready_for_human_review", [])),
                "hold": len(grouped.get("hold", [])),
                "duplicateCatalog": len(grouped.get("duplicate_catalog", [])),
                "duplicateCandidates": len(grouped.get("duplicate_candidate", [])),
                "syncedUnlisted": len(grouped.get("synced_unlisted", [])),
            },
            "packetOperationAttestation": {
                "accountsCreated": False,
                "formsSubmitted": False,
                "contactsMade": False,
                "thirdPartyMutations": False,
                "listedVisibilityWrites": False,
                "gitActions": False,
                "deploymentActions": False,
            },
        }
        if not queue_json.exists() or json.loads(queue_json.read_text(encoding="utf-8")) != packet:
            atomic_write_json(queue_json, packet)
        if active_run:
            with self.connect() as connection:
                connection.execute(
                    """
                    UPDATE runs
                    SET lifecycle_stage = CASE
                        WHEN lifecycle_stage = 'validated' THEN 'validated'
                        ELSE 'packeted'
                    END
                    WHERE run_id = ? AND finished_at IS NULL
                    """,
                    (run_id,),
                )
        return {
            "runId": run_id,
            "queue": str(queue_file),
            "queueJson": str(queue_json),
            "readyForHumanReview": len(grouped.get("ready_for_human_review", [])),
            "hold": len(grouped.get("hold", [])),
            "duplicateCatalog": len(grouped.get("duplicate_catalog", [])),
            "duplicateCandidates": len(grouped.get("duplicate_candidate", [])),
            "syncedUnlisted": len(grouped.get("synced_unlisted", [])),
        }

    def sync_unlisted(self, catalog: Path, run_id: str) -> dict[str, Any]:
        run = self.require_active_run(run_id)
        if not bool(run["worker_contracts_validated"]):
            raise LedgerError(
                f"Run {run_id!r} has no validated worker-contract attestation; "
                "public projection is disabled."
            )
        try:
            run_provenance = json.loads(run["provenance_json"] or "{}")
        except json.JSONDecodeError as error:
            raise LedgerError(f"Run {run_id!r} has invalid model provenance JSON.") from error
        run_workers = (
            run_provenance.get("workers")
            if isinstance(run_provenance, dict)
            else None
        )
        if (
            not isinstance(run_workers, list)
            or {worker.get("role") for worker in run_workers if isinstance(worker, dict)}
            != set(WORKER_REQUIREMENTS)
            or any(
                not isinstance(worker, dict) or worker.get("status") != "complete"
                for worker in run_workers
            )
        ):
            raise LedgerError(
                f"Run {run_id!r} does not have complete results from all required workers; "
                "public projection is disabled."
            )
        try:
            run_attestation = json.loads(run["attestation_json"] or "{}")
        except json.JSONDecodeError as error:
            raise LedgerError(f"Run {run_id!r} has invalid side-effect attestation JSON.") from error
        if (
            not isinstance(run_attestation, dict)
            or set(run_attestation) != INGEST_ATTESTATION_FIELDS
            or any(run_attestation.get(field) is not False for field in INGEST_ATTESTATION_FIELDS)
        ):
            raise LedgerError(
                f"Run {run_id!r} lacks the complete all-false side-effect attestation; "
                "public projection is disabled."
            )
        if not bool(run["catalog_clean_at_start"]):
            raise LedgerError(
                f"Run {run_id!r} began with a dirty public catalog; public projection is disabled "
                "for the whole run even if the worktree later becomes clean."
            )
        if run["publication_mode"] == PUBLICATION_MODE_UNLISTED:
            try:
                publication_preflight = json.loads(
                    run["repository_preflight_json"] or "{}"
                )
            except json.JSONDecodeError as error:
                raise LedgerError(
                    f"Run {run_id!r} has malformed repository preflight facts; "
                    "public projection is disabled."
                ) from error
            if (
                not isinstance(publication_preflight, dict)
                or not bool(publication_preflight.get("eligible"))
            ):
                raise LedgerError(
                    f"Run {run_id!r} did not begin on a clean, upstream-aligned main "
                    "worktree; public projection and publication are disabled for this run."
                )
        catalog_payload, products = load_catalog(catalog)
        if catalog_payload.get("schemaVersion") != 2:
            raise LedgerError("sync-unlisted requires data/products.json schemaVersion 2.")
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE runs
                SET lifecycle_stage = 'ingested'
                WHERE run_id = ? AND finished_at IS NULL
                """,
                (run_id,),
            )
        self.snapshot(catalog)
        existing_ids = {str(product.get("id")) for product in products if product.get("id")}
        existing_slugs = {str(product.get("slug")) for product in products if product.get("slug")}
        additions: list[tuple[sqlite3.Row, dict[str, Any]]] = []
        catalog_duplicates: list[tuple[sqlite3.Row, tuple[str, str]]] = []
        projection_holds: list[tuple[sqlite3.Row, list[str]]] = []

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM candidates
                WHERE state = 'ready_for_human_review' AND synced_catalog_id IS NULL AND run_id = ?
                ORDER BY created_at ASC, candidate_id ASC
                """
                ,
                (run_id,),
            ).fetchall()
            for row in rows:
                evidence_a = json.loads(row["evidence_a_json"]) if row["evidence_a_json"] else None
                evidence_b = json.loads(row["evidence_b_json"]) if row["evidence_b_json"] else None
                sources = json.loads(row["sources_json"] or "[]")
                try:
                    public_payload = json.loads(row["public_payload_json"])
                except json.JSONDecodeError:
                    public_payload = {}
                hold_reasons = gate_reasons(
                    str(row["recommendation"]),
                    row["confidence"],
                    evidence_a,
                    evidence_b,
                    str(row["caribbean_evidence_tier"] or "unknown"),
                    sources,
                )
                hold_reasons.extend(public_projection_reasons(public_payload))
                hold_reasons = list(dict.fromkeys(hold_reasons))
                if hold_reasons:
                    projection_holds.append((row, hold_reasons))
                    continue
                try:
                    row_app_store_ids = json.loads(row["app_store_ids_json"] or "[]")
                except json.JSONDecodeError:
                    row_app_store_ids = []
                matched = catalog_exact_match(
                    products,
                    str(row["canonical_domain"]),
                    row_app_store_ids if isinstance(row_app_store_ids, list) else [],
                )
                if matched:
                    catalog_duplicates.append((row, matched))
                    continue
                try:
                    record = self.public_record(public_payload, existing_ids, existing_slugs)
                except LedgerError as error:
                    projection_holds.append((row, [f"public projection blocked: {error}"]))
                    continue
                additions.append((row, record))
                products.append(record)
                existing_ids.add(str(record["id"]))
                existing_slugs.add(str(record["slug"]))

            for row, matched in catalog_duplicates:
                connection.execute(
                    """
                    UPDATE candidates
                    SET state = 'duplicate_catalog', duplicate_kind = ?, catalog_match_id = ?, updated_at = ?
                    WHERE candidate_id = ?
                    """,
                    (matched[0], matched[1], utc_now(), row["candidate_id"]),
                )
            for row, reasons in projection_holds:
                existing_reasons = json.loads(row["hold_reasons_json"] or "[]")
                combined_reasons = list(dict.fromkeys(existing_reasons + reasons))
                connection.execute(
                    """
                    UPDATE candidates
                    SET state = 'hold', hold_reasons_json = ?, updated_at = ?
                    WHERE candidate_id = ?
                    """,
                    (stable_json(combined_reasons), utc_now(), row["candidate_id"]),
                )

        if additions:
            catalog_payload["products"] = products
            atomic_write_json(catalog, catalog_payload)
            with self.connect() as connection:
                for row, record in additions:
                    connection.execute(
                        """
                        UPDATE candidates
                        SET state = 'synced_unlisted',
                            synced_catalog_id = ?,
                            synced_public_record_json = ?,
                            updated_at = ?
                        WHERE candidate_id = ?
                        """,
                        (
                            record["id"],
                            stable_json(record),
                            utc_now(),
                            row["candidate_id"],
                        ),
                    )
            for row, record in additions:
                self.append_event(
                    {
                        "event": "candidate_synced_unlisted",
                        "eventKey": f"candidate_synced_unlisted:{row['candidate_id']}:{run_id}:{record['id']}",
                        "candidateId": row["candidate_id"],
                        "runId": run_id,
                        "catalogId": record["id"],
                    }
                )
        for row, reasons in projection_holds:
            self.append_event(
                {
                    "event": "candidate_projection_held",
                    "eventKey": f"candidate_projection_held:{row['candidate_id']}:{run_id}",
                    "candidateId": row["candidate_id"],
                    "runId": run_id,
                    "reasons": reasons,
                }
            )

        return {
            "runId": run_id,
            "added": len(additions),
            "catalogDuplicates": len(catalog_duplicates),
            "projectionHolds": len(projection_holds),
            "catalog": str(catalog),
            "addedIds": [record["id"] for _row, record in additions],
        }

    @staticmethod
    def public_record(
        public_payload: dict[str, Any], existing_ids: set[str], existing_slugs: set[str]
    ) -> dict[str, Any]:
        name = text(public_payload.get("name"))
        website_url = text(public_payload.get("websiteUrl"))
        if not name or not website_url:
            raise LedgerError("A syncable candidate must have a public name and websiteUrl.")
        projection_reasons = public_projection_reasons(public_payload)
        if projection_reasons:
            raise LedgerError("; ".join(projection_reasons))
        base_slug = slugify(name)
        slug = base_slug
        suffix = 2
        while slug in existing_slugs or slug in existing_ids:
            slug = f"{base_slug}-{suffix}"
            suffix += 1

        record: dict[str, Any] = {
            "id": slug,
            "slug": slug,
            "name": name,
            "tagline": text(public_payload.get("tagline")),
            "description": text(public_payload.get("description")),
            "productKind": text(public_payload.get("productKind")),
            "websiteUrl": website_url,
            "country": text(public_payload.get("country")),
            "countries": safe_list(public_payload.get("countries")),
            "category": text(public_payload.get("category")),
            "industry": text(public_payload.get("industry")),
            "tags": safe_list(public_payload.get("tags")),
            "aliases": candidate_aliases(public_payload, name),
            "officialAppStoreIds": candidate_app_store_ids(public_payload),
            "logoUrl": None,
            "logoAlt": None,
            "logoWidth": None,
            "logoHeight": None,
            "screenshotUrls": [],
            "companyName": text(public_payload.get("companyName")),
            "founderNames": [],
            "caribbeanConnection": text(public_payload.get("caribbeanConnection")),
            "visibility": "unlisted",
            "publishedAt": None,
            "updatedAt": date.today().isoformat(),
        }
        if record["productKind"] not in PRODUCT_KINDS:
            raise LedgerError(f"Unsupported productKind for public projection: {record['productKind']!r}")
        leaked = catalog_has_private_fields(record)
        if leaked:
            raise LedgerError(f"Refusing to project private fields into the public catalog: {', '.join(leaked)}")
        return record

    def validate(self, catalog: Path, run_id: str | None = None) -> dict[str, Any]:
        if run_id is not None:
            run = self.require_active_run(run_id)
            if run["lifecycle_stage"] not in {"packeted", "validated"}:
                raise LedgerError(
                    f"Run {run_id!r} is at lifecycle stage "
                    f"{run['lifecycle_stage']!r}; generate its final packet before validation."
                )
            with self.connect() as connection:
                connection.execute(
                    """
                    UPDATE runs
                    SET lifecycle_stage = 'packeted'
                    WHERE run_id = ? AND finished_at IS NULL
                    """,
                    (run_id,),
                )
        payload, products = load_catalog(catalog)
        issues: list[str] = []
        public_app_store_owners: dict[str, str] = {}
        if payload.get("schemaVersion") != 2:
            issues.append("catalog schemaVersion must be 2")
        for index, product in enumerate(products):
            identifier = str(product.get("id") or product.get("name") or index)
            leaked = catalog_has_private_fields(product)
            if leaked:
                issues.append(f"{identifier}: private fields present ({', '.join(leaked)})")
            unexpected_fields = sorted(set(product) - PUBLIC_RECORD_FIELDS)
            if unexpected_fields:
                issues.append(
                    f"{identifier}: fields outside the public schema ({', '.join(unexpected_fields)})"
                )
            contact_fields = sorted(
                field
                for field in PUBLIC_CONTACT_SCAN_FIELDS
                if field in product and contains_contact_detail(product[field])
            )
            if contact_fields:
                issues.append(
                    f"{identifier}: contact details found in public fields ({', '.join(contact_fields)})"
                )
            if "status" in product:
                issues.append(f"{identifier}: legacy status field is not allowed")
            if product.get("visibility") not in ALLOWED_VISIBILITIES:
                issues.append(f"{identifier}: invalid visibility {product.get('visibility')!r}")
            product_kind = product.get("productKind")
            if not isinstance(product_kind, str) or product_kind not in PRODUCT_KINDS:
                issues.append(f"{identifier}: invalid productKind {product_kind!r}")
            try:
                if product.get("websiteUrl"):
                    canonicalize_url(product["websiteUrl"])
            except LedgerError as error:
                issues.append(f"{identifier}: {error}")
            if "aliases" in product:
                normalized_aliases = candidate_aliases(product, text(product.get("name")))
                if not isinstance(product["aliases"], list) or product["aliases"] != normalized_aliases:
                    issues.append(f"{identifier}: aliases must be unique public-safe strings")
            if "officialAppStoreIds" in product:
                normalized_app_ids = candidate_app_store_ids(product)
                if (
                    not isinstance(product["officialAppStoreIds"], list)
                    or product["officialAppStoreIds"] != normalized_app_ids
                ):
                    issues.append(
                        f"{identifier}: officialAppStoreIds must use normalized public IDs"
                    )
                for app_store_id in normalized_app_ids:
                    previous_owner = public_app_store_owners.get(app_store_id)
                    if previous_owner and previous_owner != identifier:
                        issues.append(
                            f"public catalog duplicate app-store ID: {app_store_id}"
                        )
                    else:
                        public_app_store_owners[app_store_id] = identifier

        with self.connect() as connection:
            duplicate_rows = connection.execute(
                """
                SELECT canonical_domain, COUNT(*) AS count FROM candidates
                GROUP BY canonical_domain HAVING COUNT(*) > 1
                """
            ).fetchall()
            app_store_rows = connection.execute(
                "SELECT candidate_id, app_store_ids_json FROM candidates"
            ).fetchall()
        for row in duplicate_rows:
            identity = row[0]
            issues.append(f"private ledger duplicate identity: {identity}")
        app_store_owners: dict[str, str] = {}
        for row in app_store_rows:
            try:
                app_store_ids = json.loads(row["app_store_ids_json"] or "[]")
            except json.JSONDecodeError:
                issues.append(f"{row['candidate_id']}: invalid private app-store ID JSON")
                continue
            for app_store_id in app_store_ids:
                previous_owner = app_store_owners.get(str(app_store_id))
                if previous_owner and previous_owner != row["candidate_id"]:
                    issues.append(
                        f"private ledger duplicate app-store ID: {app_store_id}"
                    )
                else:
                    app_store_owners[str(app_store_id)] = str(row["candidate_id"])

        if run_id is not None and not issues:
            with self.connect() as connection:
                connection.execute(
                    """
                    UPDATE runs
                    SET lifecycle_stage = 'validated'
                    WHERE run_id = ? AND finished_at IS NULL
                    """,
                    (run_id,),
                )
        return {
            "valid": not issues,
            "issues": issues,
            "catalog": str(catalog),
            "products": len(products),
            "lifecycleStage": "validated" if run_id is not None and not issues else None,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=DEFAULT_PRIVATE_ROOT, help="Private review ledger directory.")
    common.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG, help="Public products.json path.")
    common.add_argument(
        "--allow-dirty-catalog",
        action="store_true",
        help="Only for isolated tests using a non-production catalog fixture.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", parents=[common], help="Create the private SQLite ledger and event directories.")
    begin = commands.add_parser(
        "begin-run",
        parents=[common],
        help="Acquire the private run lock and record catalog/repository facts at run start.",
    )
    begin.add_argument("--run-id", required=True, help="Unique ID for this review run.")
    begin.add_argument(
        "--publish-unlisted",
        action="store_true",
        help=(
            "Enable coordinator-only guarded publication planning for sanitized "
            "unlisted additions."
        ),
    )
    finish = commands.add_parser(
        "finish-run",
        parents=[common],
        help="Release an active run only after ingest, packet, and validation checkpoints.",
    )
    finish.add_argument("--run-id", required=True, help="Active run ID whose lock may be released.")
    commands.add_parser("snapshot", parents=[common], help="Snapshot the current public catalog privately.")
    commands.add_parser(
        "inventory",
        parents=[common],
        help="Return safe public/private identity inventory without review notes.",
    )
    ingest = commands.add_parser(
        "ingest",
        parents=[common],
        help="Ingest one contract-versioned normalized coordinator envelope.",
    )
    ingest.add_argument("input", type=Path, help="Normalized coordinator envelope JSON file.")
    queue = commands.add_parser("queue", parents=[common], help="Write a private weekly review queue.")
    queue.add_argument("--run-id", help="Specific private run to package; defaults to the latest run.")
    sync = commands.add_parser(
        "sync-unlisted",
        parents=[common],
        help="Append eligible candidates as sanitized visibility=unlisted catalog records.",
    )
    sync.add_argument("--run-id", required=True, help="Explicit run whose eligible records may be projected.")
    prepare = commands.add_parser(
        "prepare-publication",
        parents=[common],
        help="Write a private, local-only publication plan after validation.",
    )
    prepare.add_argument("--run-id", required=True, help="Publication-enabled active run ID.")
    prepare.add_argument(
        "--attempt-id",
        help="Stable idempotency ID; defaults to <run-id>-publication.",
    )
    record = commands.add_parser(
        "record-publication",
        parents=[common],
        help="Record a terminal coordinator publication result without Git or network actions.",
    )
    record.add_argument("--run-id", required=True, help="Publication-enabled run ID.")
    record.add_argument(
        "--attempt-id",
        help="Stable idempotency ID; defaults to <run-id>-publication.",
    )
    record.add_argument(
        "--status",
        required=True,
        choices=sorted(PUBLICATION_RESULT_STATUSES),
        help="Terminal publication result.",
    )
    record.add_argument("--commit-sha", help="Local/pushed Git commit object ID, when applicable.")
    record.add_argument(
        "--deployment-commit-sha",
        help="Source commit reported by the connected Cloudflare Pages deployment.",
    )
    record.add_argument("--deployment-url", help="Public deployment URL, when applicable.")
    record.add_argument(
        "--live-catalog-sha256",
        help="SHA-256 digest calculated from the verified live catalog response body.",
    )
    record.add_argument(
        "--failure-code",
        help="Short machine-readable terminal failure category for the private receipt.",
    )
    record.add_argument(
        "--live-verified",
        action="store_true",
        help="Attest that the committed catalog was verified on the live public routes.",
    )
    commands.add_parser("validate", parents=[common], help="Validate catalog visibility and private-field boundaries.")
    return parser


def execute(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    ensure_private_storage(args.root, args.catalog, args.allow_dirty_catalog)
    ledger = ReviewLedger(args.root)
    with ledger.ledger_lock():
        if args.command == "init":
            return 0, {
                "created": ledger.initialize(),
                "root": str(ledger.root),
                "database": str(ledger.database_path),
            }

        if args.command == "sync-unlisted":
            ensure_clean_real_catalog(args.catalog, args.allow_dirty_catalog)
        ledger.initialize()
        if args.command == "begin-run":
            return 0, ledger.begin_run(
                args.catalog,
                args.run_id,
                args.allow_dirty_catalog,
                args.publish_unlisted,
            )
        if args.command == "finish-run":
            with ledger.command_lock(args.run_id):
                return 0, ledger.finish_run(args.catalog, args.run_id)
        if args.command == "snapshot":
            if ledger.read_lock():
                raise LedgerError("Use begin-run's catalog snapshot while a review run is active.")
            return 0, ledger.snapshot(args.catalog)
        if args.command == "inventory":
            active_lock = ledger.read_lock()
            if active_lock:
                with ledger.command_lock(str(active_lock["runId"])):
                    return 0, ledger.inventory(args.catalog)
            return 0, ledger.inventory(args.catalog)
        if args.command == "ingest":
            _candidates, context = ledger.ingest_context(read_json(args.input))
            with ledger.command_lock(str(context["runId"])):
                return 0, ledger.ingest(args.catalog, args.input)
        if args.command == "queue":
            active_lock = ledger.read_lock()
            if active_lock:
                target_run_id = args.run_id or str(active_lock["runId"])
                with ledger.command_lock(target_run_id):
                    return 0, ledger.queue(target_run_id)
            return 0, ledger.queue(args.run_id)
        if args.command == "sync-unlisted":
            with ledger.command_lock(args.run_id):
                return 0, ledger.sync_unlisted(args.catalog, args.run_id)
        if args.command == "prepare-publication":
            with ledger.command_lock(args.run_id):
                return 0, ledger.prepare_publication(
                    args.catalog,
                    args.run_id,
                    args.attempt_id,
                )
        if args.command == "record-publication":
            return 0, ledger.record_publication(
                args.run_id,
                args.attempt_id,
                args.status,
                args.commit_sha,
                args.deployment_commit_sha,
                args.deployment_url,
                args.live_catalog_sha256,
                args.failure_code,
                args.live_verified,
            )
        if args.command == "validate":
            active_lock = ledger.read_lock()
            if active_lock:
                active_run_id = str(active_lock["runId"])
                with ledger.command_lock(active_run_id):
                    result = ledger.validate(args.catalog, active_run_id)
            else:
                result = ledger.validate(args.catalog)
            return (0 if result["valid"] else 1), result
        raise LedgerError(f"Unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        exit_code, result = execute(args)
    except LedgerError as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps({"ok": exit_code == 0, **result}, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
