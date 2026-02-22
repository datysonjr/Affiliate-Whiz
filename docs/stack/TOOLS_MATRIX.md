# TOOLS_MATRIX.md — OpenClaw Affiliate Bot (Friend Group)

One-page matrix of tools/services we use now or may adopt later.

Legend:
- Node mapping:
  - A = Node A (oc-core-01) control plane
  - B = Node B (oc-work-01) work plane
  - Both = runs/installed on both
  - Cloud = managed service
- Cost ranges are rough planning estimates.

| Tool / Service | Purpose (Use Case) | Cost (Low/Base/High) | API / Programmatic Features | Node Mapping |
|---|---|---:|---|---|
| GitHub | Source control, CI hooks, repo collaboration | $0 / $4–$10 user / enterprise | Webhooks, Actions CI, API | Cloud |
| Claude Code | Repo generation + iterative coding from specs | (varies by plan) | Code generation, repo editing | Operator laptop / Both |
| Docker + Docker Compose | Consistent runtime across nodes | $0 | CLI automation, compose files | Both |
| Python 3.11+ | Core runtime for OpenClaw | $0 | Full programmatic | Both |
| SQLite (v1) | Local-first DB for jobs/artifacts | $0 | Standard DB access | A (primary) |
| Postgres (v2+) | Robust DB for multi-node production | $0 self-host / $15–$100+ managed | SQL + libraries, migrations | A (or Cloud) |
| Redis (v2+) | Durable distributed queue / cache | $0 self-host / $5–$50+ managed | Pub/sub, queues, caching | A (or Cloud) |
| WordPress | CMS for automated site/page/post creation | Hosting cost | REST API for posts/media/users | Cloud |
| WP Application Passwords | Auth method for WP REST | $0 | Token-based auth for API | Cloud |
| Rank Math OR Yoast | SEO metadata + sitemaps + schema controls | $0–$8 / $8–$25 / $25+ | Some programmatic hooks; mostly WP-level config | Cloud |
| Caching (host plugin or built-in) | Speed → better UX/SEO | $0 / included / $5–$20 | Limited APIs; config via WP | Cloud |
| Image optimization plugin (optional) | Compress/optimize media assets | $0 / $5–$20 / $20+ | Usually plugin-level | Cloud |
| Cloudflare (optional) | DNS + CDN + caching | $0 / $20 / $200+ | Strong API for DNS, cache purge, rules | Cloud |
| Domain Registrar | Own domains + DNS | ~$1/mo per domain | Varies by registrar | Cloud |
| Google Search Console | Indexing + query/click data | $0 | API available | Cloud |
| Google Analytics (GA4) | Sessions + engagement | $0 | APIs/Measurement Protocol | Cloud |
| Affiliate Network Dashboards | Revenue + conversions | $0 | Some networks have APIs | Cloud |
| Uptime monitoring (optional) | Alerts on downtime | $0 / $10 / $50+ | APIs vary | Cloud |
| Secrets manager (optional) | Store keys safely | $0–$10 / $10–$50 / enterprise | API-based secret retrieval | Cloud/Both |
| UPS USB monitoring (optional) | Graceful shutdown on power loss | $0 | Varies by UPS tooling | A |
| Netgear switch mgmt (if managed) | Port control/visibility | $0–$ | Varies | Physical |
| Backups (scripts + offsite storage) | Recovery + DR | $0 local / $5–$30 / $30+ | CLI + storage APIs | A (primary) |
| Email alerts (optional) | Notify team on issues | $0 / $10 / $30+ | SMTP / provider APIs | A |
