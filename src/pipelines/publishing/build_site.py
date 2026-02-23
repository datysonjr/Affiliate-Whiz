"""
pipelines.publishing.build_site
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Build and deploy affiliate content sites.  Manages site scaffolding,
static site generation, deployment to hosting providers, domain
configuration, and SSL certificate provisioning.

The build stage runs first in the publishing pipeline and can be skipped
for existing sites via the ``skip_if_exists`` flag in
``config/pipelines.yaml`` (``publishing.steps[0]``).

Design references:
    - config/pipelines.yaml  ``publishing.steps[0]``  (skip_if_exists)
    - config/sites.yaml  (site definitions)
    - ARCHITECTURE.md  Section 3 (Publishing Pipeline)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, unique
from typing import Dict, List, Optional

from src.core.constants import DEFAULT_MAX_RETRIES
from src.core.errors import PublishingError
from src.core.logger import get_logger, log_event

logger = get_logger("pipelines.publishing.build_site")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


@unique
class SiteStatus(str, Enum):
    """Current status of a managed site."""

    NOT_CREATED = "not_created"
    BUILDING = "building"
    DEPLOYED = "deployed"
    LIVE = "live"
    ERROR = "error"
    MAINTENANCE = "maintenance"


@unique
class HostingProvider(str, Enum):
    """Supported hosting providers."""

    CLOUDFLARE_PAGES = "cloudflare_pages"
    NETLIFY = "netlify"
    VERCEL = "vercel"
    AWS_S3 = "aws_s3"
    CUSTOM_VPS = "custom_vps"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class SiteConfig:
    """Configuration for a managed affiliate site.

    Attributes
    ----------
    site_id:
        Unique identifier for this site.
    domain:
        Primary domain name (e.g. ``"best-widgets.com"``).
    hosting_provider:
        Where the site is deployed.
    theme:
        Site theme or template identifier.
    ssl_enabled:
        Whether SSL/TLS is configured.
    build_command:
        Shell command to build the static site.
    output_dir:
        Directory containing the built site files.
    environment:
        Environment variables for the build.
    """

    site_id: str
    domain: str
    hosting_provider: HostingProvider = HostingProvider.CLOUDFLARE_PAGES
    theme: str = "default"
    ssl_enabled: bool = False
    build_command: str = "npm run build"
    output_dir: str = "dist"
    environment: Dict[str, str] = field(default_factory=dict)


@dataclass
class BuildResult:
    """Result of a site build operation.

    Attributes
    ----------
    site_id:
        Identifier of the site that was built.
    status:
        Current site status after the operation.
    domain:
        The site's domain.
    hosting_url:
        URL where the site is accessible.
    ssl_configured:
        Whether SSL was successfully set up.
    build_duration_s:
        Time taken for the build step.
    deploy_duration_s:
        Time taken for the deployment step.
    errors:
        List of error messages if any step failed.
    built_at:
        UTC timestamp of the build.
    """

    site_id: str
    status: SiteStatus = SiteStatus.NOT_CREATED
    domain: str = ""
    hosting_url: str = ""
    ssl_configured: bool = False
    build_duration_s: float = 0.0
    deploy_duration_s: float = 0.0
    errors: List[str] = field(default_factory=list)
    built_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Build functions
# ---------------------------------------------------------------------------


def build_site(
    site_config: SiteConfig,
    *,
    skip_if_exists: bool = True,
    dry_run: bool = False,
) -> BuildResult:
    """Build a static site from configuration and deploy it.

    Orchestrates the full build lifecycle: scaffold, generate, deploy,
    configure domain, and provision SSL.  Can be skipped for existing
    sites if *skip_if_exists* is ``True``.

    Parameters
    ----------
    site_config:
        Complete site configuration.
    skip_if_exists:
        If ``True``, skip the build when the site is already deployed.
    dry_run:
        If ``True``, plan the build but do not execute side effects.

    Returns
    -------
    BuildResult
        Summary of the build and deployment operation.
    """
    log_event(
        logger,
        "build_site.start",
        site_id=site_config.site_id,
        domain=site_config.domain,
        dry_run=dry_run,
    )

    result = BuildResult(
        site_id=site_config.site_id,
        domain=site_config.domain,
    )

    # Check if site already exists
    if skip_if_exists and _check_site_exists(site_config):
        result.status = SiteStatus.LIVE
        result.hosting_url = f"https://{site_config.domain}"
        result.ssl_configured = site_config.ssl_enabled
        log_event(
            logger,
            "build_site.skipped",
            site_id=site_config.site_id,
            reason="already_exists",
        )
        return result

    if dry_run:
        result.status = SiteStatus.NOT_CREATED
        log_event(
            logger,
            "build_site.dry_run",
            site_id=site_config.site_id,
            domain=site_config.domain,
        )
        return result

    # Step 1: Build the static site
    try:
        build_start = time.monotonic()
        _execute_build(site_config)
        result.build_duration_s = round(time.monotonic() - build_start, 3)
        result.status = SiteStatus.BUILDING
    except Exception as exc:
        result.errors.append(f"Build failed: {exc}")
        result.status = SiteStatus.ERROR
        log_event(logger, "build_site.build_failed", error=str(exc))
        return result

    # Step 2: Deploy to hosting
    try:
        deploy_start = time.monotonic()
        hosting_url = deploy_to_hosting(site_config)
        result.deploy_duration_s = round(time.monotonic() - deploy_start, 3)
        result.hosting_url = hosting_url
        result.status = SiteStatus.DEPLOYED
    except PublishingError as exc:
        result.errors.append(f"Deploy failed: {exc}")
        result.status = SiteStatus.ERROR
        return result

    # Step 3: Configure domain
    try:
        configure_domain(site_config.domain, hosting_url)
    except PublishingError as exc:
        result.errors.append(f"Domain config failed: {exc}")
        # Non-fatal: site is deployed but domain may not resolve yet

    # Step 4: Setup SSL
    try:
        ssl_ok = setup_ssl(site_config.domain, site_config.hosting_provider)
        result.ssl_configured = ssl_ok
    except PublishingError as exc:
        result.errors.append(f"SSL setup failed: {exc}")
        result.ssl_configured = False

    # Final status
    if not result.errors:
        result.status = SiteStatus.LIVE
    elif result.hosting_url:
        result.status = SiteStatus.DEPLOYED  # partially successful

    log_event(
        logger,
        "build_site.complete",
        site_id=site_config.site_id,
        status=result.status.value,
        errors=len(result.errors),
        build_s=result.build_duration_s,
        deploy_s=result.deploy_duration_s,
    )
    return result


# ---------------------------------------------------------------------------
# Deployment
# ---------------------------------------------------------------------------


def deploy_to_hosting(
    site_config: SiteConfig,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> str:
    """Deploy built site files to the configured hosting provider.

    Each hosting provider has a different deployment mechanism.  This
    function dispatches to the appropriate adapter and returns the
    live URL.

    Parameters
    ----------
    site_config:
        Site configuration including hosting provider and output directory.
    max_retries:
        Maximum retry attempts for transient deployment failures.

    Returns
    -------
    str
        The URL where the site is now accessible.

    Raises
    ------
    PublishingError
        If deployment fails after all retries.
    """
    provider = site_config.hosting_provider
    log_event(
        logger,
        "deploy.start",
        provider=provider.value,
        domain=site_config.domain,
    )

    deploy_handlers = {
        HostingProvider.CLOUDFLARE_PAGES: _deploy_cloudflare,
        HostingProvider.NETLIFY: _deploy_netlify,
        HostingProvider.VERCEL: _deploy_vercel,
        HostingProvider.AWS_S3: _deploy_s3,
        HostingProvider.CUSTOM_VPS: _deploy_vps,
    }

    handler = deploy_handlers.get(provider)
    if handler is None:
        raise PublishingError(
            f"Unsupported hosting provider: {provider.value}",
            details={"provider": provider.value},
        )

    last_error: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            url = handler(site_config)
            log_event(
                logger,
                "deploy.success",
                provider=provider.value,
                url=url,
                attempt=attempt,
            )
            return url
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Deploy attempt %d/%d failed for %s: %s",
                attempt,
                max_retries,
                provider.value,
                exc,
            )

    raise PublishingError(
        f"Deployment to {provider.value} failed after {max_retries} attempts",
        details={"provider": provider.value, "last_error": str(last_error)},
        cause=last_error if isinstance(last_error, Exception) else None,
    )


def _deploy_cloudflare(config: SiteConfig) -> str:
    """Deploy to Cloudflare Pages. Stub for adapter integration."""
    logger.info("Deploying to Cloudflare Pages: %s", config.domain)
    return f"https://{config.site_id}.pages.dev"


def _deploy_netlify(config: SiteConfig) -> str:
    """Deploy to Netlify. Stub for adapter integration."""
    logger.info("Deploying to Netlify: %s", config.domain)
    return f"https://{config.site_id}.netlify.app"


def _deploy_vercel(config: SiteConfig) -> str:
    """Deploy to Vercel. Stub for adapter integration."""
    logger.info("Deploying to Vercel: %s", config.domain)
    return f"https://{config.site_id}.vercel.app"


def _deploy_s3(config: SiteConfig) -> str:
    """Deploy to AWS S3 + CloudFront. Stub for adapter integration."""
    logger.info("Deploying to AWS S3: %s", config.domain)
    return f"https://{config.site_id}.s3-website.amazonaws.com"


def _deploy_vps(config: SiteConfig) -> str:
    """Deploy to a custom VPS via rsync/SSH. Stub for adapter integration."""
    logger.info("Deploying to custom VPS: %s", config.domain)
    return f"https://{config.domain}"


# ---------------------------------------------------------------------------
# Domain and SSL configuration
# ---------------------------------------------------------------------------


def configure_domain(
    domain: str,
    hosting_url: str,
    *,
    dns_provider: Optional[str] = None,
) -> bool:
    """Configure DNS records to point the domain to the hosting URL.

    Creates or updates CNAME/A records with the configured DNS provider.
    The actual DNS API integration is delegated to the
    ``integrations.dns`` module.

    Parameters
    ----------
    domain:
        The domain name to configure.
    hosting_url:
        The hosting provider URL to point the domain to.
    dns_provider:
        Optional DNS provider override.

    Returns
    -------
    bool
        ``True`` if DNS records were configured successfully.

    Raises
    ------
    PublishingError
        If DNS configuration fails.
    """
    log_event(
        logger,
        "domain.configure.start",
        domain=domain,
        target=hosting_url,
    )

    # Extract the target hostname from the hosting URL
    target_host = hosting_url.replace("https://", "").replace("http://", "").rstrip("/")

    # DNS record configuration (stub -- delegates to integrations.dns)
    dns_record = {
        "type": "CNAME",
        "name": domain,
        "content": target_host,
        "ttl": 300,
        "proxied": True,
    }

    logger.info(
        "DNS record prepared: %s CNAME -> %s (provider: %s)",
        domain,
        target_host,
        dns_provider or "auto-detect",
    )

    log_event(
        logger,
        "domain.configure.ok",
        domain=domain,
        record_type=dns_record["type"],
    )
    return True


def setup_ssl(
    domain: str,
    hosting_provider: HostingProvider,
    *,
    force_renew: bool = False,
) -> bool:
    """Provision or verify SSL/TLS certificate for the domain.

    Most modern hosting providers (Cloudflare, Netlify, Vercel) handle
    SSL automatically.  For custom VPS deployments, this function
    triggers Let's Encrypt certificate issuance.

    Parameters
    ----------
    domain:
        The domain to secure.
    hosting_provider:
        The hosting provider (determines SSL strategy).
    force_renew:
        Force certificate renewal even if one exists.

    Returns
    -------
    bool
        ``True`` if SSL is active for the domain.

    Raises
    ------
    PublishingError
        If SSL provisioning fails.
    """
    log_event(logger, "ssl.setup.start", domain=domain, provider=hosting_provider.value)

    auto_ssl_providers = {
        HostingProvider.CLOUDFLARE_PAGES,
        HostingProvider.NETLIFY,
        HostingProvider.VERCEL,
    }

    if hosting_provider in auto_ssl_providers:
        logger.info(
            "SSL is automatically managed by %s for %s",
            hosting_provider.value,
            domain,
        )
        log_event(logger, "ssl.setup.ok", domain=domain, method="auto")
        return True

    # For custom VPS / S3, we need to provision manually
    logger.info("Provisioning SSL certificate for %s via Let's Encrypt", domain)

    # Stub: actual Let's Encrypt / certbot integration goes here
    log_event(logger, "ssl.setup.ok", domain=domain, method="letsencrypt")
    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_site_exists(site_config: SiteConfig) -> bool:
    """Check if a site has already been deployed.

    Parameters
    ----------
    site_config:
        The site configuration to check.

    Returns
    -------
    bool
        ``True`` if the site appears to be live.
    """
    # Stub: in production, this would make an HTTP request to the domain
    # or query the hosting provider's API
    logger.debug(
        "Checking if site %s exists at %s", site_config.site_id, site_config.domain
    )
    return False


def _execute_build(site_config: SiteConfig) -> None:
    """Execute the static site build command.

    Parameters
    ----------
    site_config:
        Site configuration with build command and output directory.

    Raises
    ------
    PipelineStepError
        If the build command fails.
    """
    log_event(
        logger,
        "build.execute",
        command=site_config.build_command,
        output_dir=site_config.output_dir,
    )
    # Stub: in production, this would run the build command via subprocess
    logger.info(
        "Executing build: '%s' -> '%s'",
        site_config.build_command,
        site_config.output_dir,
    )
