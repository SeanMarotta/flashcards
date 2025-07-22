#!/bin/bash

# Allez dans le répertoire de votre projet
cd /home/flashcards || exit

# Vérifiez s'il y a des changements à commiter
if [ -n "$(git status --porcelain)" ]; then
  echo "Changements détectés, commit en cours..."
  # Ajoutez tous les fichiers
  git add .
  # Créez le commit avec la date
  git commit -m "Commit automatique du $(date +'%Y-%m-%d %H:%M:%S')"
  # Poussez les changements
  git push
else
  echo "Pas de changements à commiter."
fi

# Dans tous les cas, faites un pull pour mettre à jour
echo "Mise à jour depuis le dépôt distant..."
git pull

echo "Synchronisation terminée."
