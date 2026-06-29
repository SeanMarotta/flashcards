#!/bin/bash
set -euo pipefail
#
# data_backup.sh — Sauvegarde des données vers un CLOUD via rclone.
#
# Remplace le rôle de sauvegarde hors-machine que jouait GitHub, sans avoir
# besoin d'un NAS ou d'un disque externe.
#
# À lancer quotidiennement par cron (voir la ligne tout en bas).
#
#   ┌─────────────────────────────────────────────────────────────────────┐
#   │ PRÉ-REQUIS (à faire UNE FOIS) :                                      │
#   │                                                                     │
#   │ 1. Installer rclone :                                                │
#   │      sudo apt install rclone        (ou : curl https://rclone.org/  │
#   │                                       install.sh | sudo bash)        │
#   │                                                                     │
#   │ 2. Configurer un "remote" cloud :                                   │
#   │      rclone config                                                  │
#   │                                                                     │
#   │    • Backblaze B2 (le PLUS SIMPLE sur un serveur sans écran : juste │
#   │      un keyID + applicationKey, pas d'OAuth navigateur). 10 Go      │
#   │      gratuits.                                                       │
#   │    • Google Drive (15 Go) : sur un serveur sans navigateur, lance   │
#   │      `rclone authorize "drive"` depuis ton PC, puis colle le token. │
#   │                                                                     │
#   │ 3. Note le nom que tu donnes au remote et reporte-le dans REMOTE    │
#   │    ci-dessous (ex. si tu l'as nommé "gdrive", mets "gdrive:...").    │
#   │                                                                     │
#   │ 4. Teste : ./data_backup.sh                                         │
#   └─────────────────────────────────────────────────────────────────────┘
# ---------------------------------------------------------------------------

# Dossier du dépôt = dossier où se trouve ce script.
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

# >>> ADAPTE : nom_du_remote:chemin_de_destination <<<
REMOTE="gdrive:flashcards-backup"

# Options rclone communes (silencieux mais journalisable, reprend les erreurs).
RCLONE_OPTS=(--fast-list --transfers=8 --retries=3 --stats-one-line --stats=0)

echo "$(date '+%F %T') >> Sauvegarde vers $REMOTE"

# On utilise `copy` (jamais `sync`) : il AJOUTE et MET À JOUR, mais ne SUPPRIME
# jamais côté cloud. Une suppression accidentelle en local ne détruit donc pas
# la copie de sauvegarde.
rclone copy "$REPO_DIR/images"          "$REMOTE/images"  "${RCLONE_OPTS[@]}"
rclone copy "$REPO_DIR/audios"          "$REMOTE/audios"  "${RCLONE_OPTS[@]}"

# Le JSON courant (écrasé à chaque fois = toujours la dernière version).
rclone copy "$REPO_DIR/flashcards.json" "$REMOTE/"        "${RCLONE_OPTS[@]}"

# Les snapshots datés que l'app génère elle-même dans backups/ : ça nous donne
# tout l'historique du JSON dans le cloud, sans effort.
rclone copy "$REPO_DIR/backups"         "$REMOTE/backups" "${RCLONE_OPTS[@]}"

echo "$(date '+%F %T') >> Sauvegarde terminée."

# ---------------------------------------------------------------------------
# Installation du cron (utilisateur propriétaire du dépôt) :
#
#   chmod +x data_backup.sh
#   crontab -e
#   # tous les jours à 2h30, avant le sync git de 3h :
#   30 2 * * * /root/flashcards/data_backup.sh >> /var/log/flashcards-backup.log 2>&1
#
# Vérifier de temps en temps que ça tourne :
#   tail /var/log/flashcards-backup.log
#   rclone size gdrive:flashcards-backup      # taille stockée côté cloud
# ---------------------------------------------------------------------------
