# Startup Checklist

## Pre-Launch

### Infrastructure
- [ ] Mac Mini #1 (oc-core-01) provisioned and networked
- [ ] Mac Mini #2 (oc-pub-01) provisioned and networked
- [ ] Static IPs assigned
- [ ] UPS configured and tested
- [ ] SSD docks connected and mounted
- [ ] SSH keys exchanged between nodes

### Software Setup
- [ ] Python environment configured on both nodes
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Docker installed and running (optional)
- [ ] Database initialized and migrations run
- [ ] Redis/queue system running

### Secrets & Security
- [ ] Vault initialized with master key
- [ ] Affiliate network API keys stored in vault
- [ ] CMS credentials stored in vault
- [ ] DNS provider credentials stored in vault
- [ ] Hosting provider credentials stored in vault
- [ ] LLM API keys stored in vault
- [ ] Key rotation schedule configured

### Configuration
- [ ] `config/org.yaml` - Organization details filled in
- [ ] `config/cluster.yaml` - Node details configured
- [ ] `config/agents.yaml` - Agent settings reviewed
- [ ] `config/pipelines.yaml` - Pipeline steps configured
- [ ] `config/niches.yaml` - Target niches defined
- [ ] `config/sites.yaml` - Sites and CMS credentials mapped
- [ ] `config/providers.yaml` - LLM and service providers configured
- [ ] `config/schedules.yaml` - Run schedules set
- [ ] `config/thresholds.yaml` - Kill switch and alert thresholds set

### Observability
- [ ] Grafana dashboards imported
- [ ] Alert rules configured
- [ ] Log rotation set up
- [ ] Metrics collection running

### First Run
- [ ] Run system in dry-run mode
- [ ] Verify offer discovery pipeline
- [ ] Verify content generation pipeline
- [ ] Verify publishing pipeline (to staging)
- [ ] Verify analytics collection
- [ ] Verify alerting triggers
- [ ] Review all logs for errors

### Go Live
- [ ] Switch from dry-run to live mode
- [ ] Monitor first 24 hours closely
- [ ] Verify first affiliate links are tracking
- [ ] Confirm indexing requests are being accepted
- [ ] Set up daily check-in schedule
