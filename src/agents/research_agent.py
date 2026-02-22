"""
agents.research_agent
~~~~~~~~~~~~~~~~~~~~~

The ResearchAgent handles niche research, SERP scanning, keyword research,
and competitor analysis.  It consumes configuration from ``config/niches.yaml``
and uses SEO/scraping tools to gather intelligence that feeds the content
pipeline.

Design references:
    - ARCHITECTURE.md  Section 2 (Agent Architecture)
    - config/niches.yaml       (niche definitions and seed keywords)
    - config/thresholds.yaml   (minimum keyword scores, competition caps)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.agents.base_agent import BaseAgent
from src.core.constants import AgentName, DEFAULT_MIN_OFFER_SCORE, TaskStatus
from src.core.logger import get_logger, log_event


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class KeywordCandidate:
    """A keyword discovered during research.

    Attributes:
        keyword:          The keyword phrase.
        search_volume:    Estimated monthly search volume.
        competition:      Competition score (0.0 = none, 1.0 = maximum).
        cpc:              Estimated cost-per-click in USD.
        intent:           Search intent classification (informational, commercial, etc.).
        source:           Where this keyword was discovered.
        score:            Composite viability score (0-100).
    """

    keyword: str
    search_volume: int = 0
    competition: float = 0.0
    cpc: float = 0.0
    intent: str = "informational"
    source: str = "seed"
    score: int = 0


@dataclass
class CompetitorProfile:
    """Summarised profile of a competitor site.

    Attributes:
        domain:             Competitor domain name.
        estimated_traffic:  Estimated monthly organic traffic.
        top_keywords:       Keywords the competitor ranks for.
        content_gaps:       Topics the competitor covers that we do not.
        backlink_count:     Estimated number of backlinks.
        domain_authority:   Domain authority score (0-100).
    """

    domain: str
    estimated_traffic: int = 0
    top_keywords: List[str] = field(default_factory=list)
    content_gaps: List[str] = field(default_factory=list)
    backlink_count: int = 0
    domain_authority: int = 0


@dataclass
class SERPResult:
    """A single search-engine result page entry.

    Attributes:
        position:      Rank position (1-based).
        url:           Result URL.
        title:         Page title.
        snippet:       Meta description / snippet text.
        domain:        Extracted domain name.
        is_competitor: Whether this domain is a known competitor.
    """

    position: int
    url: str
    title: str
    snippet: str = ""
    domain: str = ""
    is_competitor: bool = False


@dataclass
class ResearchPlan:
    """Output of the planning phase.

    Attributes:
        niches:          Niche identifiers to research.
        seed_keywords:   Keywords to expand upon.
        competitor_domains: Domains to analyse.
        serp_queries:    Exact queries to run through SERP scanning.
        research_depth:  How thorough the research should be (shallow/normal/deep).
    """

    niches: List[str] = field(default_factory=list)
    seed_keywords: List[str] = field(default_factory=list)
    competitor_domains: List[str] = field(default_factory=list)
    serp_queries: List[str] = field(default_factory=list)
    research_depth: str = "normal"


@dataclass
class ResearchResults:
    """Aggregated output of all research pipelines.

    Attributes:
        keywords:          Discovered keyword candidates.
        serp_results:      Raw SERP data keyed by query string.
        competitor_profiles: Analysed competitor profiles.
        content_opportunities: Topics identified as high-value content targets.
        errors:            Any errors encountered during research.
    """

    keywords: List[KeywordCandidate] = field(default_factory=list)
    serp_results: Dict[str, List[SERPResult]] = field(default_factory=dict)
    competitor_profiles: List[CompetitorProfile] = field(default_factory=list)
    content_opportunities: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent implementation
# ---------------------------------------------------------------------------

class ResearchAgent(BaseAgent):
    """Handles niche research, SERP scanning, keyword research, and competitor analysis.

    The ResearchAgent operates in three phases:

    1. **Plan** -- Reads niche configs and recent performance data to decide
       which niches, keywords, and competitors to investigate.
    2. **Execute** -- Runs the research pipelines: keyword expansion, SERP
       scanning, and competitor profiling.
    3. **Report** -- Summarises findings, scores keyword opportunities, and
       writes results for downstream agents (content generation, traffic
       routing).

    Configuration keys (from ``config/agents.yaml`` under ``research``):
        enabled:             bool  -- whether this agent is active.
        niches:              list  -- niche identifiers to research.
        max_keywords:        int   -- cap on keywords per research cycle.
        min_keyword_score:   int   -- minimum viability score to keep a keyword.
        competitor_domains:  list  -- known competitor domains.
        research_depth:      str   -- ``"shallow"`` / ``"normal"`` / ``"deep"``.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(name=str(AgentName.RESEARCH), config=config)
        self._niches: List[str] = config.get("niches", [])
        self._max_keywords: int = config.get("max_keywords", 100)
        self._min_keyword_score: int = config.get(
            "min_keyword_score", DEFAULT_MIN_OFFER_SCORE
        )
        self._competitor_domains: List[str] = config.get("competitor_domains", [])
        self._research_depth: str = config.get("research_depth", "normal")

    # ------------------------------------------------------------------
    # BaseAgent lifecycle
    # ------------------------------------------------------------------

    def plan(self) -> ResearchPlan:
        """Identify research targets based on niche config and recent performance.

        Reads niche definitions, extracts seed keywords, and determines which
        competitor domains and SERP queries to evaluate in this cycle.

        Returns:
            A :class:`ResearchPlan` specifying what to research.
        """
        log_event(self.logger, "research.plan.start", niches=self._niches)

        plan = ResearchPlan(
            niches=list(self._niches),
            seed_keywords=self._extract_seed_keywords(),
            competitor_domains=list(self._competitor_domains),
            research_depth=self._research_depth,
        )

        # Build SERP queries from seed keywords
        for keyword in plan.seed_keywords:
            plan.serp_queries.append(keyword)
            # Add commercial-intent variant
            plan.serp_queries.append(f"best {keyword}")

        log_event(
            self.logger,
            "research.plan.complete",
            seed_keywords=len(plan.seed_keywords),
            serp_queries=len(plan.serp_queries),
            competitors=len(plan.competitor_domains),
        )
        return plan

    def execute(self, plan: ResearchPlan) -> ResearchResults:
        """Run research pipelines: keyword expansion, SERP scanning, competitor analysis.

        Parameters:
            plan: The :class:`ResearchPlan` from the planning phase.

        Returns:
            A :class:`ResearchResults` with all discovered data.
        """
        results = ResearchResults()

        # --- Keyword expansion ---
        log_event(self.logger, "research.keywords.start")
        try:
            expanded = self._expand_keywords(plan.seed_keywords)
            scored = self._score_keywords(expanded)
            # Keep only keywords above the minimum score threshold
            results.keywords = [
                kw for kw in scored if kw.score >= self._min_keyword_score
            ][: self._max_keywords]
            log_event(
                self.logger,
                "research.keywords.complete",
                total_expanded=len(expanded),
                above_threshold=len(results.keywords),
            )
        except Exception as exc:
            results.errors.append(f"Keyword expansion failed: {exc}")
            self.logger.error("Keyword expansion failed: %s", exc)

        # --- SERP scanning ---
        log_event(self.logger, "research.serp.start", query_count=len(plan.serp_queries))
        for query in plan.serp_queries:
            if self._check_dry_run(f"SERP scan for '{query}'"):
                continue
            try:
                serp_entries = self._scan_serp(query)
                results.serp_results[query] = serp_entries
            except Exception as exc:
                results.errors.append(f"SERP scan failed for '{query}': {exc}")
                self.logger.error("SERP scan failed for '%s': %s", query, exc)

        # --- Competitor analysis ---
        log_event(
            self.logger,
            "research.competitors.start",
            domain_count=len(plan.competitor_domains),
        )
        for domain in plan.competitor_domains:
            if self._check_dry_run(f"competitor analysis for '{domain}'"):
                continue
            try:
                profile = self._analyse_competitor(domain)
                results.competitor_profiles.append(profile)
            except Exception as exc:
                results.errors.append(f"Competitor analysis failed for '{domain}': {exc}")
                self.logger.error("Competitor analysis failed for '%s': %s", domain, exc)

        # --- Content opportunity identification ---
        results.content_opportunities = self._identify_content_opportunities(results)

        return results

    def report(self, plan: ResearchPlan, result: ResearchResults) -> Dict[str, Any]:
        """Log research findings and return a structured summary.

        Parameters:
            plan:   The research plan.
            result: The research results.

        Returns:
            A summary dict for the orchestrator's audit log.
        """
        report_data: Dict[str, Any] = {
            "niches_researched": plan.niches,
            "keywords_found": len(result.keywords),
            "top_keywords": [
                {"keyword": kw.keyword, "score": kw.score, "volume": kw.search_volume}
                for kw in sorted(result.keywords, key=lambda k: k.score, reverse=True)[:10]
            ],
            "serp_queries_run": len(result.serp_results),
            "competitors_analysed": len(result.competitor_profiles),
            "content_opportunities": len(result.content_opportunities),
            "errors": result.errors,
        }

        self._log_metric("research.keywords.found", len(result.keywords))
        self._log_metric("research.serp_queries.run", len(result.serp_results))
        self._log_metric("research.competitors.analysed", len(result.competitor_profiles))
        self._log_metric("research.opportunities.found", len(result.content_opportunities))
        self._log_metric("research.errors", len(result.errors))

        if result.errors:
            self.logger.warning(
                "Research completed with %d error(s).", len(result.errors)
            )

        log_event(
            self.logger,
            "research.report.complete",
            keywords=len(result.keywords),
            opportunities=len(result.content_opportunities),
        )
        return report_data

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_seed_keywords(self) -> List[str]:
        """Pull seed keywords from niche configuration.

        Returns:
            A flat list of seed keyword strings.
        """
        seeds: List[str] = []
        niche_keywords = self.config.get("seed_keywords", {})

        if isinstance(niche_keywords, list):
            seeds.extend(niche_keywords)
        elif isinstance(niche_keywords, dict):
            for niche in self._niches:
                niche_seeds = niche_keywords.get(niche, [])
                if isinstance(niche_seeds, list):
                    seeds.extend(niche_seeds)

        self.logger.debug("Extracted %d seed keywords from config.", len(seeds))
        return seeds

    def _expand_keywords(self, seed_keywords: List[str]) -> List[KeywordCandidate]:
        """Expand seed keywords into a broader candidate list.

        In production this calls the SEO tool's keyword expansion API.
        The scaffold returns candidates built from seed modifiers.

        Parameters:
            seed_keywords: Base keywords to expand.

        Returns:
            A list of :class:`KeywordCandidate` instances.
        """
        candidates: List[KeywordCandidate] = []
        modifiers = ["best", "top", "review", "vs", "alternative", "how to", "guide"]

        for seed in seed_keywords:
            # Include the seed itself
            candidates.append(
                KeywordCandidate(keyword=seed, source="seed")
            )
            # Generate modifier variants
            for mod in modifiers:
                candidates.append(
                    KeywordCandidate(
                        keyword=f"{mod} {seed}",
                        source="modifier_expansion",
                    )
                )

        self.logger.info("Expanded %d seeds into %d candidates.", len(seed_keywords), len(candidates))
        return candidates

    def _score_keywords(self, candidates: List[KeywordCandidate]) -> List[KeywordCandidate]:
        """Score each keyword candidate on a composite viability metric.

        The score combines search volume, competition, CPC, and intent
        into a 0-100 integer.  In production, real metrics would come from
        the SEO tool; the scaffold uses heuristic defaults.

        Parameters:
            candidates: Unscored keyword candidates.

        Returns:
            The same list with ``score`` fields populated.
        """
        for candidate in candidates:
            # Heuristic: seeds score higher, commercial intent scores higher
            base_score = 50
            if candidate.source == "seed":
                base_score += 10
            if candidate.intent in ("commercial", "transactional"):
                base_score += 15
            if candidate.search_volume > 1000:
                base_score += 10
            if candidate.competition < 0.3:
                base_score += 10
            if candidate.cpc > 2.0:
                base_score += 5
            candidate.score = min(base_score, 100)

        return candidates

    def _scan_serp(self, query: str) -> List[SERPResult]:
        """Run a SERP scan for the given query.

        In production this calls the SEO tool or scraper tool.  The scaffold
        returns an empty result list as a placeholder.

        Parameters:
            query: The search query to scan.

        Returns:
            A list of :class:`SERPResult` entries.
        """
        self.logger.debug("Scanning SERP for query: %s", query)
        # Placeholder -- real implementation uses SEOTool.check_serp()
        return []

    def _analyse_competitor(self, domain: str) -> CompetitorProfile:
        """Analyse a competitor domain.

        In production this calls scraper and SEO tools to gather traffic
        estimates, keyword data, and content inventory.

        Parameters:
            domain: The competitor domain to analyse.

        Returns:
            A :class:`CompetitorProfile` with gathered data.
        """
        self.logger.debug("Analysing competitor domain: %s", domain)
        # Placeholder -- real implementation uses ScraperTool + SEOTool
        return CompetitorProfile(domain=domain)

    def _identify_content_opportunities(
        self, results: ResearchResults
    ) -> List[Dict[str, Any]]:
        """Cross-reference keywords, SERP data, and competitor gaps to find opportunities.

        Parameters:
            results: Aggregated research data.

        Returns:
            A list of opportunity dicts, each with ``keyword``, ``reasoning``,
            and ``priority``.
        """
        opportunities: List[Dict[str, Any]] = []

        for kw in results.keywords:
            # Keywords with high score and low competition are prime targets
            if kw.score >= 60 and kw.competition < 0.5:
                opportunities.append({
                    "keyword": kw.keyword,
                    "score": kw.score,
                    "competition": kw.competition,
                    "reasoning": "High viability score with low competition.",
                    "priority": 100 - kw.score,  # Lower number = higher priority
                })

        # Check for competitor content gaps
        for profile in results.competitor_profiles:
            for gap in profile.content_gaps:
                opportunities.append({
                    "keyword": gap,
                    "score": 55,
                    "competition": 0.3,
                    "reasoning": f"Content gap identified from competitor {profile.domain}.",
                    "priority": 40,
                })

        opportunities.sort(key=lambda o: o["priority"])
        self.logger.info("Identified %d content opportunities.", len(opportunities))
        return opportunities
