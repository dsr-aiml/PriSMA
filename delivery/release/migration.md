# Upgrade from 0.8.5 to 0.8.6

Finish active jobs first. This overlay targets the exact shipped 0.8.5 installation. No database migration or .env change is needed.

```bash
cd ~/Desktop/Codes/Kritical
PRISMA_UPDATE_ZIP="$HOME/Downloads/prisma-0.8.6.zip"
prisma_update_dir="$(mktemp -d)"

unzip "$PRISMA_UPDATE_ZIP" -d "$prisma_update_dir" &&
bash "$prisma_update_dir/scripts/upgrade.sh" "$PRISMA_UPDATE_ZIP" --target "$PWD" --dry-run &&
bash "$prisma_update_dir/scripts/upgrade.sh" "$PRISMA_UPDATE_ZIP" --target "$PWD" &&
sudo docker compose --profile inference --profile browser up --build -d

cat .prisma-version
sudo docker compose ps
python3 scripts/overlay.py --target "$PWD" --verify-installed
```

Run the installer as your normal user; Docker subprocesses alone are elevated. The installer verifies predecessor hashes, refuses changes to touched local source files, and keeps backups. Existing settings, user assets, accounts, saved reports/chats, named volumes and models are preserved.

After services are healthy, reload the app and use Reanalyse on the original saved report. XML sources may remain selected. The action creates a new report and keeps the earlier report intact. If still running 0.8.4, apply the supplied 0.8.5 overlay first.
