#!/bin/bash
set -euo pipefail
#
# data_backup.sh — Sauvegarde HORS-GIT des données du projet flashcards.
#
# Remplace le rôle de sauvegarde que jouait GitHub (git_sync.sh) une fois
# que images/, audios/ et flashcards.json ne sont plus versionnés par git.
#
# À lancer quotidiennement par cron (voir la ligne tout en bas).
# ---------------------------------------------------------------------------

# Dossier du dépôt = dossier où se trouve ce script.
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

# >>> ADAPTE CETTE DESTINATION <<<
# Idéalement un AUTRE disque / un point de montage NAS / un disque externe.
# (sur le même disque que le serveur, ça protège des erreurs mais pas d'une
#  panne disque — pour une vraie sécurité, vise un stockage distinct.)
DEST="/mnt/backup/flashcards-data"

mkdir -p "$DEST"

# Miroir incrémental. PAS de --delete : on n'efface jamais dans la sauvegarde,
# même si un fichier disparaît de la source (un backup ne doit pas propager
# une suppression accidentelle). Quitte à accumuler quelques orphelins.
rsync -a \
  "$REPO_DIR/flashcards.json" \
  "$REPO_DIR/images" \
  "$REPO_DIR/audios" \
  "$REPO_DIR/backups" \
  "$DEST/"

# Snapshot daté du JSON (minuscule) pour pouvoir remonter dans le temps.
mkdir -p "$DEST/json-history"
cp -a "$REPO_DIR/flashcards.json" \
      "$DEST/json-history/flashcards_$(date +%Y%m%d_%H%M%S).json"

# Purge des snapshots JSON de plus de 60 jours (garde l'historique léger).
find "$DEST/json-history" -name 'flashcards_*.json' -mtime +60 -delete 2>/dev/null || true

echo "$(date '+%F %T') backup OK -> $DEST"

# ---------------------------------------------------------------------------
# Installation du cron (en tant que l'utilisateur qui possède le dépôt) :
#
#   chmod +x data_backup.sh
#   crontab -e
#   # puis ajouter (sauvegarde tous les jours à 2h30, avant le sync git de 3h) :
#   30 2 * * * /root/flashcards/data_backup.sh >> /var/log/flashcards-backup.log 2>&1
# ---------------------------------------------------------------------------
