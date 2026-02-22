# RUNBOOK_CONTENT_QUALITY_FILTER.md

OpenClaw Affiliate Automation System

Purpose: Defines automatic quality rules that MUST be satisfied before ANY article is allowed to publish.

This protects the system from:

- thin content penalties
- low trust signals
- indexing suppression
- algorithmic demotion

Garbage content is worse than no content.

---

## Core Principle

OpenClaw does NOT publish everything it generates.

**Generation does not equal approval.**

Publishing is a gated process.

---

## Required Quality Checks

All must pass.

### 1. Structure Validation

Article MUST include:

- quick answer block
- comparison table
- 3+ product sections
- FAQ section
- final recommendation block
- internal links

If ANY missing: **BLOCK PUBLISH**

### 2. Word Count Threshold

Reject if:

```
< 1,100 words
```

Ideal:

```
1,500–2,500 words
```

### 3. Affiliate Density Check

Reject if:

- affiliate links appear before introduction
- affiliate links exceed safe ratio
- affiliate links inserted unnaturally

Too many links → trust collapse.

### 4. Repetition Detection

Reject if:

- duplicate paragraphs
- repeated sentence patterns
- obvious template loops

### 5. Readability Check

Reject if:

- paragraphs > 8 lines
- sentences extremely long
- excessive filler phrases

### 6. Topic Coverage Check

Reject if:

- no buyer decision guidance
- no comparison logic
- no scenario recommendations

Articles must HELP decision.

### 7. Internal Linking Check

Reject if:

```
internal_links < 3
```

---

## Auto-Fix Strategy

If article fails:

Agent must:

1. attempt rewrite once
2. re-check quality
3. if still failing → store for manual review

Never loop infinite rewrites.

---

## Final Rule

Publishing low-quality content:

**damages ranking faster than publishing nothing.**
