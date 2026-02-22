# RUNBOOK_ACCOUNTS_KEYS.md — External Accounts & Key Vault

## Account Categories
- Domain registrar
- Hosting provider
- WordPress admin accounts
- Affiliate networks
- Analytics platforms (GSC/GA/etc.)
- CDN/DNS (if used)
- Proxy provider (if used)
- Email provider (for notifications)

## Rules
- Separate staging and production accounts where possible.
- Store all keys in approved secrets storage.
- Document ownership and recovery methods.

## Account Matrix (Template)
| Category | Provider | Owner | Access | Notes |
|---|---|---|---|---|
| Domains | TBD | TBD | Least privilege | MFA on |
| Hosting | TBD | TBD | Least privilege | MFA on |
| WordPress | TBD | TBD | Admin for 1-2 only | Rotate |
| Affiliate | TBD | TBD | As required | Follow terms |
| Analytics | TBD | TBD | Read-only to most | |

## Notifications
Use a dedicated email inbox for alerts (not personal inboxes if avoidable).
