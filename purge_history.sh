#!/bin/bash
set -euo pipefail
#
# purge_history.sh — PHASE A : purger les données de TOUT l'historique git
#                    pour récupérer ~1,7 Go dans .git.
#
# ⚠️ RÉÉCRIT L'HISTORIQUE et nécessite un FORCE-PUSH. Opération sensible.
# ⚠️ À lancer SUR LE SERVEUR (/root/flashcards), APRÈS :
#       1. avoir gelé le cron git_sync.sh,
#       2. avoir lancé data_backup.sh,
#       3. avoir exécuté setup_prevention.sh (Phase B).
#
# Le force-push final est volontairement laissé MANUEL (ce script ne le fait
# pas) : tu vérifies la nouvelle taille, puis tu lances la commande affichée.
# ---------------------------------------------------------------------------
cd "$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(pwd)"

echo "Dépôt        : $REPO_DIR"
echo "Taille .git  : $(du -sh .git | cut -f1) (avant)"
echo
read -rp "Cron gelé + données ET .git sauvegardés + Phase B faite ? [oui/non] " ok
[ "$ok" = "oui" ] || { echo "Annulé."; exit 1; }

# 0. Filet de sécurité supplémentaire : archive du .git actuel.
echo ">> Archive de sécurité du .git -> ../flashcards-git-backup-*.tar.gz"
tar czf "../flashcards-git-backup-$(date +%F-%H%M).tar.gz" .git

# 1. Outil de réécriture.
if ! command -v git-filter-repo >/dev/null 2>&1; then
  echo ">> Installation de git-filter-repo..."
  pip install git-filter-repo || {
    echo "Échec. Installe-le manuellement : pip install git-filter-repo"
    echo "(ou : sudo apt install git-filter-repo)"; exit 1; }
fi

# 2. Suppression des données de TOUT l'historique (toutes branches).
echo ">> Réécriture de l'historique (suppression images/audios/json)..."
git filter-repo --invert-paths \
  --path images --path audios \
  --path flashcards.json --path flashcards.json.lock --force

# 3. filter-repo retire le remote par sécurité -> on le remet, puis on compacte.
echo ">> Remise du remote + compactage..."
git remote add origin https://github.com/SeanMarotta/flashcards.git 2>/dev/null || true
git reflog expire --expire=now --all
git gc --prune=now --aggressive

echo
echo "Taille .git  : $(du -sh .git | cut -f1) (après)"
echo
echo "=== ÉTAPE FINALE (manuelle) ============================================"
echo "Si la taille a bien chuté, publie l'historique réécrit :"
echo
echo "    git push origin --force --all"
echo "    git push origin --force --tags"
echo
echo "Puis, pour vraiment libérer la place côté GitHub, supprime les branches"
echo "obsolètes qui retiennent encore l'ancien gros historique, par ex. :"
echo "    git push origin --delete claude/determined-bell-v4m9y1"
echo
echo "Enfin, RE-CLONE tes autres copies (ne fais pas 'git pull' dessus) :"
echo "    mv flashcards flashcards.old && git clone <url> && \\"
echo "    cp -an flashcards.old/{flashcards.json,images,audios} flashcards/"
echo "========================================================================"
