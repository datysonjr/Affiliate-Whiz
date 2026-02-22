# Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR                          │
│  ┌──────────┐  ┌───────────┐  ┌────────┐  ┌─────────┐  │
│  │Controller│  │ Scheduler │  │ Router │  │  State  │  │
│  │          │  │           │  │        │  │ Machine │  │
│  └────┬─────┘  └─────┬─────┘  └───┬────┘  └────┬────┘  │
│       │              │             │             │       │
│  ┌────┴──────────────┴─────────────┴─────────────┴────┐  │
│  │                   POLICIES                         │  │
│  │  ai_rules / posting_policy / risk_policy           │  │
│  └────────────────────────────────────────────────────┘  │
└────────────────────────┬────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
    ┌────┴────┐    ┌─────┴─────┐   ┌─────┴─────┐
    │ AGENTS  │    │ PIPELINES │   │   TOOLS   │
    │         │    │           │   │           │
    │Research │    │Offer Disc.│   │Browser    │
    │Content  │    │Content    │   │Scraper    │
    │Publish  │    │Publishing │   │LLM        │
    │Analytics│    │Optimiz.   │   │SEO        │
    │Health   │    │           │   │CMS        │
    │Recovery │    │           │   │Analytics  │
    │Traffic  │    │           │   │           │
    └────┬────┘    └─────┬─────┘   └─────┬─────┘
         │               │               │
         └───────────────┼───────────────┘
                         │
    ┌────────────────────┼────────────────────┐
    │                    │                    │
┌───┴────┐        ┌──────┴──────┐      ┌──────┴──────┐
│DOMAINS │        │INTEGRATIONS │      │    DATA     │
│        │        │             │      │             │
│Offers  │        │Affiliates   │      │Database     │
│Content │        │Hosting      │      │Migrations   │
│SEO     │        │DNS          │      │Models       │
│Publish │        │Email        │      │             │
│Analyt. │        │Proxy        │      │             │
│        │        │Storage      │      │             │
└────────┘        └─────────────┘      └─────────────┘
```

## Design Principles

### 1. Single Point of Control
All agent actions flow through `orchestrator/controller.py`. This enables:
- Rate limiting per agent/action
- Decision logging and audit trail
- Kill switches and pause controls
- Dry-run mode for testing
- Risk policy enforcement

### 2. Agent Architecture
Agents inherit from `base_agent.py` and implement:
- `plan()` - Decide next actions based on state
- `execute()` - Run actions through pipelines
- `report()` - Log outcomes and metrics

### 3. Pipeline Pattern
Pipelines are composable step sequences:
- Each step is a pure function: input -> output
- Steps can be retried independently
- Pipeline state is checkpointed for recovery

### 4. Integration Isolation
External services are wrapped in integration modules:
- Standardized interface per integration type
- Credential management via vault
- Circuit breaker pattern for resilience
- Easy to swap providers

## Node Topology

```
┌─────────────────────┐     ┌─────────────────────┐
│   oc-core-01        │     │   oc-pub-01          │
│   (Mac Mini #1)     │     │   (Mac Mini #2)      │
│                     │     │                      │
│ - Orchestrator      │────▶│ - Publishing pipeline│
│ - Research agent    │     │ - CMS integrations   │
│ - Content agent     │     │ - DNS management     │
│ - Database          │     │ - Monitoring/alerts  │
│ - Queue             │     │ - Backup runner      │
└─────────────────────┘     └──────────────────────┘
```

## Data Flow

1. **Offer Discovery**: Network APIs → Ingest → Normalize → Score → DB
2. **Content Creation**: Keywords → Outline → Draft → SEO → Links → DB
3. **Publishing**: DB → Build → CMS → Sitemap → Index Ping
4. **Optimization**: Analytics → Measure → Prune/Scale → Loop
