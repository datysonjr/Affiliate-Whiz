# ADR 0002: Hosting Strategy

## Status
Accepted

## Context
We need a hosting strategy for affiliate sites that balances cost, performance, and scalability. Sites need to load fast (Core Web Vitals), support SSL, and handle moderate traffic.

## Decision

### Primary: Cloudflare Pages
- Free tier supports 500 builds/month
- Global CDN with excellent performance
- Free SSL
- Easy DNS management via Cloudflare

### Secondary: Vercel
- Free tier for static and SSR sites
- Excellent developer experience
- Good for headless CMS frontends

### Self-hosted WordPress: Managed VPS
- For sites requiring WordPress backend
- Use lightweight hosting providers
- Cloudflare CDN in front for performance

### DNS: Cloudflare
- Free DNS management
- DDoS protection included
- Easy API for automated domain management

## Consequences
- Free tiers limit the number of builds/deployments per month
- Cloudflare Pages requires static or JAMstack architecture
- WordPress sites need separate hosting management
- All sites benefit from Cloudflare CDN regardless of backend
