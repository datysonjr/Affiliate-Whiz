# config/secrets/

## Rules
- NEVER commit secrets to git.
- This directory is for documentation only.
- Actual secrets must be stored in:
  - Environment variables (loaded from .env, which is gitignored)
  - A team password manager
  - OS keychain (optional)

## Required Secrets (Environment Variables)
| Variable | Description | Required For |
|----------|-------------|--------------|
| OPENAI_API_KEY | OpenAI API key | Content generation |
| ANTHROPIC_API_KEY | Anthropic API key | Content generation |
| WP_USERNAME | WordPress admin username | Publishing |
| WP_APP_PASSWORD | WordPress application password | Publishing |
| WP_BASE_URL | WordPress site URL | Publishing |
| AFFILIATE_NETWORK_API_KEY | Affiliate network credentials | Revenue tracking |
| GSC_CREDENTIALS_JSON | Google Search Console service account | Analytics |
| GA_PROPERTY_ID | Google Analytics property ID | Analytics |

## Rotation Schedule
- API keys: quarterly or on suspicion of compromise
- WordPress passwords: quarterly
- All keys: immediately on team member departure

## See Also
- docs/ops/RUNBOOK_SECURITY.md
- docs/ops/RUNBOOK_ACCOUNTS_KEYS.md
