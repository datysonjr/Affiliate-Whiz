# Rollback Plan

## Content Rollback

### Unpublish a Single Post
```bash
python src/cli.py unpublish --post-id <id>
```

### Unpublish All Posts from Last N Hours
```bash
python src/cli.py unpublish --since "2h ago" --dry-run
python src/cli.py unpublish --since "2h ago" --confirm
```

### Revert a Post to Previous Version
```bash
python src/cli.py revert --post-id <id> --to-version <n>
```

## Database Rollback

### Restore from Backup
```bash
bash ops/scripts/backup_restore.sh restore --latest
```

### Restore Specific Backup
```bash
bash ops/scripts/backup_restore.sh restore --file <backup_file>
```

## Configuration Rollback

### Revert Config to Last Known Good
```bash
git checkout HEAD~1 -- config/
python src/cli.py reload-config
```

## Code Rollback

### Revert to Last Stable Release
```bash
git checkout main
git pull origin main
python src/cli.py restart
```

### Revert a Specific Feature
```bash
git revert <commit-hash>
git push origin main
python src/cli.py restart
```

## Full System Rollback

1. Enable kill switch: `python src/cli.py kill-switch --enable`
2. Restore database from backup
3. Revert code to last stable tag
4. Revert config to matching version
5. Restart all services
6. Verify health checks pass
7. Disable kill switch: `python src/cli.py kill-switch --disable`

## Prevention

- Always tag releases before deploying
- Always backup database before migrations
- Test in dry-run mode before going live
- Keep last 7 days of backups available
