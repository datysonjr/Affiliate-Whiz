# RUNBOOK_VENDOR_SELECTION.md — Choosing WP Host + Plugins + Registrar

## Goal
Select vendors that:
- are stable and reputable
- support staging → production workflows
- allow programmatic automation (especially publishing)
- keep costs predictable

This runbook is for the OpenClaw affiliate automation bot only.

---

## Part 1 — WordPress Hosting (Primary decision)

### Must-Have Requirements (Non-negotiable)
1) **SSL / HTTPS** supported
2) **Staging site** supported (or easy to create)
3) **WordPress REST API works reliably**
4) **Backups** available (daily at minimum)
5) **Good performance** (caching, CDN optional)
6) **Reasonable upgrade path** (as traffic grows)

### Strongly Preferred
- One-click WordPress install
- Easy credentials rotation
- Malware scanning / basic firewall
- Clear resource limits (avoid surprise throttling)

### Red Flags
- No backups or paid-only backups with poor control
- Aggressive limits that break automation (rate limits, blocked REST)
- Unclear policies about "automated posting"
- Cheap hosts that constantly go down

### Evaluation Checklist (Score 0–2 each)
- [ ] Staging environment (0/1/2)
- [ ] Backups + restore (0/1/2)
- [ ] Performance (0/1/2)
- [ ] REST API reliability (0/1/2)
- [ ] Support quality (0/1/2)
- [ ] Cost predictability (0/1/2)
- [ ] Easy scale (0/1/2)

**Minimum pass:** 10/14

### Cost Guidance
- Start with 1 staging WP site + 1 production WP site.
- Expect: $10–$30/mo per site early.
- Upgrade only when you have ranking/traffic signals.

---

## Part 2 — SEO Plugin (Rank Math vs Yoast)

### Selection Criteria
- Sitemaps enabled and configurable
- Easy metadata fields
- Schema control (Article/FAQ) without complexity
- Doesn't break REST publishing workflows
- Widely used and stable updates

### Standardization Rule
Pick ONE plugin and standardize:
- same settings
- same metadata strategy
- same schema approach
This prevents automation edge cases.

### Default Recommendation
Either is fine. Choose the team's preference and lock it in:
- Rank Math: feature-rich
- Yoast: widely used + stable

---

## Part 3 — Domain Registrar

### Must-Have Requirements
- Strong security (MFA)
- Easy DNS management
- Transparent renewal pricing
- API access is nice but not required initially

### Preferred
- Simple domain transfer
- Clear ownership records
- Good support

### Red Flags
- predatory upsells
- confusing DNS UI
- poor account recovery

### DNS Strategy
Use one of:
- Registrar DNS (simple, v1)
- Cloudflare DNS (more powerful, API-friendly, optional v2)

---

## Part 4 — Vendor Decision Process (How we choose)
1) Shortlist 2–3 WP hosts
2) Spin up a staging site on the top candidate
3) Test OpenClaw SAFE_STAGING publishing:
   - create draft post
   - set category
   - upload 1 image
   - confirm sitemap updates
4) If successful and stable → choose host
5) Lock plugin set + standard config
6) Document in `docs/stack/WORDPRESS_STACK.md` and `config/sites/*.yaml`

---

## Part 5 — "Minimum Viable Vendor Stack" (v1)
- WP host with staging
- 1 SEO plugin (Rank Math OR Yoast)
- caching enabled
- 1 domain registrar with MFA
- optional: Cloudflare (free) later
