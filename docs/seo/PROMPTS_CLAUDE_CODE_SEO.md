# OpenClaw Claude Code SEO Prompts

Reference prompts for Claude Code when operating on the OpenClaw repo.

---

## SEO Enforcement Prompt

```
You are updating the OpenClaw repo.

Implement strict SEO enforcement rules.

Create a publishing validator that blocks articles unless:

1. TLDR block exists at top
2. comparison table exists
3. FAQ section exists
4. at least 5 internal links exist
5. at least 3 product verdict statements exist

If any missing:
Return error: "ARTICLE FAILED OPENCLAW SEO VALIDATION"

Add this validator into publishing workflow.
```

---

## Usage

This prompt is implemented as `src/domains/seo/validator.py` and enforced
automatically in the publishing pipeline via `publish_to_cms()`.

The validator raises `ContentValidationError` with detailed failure reasons
when any required SEO block is missing from an article.
