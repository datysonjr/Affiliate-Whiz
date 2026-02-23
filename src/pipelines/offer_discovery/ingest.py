"""
pipelines.offer_discovery.ingest
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Ingest affiliate offers from multiple affiliate networks (Amazon Associates,
Impact, CJ, ShareASale, etc.).  Handles batching, pagination, and error
handling so that downstream pipeline stages always receive a clean list of
raw offer dicts.

Design references:
    - config/pipelines.yaml  ``offer_discovery.steps[0]``  (sources, batch_size)
    - ARCHITECTURE.md  Section 3 (Pipeline Architecture)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from src.core.constants import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BASE_DELAY,
    DEFAULT_RETRY_EXPONENTIAL_BASE,
    DEFAULT_RETRY_MAX_DELAY,
)
from src.core.errors import OpenClawError
from src.core.logger import get_logger, log_event

logger = get_logger("pipelines.offer_discovery.ingest")


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class IngestionError(OpenClawError):
    """Raised when an offer ingestion operation fails."""


class SourceUnavailableError(IngestionError):
    """Raised when an affiliate network source cannot be reached."""


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass
class RawOffer:
    """Unprocessed offer record as received from a network API.

    Fields are intentionally loose (``Dict[str, Any]``) because each
    network returns a different schema.  The ``normalize`` stage will
    convert these into a canonical format.
    """

    source: str
    external_id: str
    raw_payload: Dict[str, Any]
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class IngestionResult:
    """Summary of a single ingestion run across one or more sources."""

    total_offers: int = 0
    offers_by_source: Dict[str, int] = field(default_factory=dict)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_s: float = 0.0

    @property
    def success_rate(self) -> float:
        """Return the fraction of sources that completed without error."""
        total_sources = len(self.offers_by_source) + len(self.errors)
        if total_sources == 0:
            return 0.0
        return len(self.offers_by_source) / total_sources


# ---------------------------------------------------------------------------
# Source registry  (maps source name -> adapter callable)
# ---------------------------------------------------------------------------

# Each adapter is a callable(config, batch_size) -> Iterator[List[Dict]]
_SOURCE_ADAPTERS: Dict[str, Any] = {}


def register_source_adapter(source_name: str, adapter: Any) -> None:
    """Register a network-specific adapter so ``ingest_from_source`` can use it.

    Parameters
    ----------
    source_name:
        Canonical source key matching ``config/pipelines.yaml`` source names
        (e.g. ``"amazon_associates"``, ``"impact"``).
    adapter:
        A callable with signature ``(config: dict, batch_size: int) -> Iterator[List[dict]]``
        that yields paginated batches of raw offer dicts.
    """
    _SOURCE_ADAPTERS[source_name] = adapter
    log_event(logger, "source_adapter.registered", source=source_name)


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def parse_offer_data(source: str, raw_record: Dict[str, Any]) -> RawOffer:
    """Parse a single raw API record into a :class:`RawOffer`.

    Each network uses different field names for the offer identifier.  This
    function normalises just enough to build a ``RawOffer`` -- full field
    normalisation happens in the ``normalize`` stage.

    Parameters
    ----------
    source:
        Name of the affiliate network (e.g. ``"amazon_associates"``).
    raw_record:
        A single record dict as returned by the network API.

    Returns
    -------
    RawOffer
        A structured container holding the original payload alongside
        the extracted external identifier and source tag.

    Raises
    ------
    IngestionError
        If the record is missing a usable identifier field.
    """
    # Each network uses a different key for offer ID
    id_field_map: Dict[str, List[str]] = {
        "amazon_associates": ["asin", "offer_id", "id"],
        "impact": ["id", "campaignId", "offerId"],
        "cj": ["ad_id", "advertiserId", "id"],
        "shareasale": ["dealId", "offerId", "id"],
    }

    candidate_fields = id_field_map.get(source, ["id", "offer_id", "external_id"])
    external_id: Optional[str] = None

    for fld in candidate_fields:
        if fld in raw_record and raw_record[fld]:
            external_id = str(raw_record[fld])
            break

    if external_id is None:
        raise IngestionError(
            f"Cannot extract identifier from {source} record",
            details={"source": source, "available_keys": list(raw_record.keys())},
        )

    return RawOffer(
        source=source,
        external_id=external_id,
        raw_payload=raw_record,
    )


def _paginate_source(
    source: str,
    config: Dict[str, Any],
    batch_size: int,
) -> Iterator[List[Dict[str, Any]]]:
    """Yield pages of raw offer dicts from *source*.

    If a registered adapter exists for the source, it is called directly.
    Otherwise a stub page is yielded so the pipeline skeleton remains
    functional until real adapters are wired in.

    Parameters
    ----------
    source:
        Network identifier.
    config:
        Source-specific configuration (API keys, endpoints, etc.).
    batch_size:
        Maximum number of records per page.

    Yields
    ------
    list[dict]
        A batch of raw offer records.
    """
    adapter = _SOURCE_ADAPTERS.get(source)
    if adapter is not None:
        yield from adapter(config, batch_size)
    else:
        logger.warning(
            "No adapter registered for source '%s'; yielding empty batch", source
        )
        yield []


def _retry_with_backoff(
    func: Any,
    *args: Any,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_RETRY_BASE_DELAY,
    max_delay: float = DEFAULT_RETRY_MAX_DELAY,
    **kwargs: Any,
) -> Any:
    """Call *func* with exponential-backoff retry on failure.

    Parameters
    ----------
    func:
        Callable to invoke.
    max_retries:
        Maximum number of retry attempts (excludes the initial call).
    base_delay:
        Initial delay in seconds before the first retry.
    max_delay:
        Cap on the delay between retries.

    Returns
    -------
    Any
        The return value of *func* on success.

    Raises
    ------
    IngestionError
        If all retries are exhausted.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_retries + 2):  # +2: first try + retries
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt > max_retries:
                break
            delay = min(
                base_delay * (DEFAULT_RETRY_EXPONENTIAL_BASE ** (attempt - 1)),
                max_delay,
            )
            log_event(
                logger,
                "ingest.retry",
                attempt=attempt,
                max_retries=max_retries,
                delay_s=delay,
                error=str(exc),
            )
            time.sleep(delay)

    raise IngestionError(
        f"All {max_retries} retries exhausted",
        details={"last_error": str(last_exc)},
    )


def ingest_from_source(
    source: str,
    *,
    source_config: Optional[Dict[str, Any]] = None,
    batch_size: int = 100,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> List[RawOffer]:
    """Ingest all available offers from a single affiliate network.

    Pages through the source API in batches of *batch_size*, parses each
    record via :func:`parse_offer_data`, and collects them into a flat list.
    Transient failures are retried with exponential backoff.

    Parameters
    ----------
    source:
        Network identifier (e.g. ``"amazon_associates"``).
    source_config:
        Optional per-source config dict (API keys, base URLs, etc.).
        Falls back to an empty dict if not supplied.
    batch_size:
        Number of records to request per page.
    max_retries:
        Maximum retry attempts for each page fetch.

    Returns
    -------
    list[RawOffer]
        All successfully parsed offers from this source.

    Raises
    ------
    SourceUnavailableError
        If the source cannot be reached after all retries.
    """
    config = source_config or {}
    offers: List[RawOffer] = []
    page_num = 0

    log_event(logger, "ingest.source.start", source=source, batch_size=batch_size)

    try:
        for page in _retry_with_backoff(
            _paginate_source, source, config, batch_size, max_retries=max_retries
        ):
            page_num += 1
            for record in page:
                try:
                    offer = parse_offer_data(source, record)
                    offers.append(offer)
                except IngestionError as parse_err:
                    log_event(
                        logger,
                        "ingest.parse_error",
                        source=source,
                        page=page_num,
                        error=str(parse_err),
                    )
    except IngestionError:
        raise SourceUnavailableError(
            f"Source '{source}' unreachable after retries",
            details={"source": source, "pages_completed": page_num},
        )

    log_event(
        logger,
        "ingest.source.complete",
        source=source,
        total_offers=len(offers),
        pages=page_num,
    )
    return offers


def ingest_all(
    pipeline_config: Dict[str, Any],
    *,
    source_configs: Optional[Dict[str, Dict[str, Any]]] = None,
) -> tuple[List[RawOffer], IngestionResult]:
    """Ingest offers from every source listed in the pipeline configuration.

    Iterates through ``pipeline_config["sources"]`` and calls
    :func:`ingest_from_source` for each.  Individual source failures are
    captured in the result summary without halting the overall run.

    Parameters
    ----------
    pipeline_config:
        The ``offer_discovery`` ingest step config from
        ``config/pipelines.yaml``.  Expected keys: ``sources`` (list[str]),
        ``batch_size`` (int).
    source_configs:
        Optional mapping of source name to per-source config dicts.

    Returns
    -------
    tuple[list[RawOffer], IngestionResult]
        A 2-tuple of (all collected offers, run summary).
    """
    sources: List[str] = pipeline_config.get("sources", [])
    batch_size: int = pipeline_config.get("batch_size", 100)
    per_source = source_configs or {}

    result = IngestionResult(started_at=datetime.now(timezone.utc))
    all_offers: List[RawOffer] = []

    log_event(logger, "ingest.all.start", sources=sources, batch_size=batch_size)
    start = time.monotonic()

    for source in sources:
        try:
            offers = ingest_from_source(
                source,
                source_config=per_source.get(source),
                batch_size=batch_size,
            )
            all_offers.extend(offers)
            result.offers_by_source[source] = len(offers)
        except (IngestionError, SourceUnavailableError) as exc:
            result.errors.append(
                {
                    "source": source,
                    "error": str(exc),
                    "details": getattr(exc, "details", {}),
                }
            )
            log_event(
                logger,
                "ingest.source.failed",
                source=source,
                error=str(exc),
            )

    result.total_offers = len(all_offers)
    result.finished_at = datetime.now(timezone.utc)
    result.duration_s = round(time.monotonic() - start, 3)

    log_event(
        logger,
        "ingest.all.complete",
        total_offers=result.total_offers,
        sources_ok=len(result.offers_by_source),
        sources_failed=len(result.errors),
        duration_s=result.duration_s,
    )

    return all_offers, result
