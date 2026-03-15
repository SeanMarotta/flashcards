"""
Migration des intervalles de révision.

Usage:
    python3 migrate_intervals.py [exposant]

Exemple:
    python3 migrate_intervals.py 1.3

Si aucun exposant n'est fourni, utilise la valeur actuelle de app2.py.
IMPORTANT: après migration, penser à mettre à jour la même valeur
dans app2.py → fonction box_interval().
"""

import json
import sys
from datetime import datetime, timedelta
from collections import Counter

CARDS_FILE = "flashcards.json"

def box_interval(box, power):
    if box <= 8:
        return box
    return round(box ** power)

def migrate(power):
    with open(CARDS_FILE) as f:
        cards = json.load(f)

    migrated = 0
    for c in cards:
        base = c.get("last_reviewed_date") or c.get("creation_date")
        if not base:
            continue
        box = c.get("box", 1)
        base_dt = datetime.strptime(base, "%Y-%m-%d")
        new_date = (base_dt + timedelta(days=box_interval(box, power))).strftime("%Y-%m-%d")
        if new_date != c.get("next_review_date"):
            c["next_review_date"] = new_date
            migrated += 1

    with open(CARDS_FILE, "w") as f:
        json.dump(cards, f, ensure_ascii=False, indent=2)

    # Affichage des résultats
    print(f"Exposant: {power}")
    print(f"Cartes migrées: {migrated}")

    print("\n--- Intervalles ---")
    for b in range(1, 31):
        old = b
        new = box_interval(b, power)
        diff = f"  (+{new - old}j)" if new != old else ""
        print(f"  Boîte {b:2d}: {old:3d}j → {new:3d}j{diff}")

    date_counts = Counter(c.get("next_review_date", "") for c in cards)
    total_30 = 0
    print("\n--- 30 prochains jours ---")
    for i in range(30):
        d = (datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d")
        count = date_counts.get(d, 0)
        total_30 += count
        bar = "#" * min(count, 60)
        print(f"  {d}: {count:4d} {bar}")

    print(f"\nMoyenne 30j: {total_30 / 30:.0f}/jour")

    boxes = Counter(c.get("box", 1) for c in cards)
    daily_theory = sum(count / box_interval(box, power) for box, count in boxes.items())
    print(f"Régime stable estimé: ~{daily_theory:.0f}/jour")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        power = float(sys.argv[1])
    else:
        from app2 import box_interval as _bi
        # Detect current power by testing box 10
        import math
        val = _bi(10)
        power = math.log(val) / math.log(10)
        print(f"(exposant détecté depuis app2.py: {power:.1f})")

    migrate(power)
