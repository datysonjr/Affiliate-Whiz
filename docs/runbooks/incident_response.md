# Incident Response Runbook

## Severity Levels

| Level | Description | Response Time | Examples |
|-------|------------|---------------|----------|
| P1 | System down / Revenue impact | Immediate | All publishing stopped, DB down, affiliate links broken |
| P2 | Degraded performance | < 1 hour | One pipeline failing, high error rate, slow publishing |
| P3 | Minor issue | < 4 hours | Single site issue, non-critical alert, cosmetic problem |

## Immediate Steps (All Incidents)

1. **Assess** - What is broken? What is the blast radius?
2. **Communicate** - Log the incident in the team channel
3. **Contain** - Use kill switch if needed: `python src/cli.py kill-switch --enable`
4. **Investigate** - Check logs, metrics, recent deployments

## Specific Scenarios

### Revenue Drop (>20% day-over-day)

1. Check affiliate network status pages
2. Verify affiliate links are resolving (not 404/redirect loops)
3. Check Google Search Console for ranking drops
4. Review recent content changes or site issues
5. Check if any offers were discontinued

### Publishing Pipeline Failure

1. Check CMS connectivity: `python src/cli.py health --check cms`
2. Review publishing agent logs
3. Check for CMS plugin updates or changes
4. Verify hosting provider status
5. Try publishing a test post manually

### Indexing Stall

1. Check Google Search Console for crawl errors
2. Verify sitemap is accessible and valid
3. Check robots.txt hasn't been modified
4. Review recent changes to site structure
5. Submit manual indexing requests for critical pages

### Node Failure

1. Check physical hardware (power, network, display)
2. SSH into node if possible
3. Check system logs: `journalctl -xe`
4. If oc-core-01 is down, publishing can continue from queue
5. If oc-pub-01 is down, content generation continues but publishing stops
6. Follow `docs/runbooks/rollback_plan.md` if needed

### Proxy Ban / Rate Limit

1. Check proxy pool health: `python src/cli.py health --check proxy`
2. Rotate to fresh proxy set
3. Reduce scraping frequency
4. Review which targets triggered the ban
5. Add problematic targets to cool-down list

## Post-Incident

1. Write incident summary (what, when, impact, resolution)
2. Identify root cause
3. Create action items to prevent recurrence
4. Update runbooks if needed
5. Review alerting - did we catch it fast enough?
