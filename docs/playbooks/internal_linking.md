# Internal Linking Playbook

## Strategy

Internal linking serves three purposes:
1. **SEO**: Distribute page authority across the site
2. **User Experience**: Guide readers to related content
3. **Conversion**: Route traffic to highest-converting pages

## Link Architecture

### Hub-and-Spoke Model
```
         ┌──────────┐
         │ Hub Page  │
         │ (Roundup) │
         └─────┬─────┘
    ┌──────────┼──────────┐
    │          │          │
┌───┴───┐ ┌───┴───┐ ┌───┴───┐
│Review │ │Review │ │Review │
│Page 1 │ │Page 2 │ │Page 3 │
└───────┘ └───────┘ └───────┘
```

- Hub pages (roundups, "best of") link to all spoke pages (individual reviews)
- Spoke pages link back to the hub
- Spoke pages link to 1-2 other related spokes

### Rules

1. **Every new post gets 3-5 internal links** (both outgoing and incoming)
2. **Hub pages link to all related reviews** (updated on publish)
3. **Use descriptive anchor text** (not "click here")
4. **Link in context** (within paragraph text, not just footer lists)
5. **Prioritize linking to high-value pages** (top revenue generators)

## Automation

The internal linking engine (`src/domains/seo/internal_linking.py`) handles:
- Scanning new posts for linkable keywords
- Matching keywords to existing posts
- Inserting contextual links
- Updating hub pages with new spokes
- Reporting on orphan pages (no incoming links)

## Monitoring

- Track pages with zero internal links (orphans)
- Track pages with excessive links (>20)
- Monitor click-through on internal links
- Audit link health monthly (broken internal links)
