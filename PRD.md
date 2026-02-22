# PRD.md — OpenClaw Affiliate Marketing Automation Bot

## 1. Product Overview
OpenClaw Affiliate Bot is an automated system that:
- researches niches/products
- generates high-quality, SEO-structured content
- publishes and maintains niche blog sites
- tracks performance and revenue signals
- iterates based on analytics

Goal: build a stable, scalable pipeline capable of producing substantial affiliate revenue over time.

## 2. Users
Primary users are the operator team:
- Corey, DA/Don Anthony, Fern, David, Jamie

## 3. Outcomes
- Consistent production of publish-ready articles
- Repeatable site deployment
- Internal linking updates
- Performance monitoring and basic ROI tracking
- Automated health monitoring and recovery

## 4. Hardware Context (Current)
Cluster hardware dedicated to this project:
- 2× Mac minis (Node A, Node B)
- 2× docking stations with SSD storage
- Netgear 16-port PoE gigabit switch
- CyberPower CP1500AVRLCD3 UPS
- Dedicated Spectrum router + dedicated 1Gbps internet for cluster

## 5. Core Features (MVP)
### 5.1 Orchestration
- scheduler triggers jobs
- queue executes jobs
- persistent state tracking (jobs, runs, outputs)

### 5.2 Agents
- Master Scheduler Agent: builds daily/weekly plan and enqueues work
- Research Agent: niche/product research and brief creation
- Content Generation Agent: outlines + draft + SEO metadata
- Publishing Agent: DRY_RUN default; SAFE_STAGING supported
- Analytics Agent: fetches key signals and stores snapshots
- Health Monitor Agent: checks disk/queue/db/connectivity
- Error Recovery Agent: retries/resumes/alerts
- Traffic Routing Agent: placeholder for future expansion (e.g., CDN/edge rules, routing experiments)

### 5.3 Site Engine
- site "factory" blueprint (structure, categories, tags)
- internal link suggestions
- SEO structure blueprint (slugs, headings, schema placeholders)

### 5.4 Revenue Tracking
- basic affiliate click/conversion tracking plan (config + analytics hooks)
- ROI dashboard placeholders

## 6. Non-Goals (for now)
- No paid ad arbitrage automation
- No black-hat SEO
- No massive web scraping
- No automated creation of accounts that violates Terms

## 7. Success Metrics
- System uptime and job completion rate
- Number of publish-ready articles generated per week
- Indexation and traffic growth
- Affiliate clicks and conversions
- Time-to-recover from failures

## 8. Risks
- Platform policy violations (mitigated by compliance policies)
- Content quality and duplication risks (mitigated by quality policy and review gates)
- Credential leaks (mitigated by security runbook + least privilege)

## 9. Milestones
- MVP local DRY_RUN working
- SAFE_STAGING publishing to staging WP site
- Cluster deployment
- First production site deployed
- Weekly ops cadence (health checks + performance review)
