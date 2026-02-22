# Daily Operations Runbook

## Morning Check (9:00 AM)

### 1. System Health
- [ ] Check both nodes are online and responsive
- [ ] Review overnight error logs: `tail -100 logs/openclaw.log`
- [ ] Check queue depth - should be near zero from overnight processing
- [ ] Verify database connectivity

### 2. Publishing Review
- [ ] Count posts published in last 24 hours
- [ ] Spot-check 2-3 published posts for quality
- [ ] Verify affiliate links are resolving correctly
- [ ] Check indexing status of recent posts

### 3. Revenue Check
- [ ] Review affiliate network dashboards for yesterday's earnings
- [ ] Compare to 7-day rolling average
- [ ] Flag any anomalies (>20% deviation)

### 4. Pipeline Status
- [ ] Verify offer discovery pipeline ran successfully
- [ ] Check content pipeline output queue
- [ ] Confirm publishing pipeline is on schedule

## Afternoon Check (3:00 PM)

### 1. Performance
- [ ] Review Grafana dashboards for any alerts
- [ ] Check LLM API costs for the day
- [ ] Monitor disk space on both nodes

### 2. Content Queue
- [ ] Review content queue depth
- [ ] Ensure tomorrow's content is staged
- [ ] Check for any content stuck in error state

## End of Day (6:00 PM)

### 1. Wrap-Up
- [ ] Acknowledge any outstanding alerts
- [ ] Review and clear any quarantined items
- [ ] Confirm backup ran successfully
- [ ] Note any issues for next day in team log
