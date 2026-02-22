# WORDPRESS_STACK.md — CMS + plugins for automated affiliate sites

## Why WordPress for OpenClaw
WordPress is the simplest path to:
- auto-create and auto-update pages
- programmatic posting via REST API
- easy sitemap + caching + SEO plugins
- fast "site factory" repeatability

---

## Programmatic Publishing
Use WP REST API with:
- Application Password authentication (recommended)
- Draft-by-default policy
- Promotion step for publish (explicit)

OpenClaw should create:
- posts (draft)
- categories/tags
- featured image (optional)
- SEO metadata (via plugin integration if supported)
- internal links in content

---

## Plugin Stack (Recommended)
### MUST HAVE (v1)
1) SEO plugin (Rank Math OR Yoast)
   - sitemaps
   - metadata management
   - schema controls

2) Caching/performance (varies by host)
   - improve page speed
   - better SEO outcomes

3) Image optimization (optional v1, better v2)
   - compress images
   - lazy load

4) Security basics
   - limit login attempts, basic firewall (host-provided often enough)

### NICE TO HAVE (v2)
- Table of Contents plugin
- Schema enhancer plugin (only if needed)
- Broken link checker (careful: can be heavy)

---

## Rank Math vs Yoast (quick)
Rank Math:
- strong features, often easier for schema
Yoast:
- widely used, stable

Pick one and standardize so your automation stays consistent.

---

## Required Pages (before PRODUCTION)
- About
- Contact
- Privacy Policy
- Affiliate Disclosure
- Terms (optional)

---

## Costs (rough guidance)
WordPress hosting is usually the main cost:
- low: $5–$15 / site / month
- base: $15–$30 / site / month
- high: $30+ / site / month

Start with ONE site (staging) and grow only when signal appears.
