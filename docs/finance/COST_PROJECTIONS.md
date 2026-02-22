# COST_PROJECTIONS.md — OpenClaw Affiliate Bot (Monthly cost ranges)

These are rough planning ranges. Actual costs depend on:
- article volume
- LLM choice (cloud vs local)
- number of sites/domains
- hosting tier

---

## Fixed-ish Costs (Cluster)
- Spectrum internet dedicated: (enter your monthly)
- Electricity: (enter estimate)
- Domains: typically $10–$15/year each (~$1/month each)

---

## Variable Costs

### 1) WordPress Hosting
Per site per month:
- Low:  $5–$15
- Base: $15–$30
- High: $30–$60+

Start with:
- 1 staging site
- 1 production site

---

### 2) LLM Usage (Cloud)
Depends on:
- tokens per article
- number of articles per day
- number of rewrites

Budget approach:
- set a hard monthly cap (e.g., $200–$1,000)
- enforce max articles/day

---

### 3) Optional Services
- Email notifications (often free/cheap)
- CDN/DNS (Cloudflare free tier is often enough)
- Rank tracking tools (can be expensive; optional)

---

## Example Scenarios (Planning)
### Scenario A — Minimal (1 site, low volume)
- 1 WP host: $10–$30/mo
- LLM: $100–$300/mo
- Domains: ~$1–$3/mo
Total: ~$111–$333/mo (+ internet)

### Scenario B — Growth (3–5 sites)
- WP hosts: $45–$150/mo
- LLM: $300–$1,200/mo
- Domains: ~$5–$10/mo
Total: ~$350–$1,360/mo (+ internet)

### Scenario C — Scale (10+ sites)
- WP hosts: $150–$600/mo
- LLM: $1,000–$5,000/mo (unless local)
- Domains: $10–$20/mo
Total: ~$1,160–$5,620/mo (+ internet)

---

## Cost Control Levers (Most Important)
1) cap articles/day
2) DRY_RUN until stable
3) staging-first publishing
4) expand winning niches, not random new sites
5) cache LLM outputs to avoid re-paying
