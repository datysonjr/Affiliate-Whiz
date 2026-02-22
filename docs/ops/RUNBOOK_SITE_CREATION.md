# RUNBOOK_SITE_CREATION.md — Automated Site Creation Template

This defines the correct process for creating a new OpenClaw site.

---

## Step 1 — Register domain

Requirements:

- short and readable
- niche-relevant
- avoid spammy phrasing

---

## Step 2 — Deploy WordPress

Minimum setup:

- hosting active
- SSL enabled
- admin account created
- REST API reachable

---

## Step 3 — Install required plugins

Required:

- SEO plugin (RankMath or Yoast)
- caching plugin
- sitemap enabled

Optional:

- table of contents plugin
- image optimization plugin

---

## Step 4 — Required pages

Create:

- About
- Contact
- Privacy Policy
- Affiliate Disclosure

Never launch without these.

---

## Step 5 — Configure OpenClaw

Add site entry to:

```
config/sites/sites.yaml
```

Add WordPress profile.

Test API auth.

---

## Step 6 — SAFE_STAGING publish test

Publish:

- 1 draft article

Verify:

- formatting clean
- categories correct
- internal links work

Only then allow production posting.
