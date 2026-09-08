"""
Migration des intervalles de révision.

Recalcule `next_review_date` de chaque carte à partir de sa dernière révision
et de la loi d'intervalle en vigueur :

    next_review_date = last_reviewed_date + box_interval(box)

La loi n'est PAS redéfinie ici : elle est importée d'app2.py, seul endroit où
elle est écrite (constantes BOX_LINEAR_UNTIL / BOX_INTERVAL_POWER). Changez-la
là-bas, puis lancez ce script pour propager le changement aux cartes déjà
enregistrées — sans quoi les anciennes échéances gardent l'ancienne loi.

Usage:
    python3 migrate_intervals.py            # simulation : n'écrit rien
    python3 migrate_intervals.py --apply    # applique, après sauvegarde

Une sauvegarde horodatée est déposée dans backups/ avant toute écriture.
"""

import json
import os
import shutil
import sys
from collections import Counter
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta

from app2 import (CARDS_FILE, LOCK_FILE, BACKUP_DIR, box_interval,
                  BOX_LINEAR_UNTIL, BOX_INTERVAL_POWER)

try:
    import fcntl  # Unix
except ImportError:
    fcntl = None


@contextmanager
def exclusive():
    """Le même verrou que locked_flashcards() dans app2.py.

    La migration lit tout le paquet, calcule, puis réécrit : sans ce verrou, une
    réponse donnée dans l'app pendant ce laps de temps serait écrasée. Le script
    peut donc tourner sans arrêter l'application — il attend simplement son tour."""
    with open(LOCK_FILE, "w") as lf:
        if fcntl is not None:
            fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lf, fcntl.LOCK_UN)


def backup():
    """Copie horodatée du fichier de cartes, sous un nom distinct de la rotation
    automatique de l'app — pour qu'elle ne soit pas emportée par celle-ci."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"pre_migration_{ts}.json")
    shutil.copy2(CARDS_FILE, dest)
    return dest


def migrate(apply_changes):
    # En simulation on ne fait que lire : inutile de bloquer l'app. En écriture,
    # lecture, calcul et écriture doivent tenir dans un seul verrou.
    with exclusive() if apply_changes else nullcontext():
        _migrate(apply_changes)


def _migrate(apply_changes):
    with open(CARDS_FILE, encoding="utf-8") as f:
        cards = json.load(f)

    changed, skipped = [], 0
    for c in cards:
        base = c.get("last_reviewed_date") or c.get("creation_date")
        if not base:
            skipped += 1
            continue
        try:
            base_dt = datetime.strptime(base, "%Y-%m-%d")
        except ValueError:
            skipped += 1
            continue
        new_date = (base_dt + timedelta(days=box_interval(c.get("box", 1)))).strftime("%Y-%m-%d")
        if new_date != c.get("next_review_date"):
            changed.append((c, new_date))

    print(f"Loi en vigueur : linéaire jusqu'à la boîte {BOX_LINEAR_UNTIL}, "
          f"puis ×(n/{BOX_LINEAR_UNTIL})^{BOX_INTERVAL_POWER}")
    print(f"Cartes             : {len(cards)}")
    print(f"Échéances à changer : {len(changed)}")
    if skipped:
        print(f"Ignorées (pas de date exploitable) : {skipped}")

    print("\n--- Intervalles par boîte ---")
    # Un échantillon régulier, plus le seuil et ses voisins immédiats : c'est là
    # que la courbe décolle, et c'est ce qu'on veut vérifier d'un coup d'œil.
    sample = sorted({1, 5, 10, 15, 25, 30, 40, 50, 60,
                     BOX_LINEAR_UNTIL - 1, BOX_LINEAR_UNTIL, BOX_LINEAR_UNTIL + 1})
    for b in sample:
        new = box_interval(b)
        flag = "  ← seuil" if b == BOX_LINEAR_UNTIL else ""
        diff = f"  (+{new - b} j)" if new != b else ""
        print(f"  Boîte {b:2d} : {b:3d} j → {new:3d} j{diff}{flag}")

    # Charge quotidienne à l'équilibre : somme des 1/intervalle sur le paquet.
    boxes = Counter(c.get("box", 1) for c in cards)
    before = sum(n / max(1, b) for b, n in boxes.items())
    after = sum(n / box_interval(b) for b, n in boxes.items())
    print(f"\nCharge quotidienne à l'équilibre : {before:.0f}/j → {after:.0f}/j")

    # Aperçu de la charge réelle des 30 prochains jours, après migration.
    preview = Counter()
    for c in cards:
        preview[c.get("next_review_date")] += 1
    for c, new_date in changed:
        preview[c.get("next_review_date")] -= 1
        preview[new_date] += 1
    today = datetime.now()
    overdue = sum(n for d, n in preview.items()
                  if d and d <= today.strftime("%Y-%m-%d") and n > 0)
    print(f"Cartes dues aujourd'hui après migration : {overdue}")

    print("\n--- 30 prochains jours ---")
    total = 0
    for i in range(30):
        d = (today + timedelta(days=i)).strftime("%Y-%m-%d")
        n = max(0, preview.get(d, 0))
        total += n
        print(f"  {d} : {n:4d} {'#' * min(n, 60)}")
    print(f"\nMoyenne sur 30 jours : {total / 30:.0f}/jour")

    if not apply_changes:
        print("\n[SIMULATION] Rien n'a été écrit. Relancez avec --apply pour appliquer.")
        return

    dest = backup()
    print(f"\nSauvegarde : {dest}")
    for c, new_date in changed:
        c["next_review_date"] = new_date
    # Même format que save_flashcards() dans app2.py, pour ne pas réécrire
    # inutilement tout le fichier au prochain enregistrement.
    tmp = CARDS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cards, f, indent=4, ensure_ascii=False, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, CARDS_FILE)
    print(f"✅ {len(changed)} échéance(s) mise(s) à jour dans {CARDS_FILE}.")


if __name__ == "__main__":
    migrate("--apply" in sys.argv)
