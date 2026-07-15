import os
import json
import uuid
import shutil
from datetime import datetime, timedelta

# --- Configuration ---
# Ces constantes doivent correspondre à celles de votre application Streamlit.
CARDS_FILE = "flashcards.json"
IMAGE_DIR = "images"
SUPPORTED_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp')

def load_flashcards():
    """
    Charge les flashcards depuis le fichier JSON.
    Retourne une liste vide si le fichier n'existe pas ou est corrompu.
    """
    if not os.path.exists(CARDS_FILE):
        return []
    try:
        with open(CARDS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        print(f"Avertissement : Le fichier {CARDS_FILE} est introuvable ou corrompu. Un nouveau fichier sera créé.")
        return []

def save_flashcards(cards):
    """
    Sauvegarde la liste complète des flashcards dans le fichier JSON.
    """
    with open(CARDS_FILE, 'w', encoding='utf-8') as f:
        json.dump(cards, f, indent=4, ensure_ascii=False)
    print(f"✅ Fichier {CARDS_FILE} mis à jour avec succès.")

def main():
    """
    Fonction principale du script d'importation.
    """
    print("--- Script d'importation de flashcards en masse ---")

    # 1. Demander le chemin du dossier source
    source_folder = input("Veuillez entrer le chemin complet du dossier contenant les images à importer : ")
    if not os.path.isdir(source_folder):
        print(f"❌ Erreur : Le dossier '{source_folder}' n'existe pas ou n'est pas un dossier valide.")
        return

    # 2. Demander la boîte de départ
    while True:
        try:
            initial_box = int(input("Dans quelle boîte souhaitez-vous placer ces nouvelles cartes ? (1-60) [Défaut: 1] ") or "1")
            if 1 <= initial_box <= 60:
                break
            else:
                print("Veuillez entrer un nombre entre 1 et 60.")
        except ValueError:
            print("Entrée invalide. Veuillez entrer un nombre.")


    # 3. Récupérer et trier les images
    try:
        image_files = sorted([f for f in os.listdir(source_folder) if f.lower().endswith(SUPPORTED_EXTENSIONS)])
    except FileNotFoundError:
        print(f"❌ Erreur : Impossible d'accéder au dossier '{source_folder}'.")
        return
        
    if not image_files:
        print("Aucune image trouvée dans le dossier spécifié.")
        return

    # 4. Regrouper les images par paires (recto, verso)
    if len(image_files) % 2 != 0:
        print(f"⚠️ Avertissement : Il y a un nombre impair d'images ({len(image_files)}). La dernière image '{image_files[-1]}' sera ignorée.")
        image_files.pop() # On retire le dernier élément

    pairs = [(image_files[i], image_files[i+1]) for i in range(0, len(image_files), 2)]

    if not pairs:
        print("Aucune paire d'images (recto/verso) n'a pu être formée.")
        return

    print(f"\n{len(pairs)} paires d'images trouvées. Début de l'importation...")

    # 5. Charger les flashcards existantes
    all_cards = load_flashcards()

    # 6. Traiter chaque paire
    cards_added_count = 0
    for recto_filename, verso_filename in pairs:
        # Créer les chemins source complets
        recto_source_path = os.path.join(source_folder, recto_filename)
        verso_source_path = os.path.join(source_folder, verso_filename)

        # Copier les images vers le répertoire 'images' de l'application et obtenir le nouveau chemin relatif
        try:
            shutil.copy(recto_source_path, IMAGE_DIR)
            recto_relative_path = os.path.join(IMAGE_DIR, os.path.basename(recto_source_path))

            shutil.copy(verso_source_path, IMAGE_DIR)
            verso_relative_path = os.path.join(IMAGE_DIR, os.path.basename(verso_source_path))
        except Exception as e:
            print(f"❌ Erreur lors de la copie des fichiers {recto_filename} ou {verso_filename}: {e}")
            continue # Passe à la paire suivante

        # Créer la nouvelle carte
        new_card = {
            "id": str(uuid.uuid4()),
            "recto_path": recto_relative_path,
            "recto_text": None,
            "verso_path": verso_relative_path,
            "verso_text": None,
            "box": initial_box,
            "creation_date": datetime.now().strftime('%Y-%m-%d'),
            "next_review_date": (datetime.now() + timedelta(days=initial_box)).strftime('%Y-%m-%d'),
            "current_face": "recto"
        }
        all_cards.append(new_card)
        cards_added_count += 1
        print(f"  -> Ajout de la carte: {recto_filename} / {verso_filename}")

    # 7. Sauvegarder la liste mise à jour
    if cards_added_count > 0:
        save_flashcards(all_cards)
        print(f"\n🎉 Terminé ! {cards_added_count} nouvelle(s) carte(s) ont été ajoutée(s).")
    else:
        print("\nAucune nouvelle carte n'a été ajoutée.")


if __name__ == "__main__":
    main()
