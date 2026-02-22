"""
pipelines.offer_discovery.normalize
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Normalize raw offer data from heterogeneous affiliate networks into a
canonical :class:`~domains.offers.models.Offer` format.  Handles field
mapping, type coercion, deduplication, and merging of records that
represent the same offer across multiple sources.

Design references:
    - config/pipelines.yaml  ``offer_discovery.steps[1]``  (deduplicate flag)
    - ARCHITECTURE.md  Section 3 (Pipeline Architecture)
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.core.errors import PipelineStepError
from src.core.logger import get_logger, log_event
from src.pipelines.offer_discovery.ingest import RawOffer

logger = get_logger("pipelines.offer_discovery.normalize")


# ---------------------------------------------------------------------------
# Field-mapping tables per source network
# ---------------------------------------------------------------------------

# Maps (source_network, canonical_field_name) -> list of candidate raw keys.
# The first match wins during extraction.
_FIELD_MAP: Dict[str, Dict[str, List[str]]] = {
    "amazon_associates": {
        "name": ["title", "productTitle", "name"],
        "merchant": ["brand", "manufacturer", "merchant"],
        "commission_rate": ["commissionRate", "commission", "rate"],
        "cookie_days": ["cookieDuration", "cookie_days"],
        "avg_order_value": ["price", "avgPrice", "avg_order_value"],
        "category": ["category", "productGroup", "browseNode"],
        "url": ["detailPageURL", "url", "link"],
        "external_id": ["asin", "offer_id", "id"],
    },
    "impact": {
        "name": ["name", "campaignName", "title"],
        "merchant": ["advertiserName", "merchant", "brand"],
        "commission_rate": ["defaultPayout", "commissionRate", "payout"],
        "cookie_days": ["cookieLength", "cookieDuration", "cookie_days"],
        "avg_order_value": ["averageOrderValue", "aov", "avg_order_value"],
        "category": ["category", "vertical", "niche"],
        "url": ["trackingLink", "url", "campaignUrl"],
        "external_id": ["id", "campaignId", "offerId"],
    },
    "cj": {
        "name": ["programName", "advertiserName", "name"],
        "merchant": ["advertiserName", "merchant", "publisher"],
        "commission_rate": ["commissionTerms", "commission", "rate"],
        "cookie_days": ["cookieDuration", "referralPeriod", "cookie_days"],
        "avg_order_value": ["averageSale", "epc", "avg_order_value"],
        "category": ["primaryCategory", "category", "niche"],
        "url": ["programUrl", "clickUrl", "url"],
        "external_id": ["ad_id", "advertiserId", "id"],
    },
    "shareasale": {
        "name": ["merchantName", "name", "programName"],
        "merchant": ["merchantName", "merchant", "company"],
        "commission_rate": ["commissionPercent", "commission", "rate"],
        "cookie_days": ["cookieLength", "cookieDays", "cookie_days"],
        "avg_order_value": ["averageSale", "avgSale", "avg_order_value"],
        "category": ["category", "merchantCategory", "niche"],
        "url": ["merchantUrl", "url", "affiliateUrl"],
        "external_id": ["dealId", "offerId", "id"],
    },
}

# Fallback field map used for unknown sources
_DEFAULT_FIELD_MAP: Dict[str, List[str]] = {
    "name": ["name", "title", "offer_name", "product_name"],
    "merchant": ["merchant", "brand", "advertiser", "company"],
    "commission_rate": ["commission_rate", "commission", "rate", "payout"],
    "cookie_days": ["cookie_days", "cookie_duration", "cookieLength"],
    "avg_order_value": ["avg_order_value", "aov", "price", "averageSale"],
    "category": ["category", "niche", "vertical", "product_group"],
    "url": ["url", "link", "tracking_url", "affiliate_url"],
    "external_id": ["id", "offer_id", "external_id"],
}


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _extract_field(
    payload: Dict[str, Any],
    candidate_keys: List[str],
    default: Any = None,
) -> Any:
    """Return the first matching value from *payload* for a list of candidate keys.

    Parameters
    ----------
    payload:
        Raw record dict from the network API.
    candidate_keys:
        Ordered list of key names to try.
    default:
        Value returned when no candidate key is present in the payload.

    Returns
    -------
    Any
        The extracted value, or *default*.
    """
    for key in candidate_keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default


def _coerce_float(value: Any, field_name: str) -> float:
    """Coerce a value to float, returning ``0.0`` on failure.

    Handles strings like ``"8%"`` by stripping the percent sign and
    converting to a decimal fraction.

    Parameters
    ----------
    value:
        Raw value from the payload.
    field_name:
        Name of the field (for logging).

    Returns
    -------
    float
        The coerced numeric value.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("$", "")
        if cleaned.endswith("%"):
            try:
                return float(cleaned[:-1]) / 100.0
            except ValueError:
                logger.debug("Could not parse percentage for %s: %r", field_name, value)
                return 0.0
        try:
            return float(cleaned)
        except ValueError:
            logger.debug("Could not coerce %s to float: %r", field_name, value)
            return 0.0
    return 0.0


def _coerce_int(value: Any, field_name: str) -> int:
    """Coerce a value to int, returning ``0`` on failure.

    Parameters
    ----------
    value:
        Raw value from the payload.
    field_name:
        Name of the field (for logging).

    Returns
    -------
    int
        The coerced integer value.
    """
    if value is None:
        return 0
    try:
        return int(float(value))
    except (ValueError, TypeError):
        logger.debug("Could not coerce %s to int: %r", field_name, value)
        return 0


# ---------------------------------------------------------------------------
# Core normalisation functions
# ---------------------------------------------------------------------------

def normalize_offer(raw_offer: RawOffer) -> Dict[str, Any]:
    """Normalize a single :class:`RawOffer` into a canonical dict.

    The returned dict has a fixed schema regardless of which network the
    offer originated from.  Downstream stages can safely construct an
    :class:`~domains.offers.models.Offer` from this dict.

    Parameters
    ----------
    raw_offer:
        An unprocessed offer from the ingest stage.

    Returns
    -------
    dict[str, Any]
        Canonical offer dict with keys: ``name``, ``merchant``,
        ``commission_rate``, ``cookie_days``, ``avg_order_value``,
        ``category``, ``url``, ``source_network``, ``external_id``,
        ``active``, ``fetched_at``, ``raw_payload``.

    Raises
    ------
    PipelineStepError
        If the raw offer is missing a usable ``name`` field after all
        candidate keys are exhausted.
    """
    source = raw_offer.source
    payload = raw_offer.raw_payload
    field_map = _FIELD_MAP.get(source, _DEFAULT_FIELD_MAP)

    name = _extract_field(payload, field_map.get("name", _DEFAULT_FIELD_MAP["name"]))
    if not name:
        raise PipelineStepError(
            f"Cannot normalize offer from '{source}': no name field found",
            step_name="normalize",
            details={"source": source, "external_id": raw_offer.external_id},
        )

    merchant = _extract_field(
        payload,
        field_map.get("merchant", _DEFAULT_FIELD_MAP["merchant"]),
        default="Unknown",
    )

    commission_raw = _extract_field(
        payload,
        field_map.get("commission_rate", _DEFAULT_FIELD_MAP["commission_rate"]),
    )
    commission_rate = _coerce_float(commission_raw, "commission_rate")
    # Normalize: if the value looks like a percentage (> 1), convert to decimal
    if commission_rate > 1.0:
        commission_rate = commission_rate / 100.0

    cookie_raw = _extract_field(
        payload,
        field_map.get("cookie_days", _DEFAULT_FIELD_MAP["cookie_days"]),
        default=30,
    )
    cookie_days = _coerce_int(cookie_raw, "cookie_days")

    aov_raw = _extract_field(
        payload,
        field_map.get("avg_order_value", _DEFAULT_FIELD_MAP["avg_order_value"]),
    )
    avg_order_value = _coerce_float(aov_raw, "avg_order_value")

    category = str(
        _extract_field(
            payload,
            field_map.get("category", _DEFAULT_FIELD_MAP["category"]),
            default="uncategorized",
        )
    ).lower().strip()

    url = str(
        _extract_field(
            payload,
            field_map.get("url", _DEFAULT_FIELD_MAP["url"]),
            default="",
        )
    )

    normalized: Dict[str, Any] = {
        "name": str(name).strip(),
        "merchant": str(merchant).strip(),
        "commission_rate": round(commission_rate, 4),
        "cookie_days": max(cookie_days, 0),
        "avg_order_value": round(avg_order_value, 2),
        "category": category,
        "url": url,
        "source_network": source,
        "external_id": raw_offer.external_id,
        "active": True,
        "fetched_at": raw_offer.fetched_at.isoformat(),
        "raw_payload": payload,
    }

    log_event(
        logger,
        "normalize.offer.ok",
        source=source,
        external_id=raw_offer.external_id,
        name=normalized["name"],
    )
    return normalized


def _offer_fingerprint(offer: Dict[str, Any]) -> str:
    """Generate a stable fingerprint for deduplication.

    Fingerprints are based on the lowercased merchant + offer name so
    that the same offer listed on multiple networks is recognized as a
    duplicate.

    Parameters
    ----------
    offer:
        A normalized offer dict.

    Returns
    -------
    str
        A hex digest string identifying this offer.
    """
    key = f"{offer.get('merchant', '').lower()}|{offer.get('name', '').lower()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def deduplicate_offers(
    offers: List[Dict[str, Any]],
    *,
    prefer_higher_commission: bool = True,
) -> List[Dict[str, Any]]:
    """Remove duplicate offers that represent the same merchant+product.

    When duplicates are found, the retained record is chosen based on
    the *prefer_higher_commission* strategy: keep the version with the
    better commission rate, preserving metadata about alternate sources.

    Parameters
    ----------
    offers:
        List of normalized offer dicts (output of :func:`normalize_offer`).
    prefer_higher_commission:
        When ``True``, keep the duplicate with the highest commission rate.
        When ``False``, keep the first occurrence encountered.

    Returns
    -------
    list[dict[str, Any]]
        Deduplicated list of offers.  Each retained offer gains an
        ``alternate_sources`` key listing the networks where it was also
        found.
    """
    seen: Dict[str, Dict[str, Any]] = {}
    duplicates_found = 0

    for offer in offers:
        fp = _offer_fingerprint(offer)

        if fp not in seen:
            offer["alternate_sources"] = []
            seen[fp] = offer
            continue

        duplicates_found += 1
        existing = seen[fp]

        # Record the alternate source
        alt_entry = {
            "source_network": offer["source_network"],
            "external_id": offer["external_id"],
            "commission_rate": offer["commission_rate"],
        }

        if (
            prefer_higher_commission
            and offer["commission_rate"] > existing["commission_rate"]
        ):
            # New version is better -- swap, but keep tracking alternates
            alternates = existing.get("alternate_sources", [])
            alternates.append({
                "source_network": existing["source_network"],
                "external_id": existing["external_id"],
                "commission_rate": existing["commission_rate"],
            })
            offer["alternate_sources"] = alternates
            offer["alternate_sources"].append(alt_entry)
            seen[fp] = offer
        else:
            existing.setdefault("alternate_sources", []).append(alt_entry)

    result = list(seen.values())

    log_event(
        logger,
        "normalize.deduplicate.complete",
        input_count=len(offers),
        output_count=len(result),
        duplicates_removed=duplicates_found,
    )
    return result


def merge_offer_data(
    existing: Dict[str, Any],
    incoming: Dict[str, Any],
    *,
    overwrite_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Merge incoming offer data into an existing normalized record.

    This is used when refreshing offer data: fields from *incoming*
    update *existing* without losing manually curated values.  Only the
    specified ``overwrite_fields`` are updated unconditionally; other
    fields are updated only if the existing value is empty or zero.

    Parameters
    ----------
    existing:
        The current canonical offer dict.
    incoming:
        New data (e.g. from a fresh ingest) for the same offer.
    overwrite_fields:
        List of field names that should always be overwritten.  Defaults
        to ``["commission_rate", "avg_order_value", "active", "url"]``
        -- the fields most likely to change between refreshes.

    Returns
    -------
    dict[str, Any]
        The merged offer dict (mutates *existing* in place and also
        returns it for convenience).
    """
    if overwrite_fields is None:
        overwrite_fields = ["commission_rate", "avg_order_value", "active", "url"]

    for field_name in overwrite_fields:
        if field_name in incoming and incoming[field_name] is not None:
            existing[field_name] = incoming[field_name]

    # Fill in blanks for non-overwrite fields
    fill_fields = ["name", "merchant", "category", "cookie_days"]
    for field_name in fill_fields:
        existing_val = existing.get(field_name)
        incoming_val = incoming.get(field_name)
        if (not existing_val or existing_val in (0, "uncategorized", "Unknown")) and incoming_val:
            existing[field_name] = incoming_val

    # Merge alternate sources without duplicating
    existing_alts = existing.get("alternate_sources", [])
    incoming_source = incoming.get("source_network", "")
    incoming_ext_id = incoming.get("external_id", "")

    already_tracked = any(
        alt.get("source_network") == incoming_source
        and alt.get("external_id") == incoming_ext_id
        for alt in existing_alts
    )
    if not already_tracked and incoming_source:
        existing_alts.append({
            "source_network": incoming_source,
            "external_id": incoming_ext_id,
            "commission_rate": incoming.get("commission_rate", 0.0),
        })
    existing["alternate_sources"] = existing_alts

    # Update the fetched_at timestamp to the most recent
    existing["fetched_at"] = incoming.get("fetched_at", existing.get("fetched_at"))

    log_event(
        logger,
        "normalize.merge.ok",
        name=existing.get("name"),
        source=incoming_source,
    )
    return existing
