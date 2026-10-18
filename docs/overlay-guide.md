# Safe updates

Do not extract update ZIPs over your project. Extract a trusted update into a temporary directory, then run its bootstrap installer against the existing project. Set PRISMA_UPDATE_ZIP to the downloaded archive path in your terminal; no delivery-specific archive name is hardcoded here.

```bash
# Run from your existing project root.
update_dir="$(mktemp -d)"
unzip "$PRISMA_UPDATE_ZIP" -d "$update_dir"
bash "$update_dir/scripts/upgrade.sh" "$PRISMA_UPDATE_ZIP" --target "$PWD" --dry-run
bash "$update_dir/scripts/upgrade.sh" "$PRISMA_UPDATE_ZIP" --target "$PWD"
sudo docker compose --profile inference --profile browser up --build -d
```

The trusted bootstrap is explicitly executed by you. The overlay installer itself never executes code from the archive. It validates the predecessor, SHA-256 payload hashes, additions/modifications/deletions, path safety, regular-file types, destination symlinks, and archive limits. Modified files must match the previously delivered version. The transition uses the original manifest's exact hash and marker hash, and requires the exact predecessor version. Read the release migration guide before installation.

Current metadata files are update-manifest.json and .prisma-version. Historical cleanup paths are stored as UTF-8 hex strings only in one-time transition metadata; the installer decodes them, applies the same path checks, and verifies old hashes before deletion. Backup/application reports list resolved paths for review. Hashes establish consistency with the manifest, not authenticity; only run trusted packages.

Run the bootstrap as your normal user; it authenticates sudo and uses sudo docker internally. This keeps project files owned by your user. upgrade.sh stops existing Compose services and copies persisted PostgreSQL/Redis volumes to the new namespace when needed. Source volumes are mounted read-only and retained. A nonempty destination causes refusal rather than overwrite. File application follows only after successful copies. Root .env is never replaced; existing database initialization names may remain in your private environment because they identify the preserved data. Renaming the project folder is optional and does not change explicit Compose naming.

If copying fails, the original volumes and project files remain available; do not delete data to force the upgrade. If installation fails, caught failures restore original touched files from .overlay-backups/. Abrupt interruption can need manual recovery using rollback.json. Database migrations are separate from file rollback; 0.8.1 adds no database migration; existing additive migration history remains intact. Back up the database first; a file rollback does not reverse database migrations.

For a deliberate files-only operation in a controlled test tree, use the extracted scripts/overlay.py directly. It does not stop services or migrate volume names.

After installation, verify the changed payload:

```bash
python3 scripts/overlay.py --target . --verify-installed
```

The verification record applies to the current update payload; unchanged files are protected by the previous delivered snapshot during upgrade. Custom icon/font assets and secrets are not payload files and are preserved.
