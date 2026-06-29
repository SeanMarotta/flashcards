#!/bin/bash
set -euo pipefail
#
# setup_prevention.sh — PHASE B : ne plus versionner les données.
#
# Détache images/, audios/, flashcards.json du suivi git (SANS les supprimer
# du disque) et les ajoute à .gitignore. À partir de là, le `git add .` du
# cron git_sync.sh n'embarque plus que le CODE -> le dépôt cesse de grossir.
#
# Idempotent : peut être relancé sans danger.
# Risque : faible (ne réécrit PAS l'historique).
#
# PRÉ-REQUIS : avoir lancé une sauvegarde des données (data_backup.sh) avant.
# ---------------------------------------------------------------------------
cd "$(cd "$(dirname "$0")" && pwd)"

PATHS=(images audios flashcards.json flashcards.json.lock)

echo ">> Détache les données du suivi git (gardées sur le disque, option --cached)..."
git rm -r --cached --ignore-unmatch "${PATHS[@]}"

echo ">> Met à jour .gitignore (idempotent)..."
touch .gitignore
for p in 'images/' 'audios/' 'flashcards.json' 'flashcards.json.lock'; do
  grep -qxF "$p" .gitignore || echo "$p" >> .gitignore
done

echo ">> Commit + push..."
git add .gitignore
if git commit -m "Ne plus versionner les données (images/audios/json), code uniquement"; then
  git push
else
  echo "(rien à committer — déjà fait ?)"
fi

echo
echo "OK. Le dépôt ne grossira plus avec les données."
echo "ATTENTION sur tes AUTRES clones : ne fais PAS un simple 'git pull' (il"
echo "pourrait supprimer les images locales devenues non suivies). Re-clone."
