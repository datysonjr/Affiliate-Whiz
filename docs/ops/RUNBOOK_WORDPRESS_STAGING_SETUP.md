# RUNBOOK_WORDPRESS_STAGING_SETUP.md

Goal: Set up a WordPress staging site that OpenClaw can publish to safely.

## Recommended Setup (Fast + Automatable)

Option A (simple): Managed WordPress host staging
Option B (cheap): Single VPS + WordPress + Cloudflare

## Required WP Settings

1) Create a dedicated WP user:
   - username: openclaw-publisher
   - role: Editor (Admin only if needed)
2) Enable Application Password:
   - WP Admin → Users → Profile → Application Passwords
   - generate: "openclaw_cluster"

## Required API Endpoints

- /wp-json/wp/v2/posts
- /wp-json/wp/v2/media
- /wp-json/wp/v2/categories
- /wp-json/wp/v2/tags

## Safe Publishing Defaults

- initial status = draft OR private
- only flip to publish after canary validation passes

## Minimum Plugins (Optional)

- SEO plugin (RankMath or Yoast) for meta handling
- caching plugin if needed (but keep it simple early)

## Env Vars Required

```bash
WP_STAGING_BASE_URL=https://staging.yoursite.com/wp-json/wp/v2
WP_STAGING_USER=openclaw-publisher
WP_STAGING_APP_PASSWORD=xxxx xxxx xxxx xxxx xxxx xxxx
```

These map to CMSTool config:
- `api_base_url` = WP_STAGING_BASE_URL
- `username` = WP_STAGING_USER
- `api_key` = WP_STAGING_APP_PASSWORD

## Canary Rule

Always publish only 1 post per run until you confirm:
- page renders correctly
- schema is valid
- internal links are inserted

## Verification Checklist

1. `curl -u "$WP_STAGING_USER:$WP_STAGING_APP_PASSWORD" "$WP_STAGING_BASE_URL/posts?per_page=1"` returns JSON
2. `make staging` publishes one draft post
3. Post appears in WP Admin → Posts → Drafts
4. Post content includes disclosure, TLDR block, FAQ section
