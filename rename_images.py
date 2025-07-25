import os

# --- Configuration ---
# Extensions de fichiers image prises en charge.
SUPPORTED_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.bmp')

def main():
    """
    Fonction principale du script de renommage.
    """
    print("--- Script de renommage séquentiel d'images (recto/verso) ---")

    # 1. Demander le chemin du dossier source
    source_folder = input("Veuillez entrer le chemin complet du dossier contenant les images à renommer : ")
    if not os.path.isdir(source_folder):
        print(f"❌ Erreur : Le dossier '{source_folder}' n'existe pas ou n'est pas un dossier valide.")
        return

    # 2. Récupérer et trier les images pour assurer un ordre cohérent
    try:
        image_files = sorted([f for f in os.listdir(source_folder) if f.lower().endswith(SUPPORTED_EXTENSIONS)])
    except Exception as e:
        print(f"❌ Erreur lors de l'accès au dossier : {e}")
        return
        
    if not image_files:
        print("Aucune image trouvée dans le dossier spécifié.")
        return

    # 3. Prévisualiser les changements prévus
    print("\nLes fichiers suivants seront renommés :")
    rename_plan = []
    for i, filename in enumerate(image_files):
        # Déterminer le numéro de la paire et le type (recto/verso)
        pair_number = (i // 2) + 1
        tag = "recto" if i % 2 == 0 else "verso"
        
        # Conserver l'extension originale du fichier
        original_extension = os.path.splitext(filename)[1]
        
        # Construire le nouveau nom de fichier
        new_filename = f"{pair_number:02d}_{tag}{original_extension}"
        
        rename_plan.append((filename, new_filename))
        print(f"  '{filename}'  ->  '{new_filename}'")
    
    # 4. Demander la confirmation de l'utilisateur avant de continuer
    print(f"\nTotal : {len(image_files)} fichiers à renommer.")
    
    try:
        confirm = input("Voulez-vous procéder au renommage ? (o/n) ").lower()
    except KeyboardInterrupt:
        print("\nOpération annulée par l'utilisateur.")
        return

    if confirm != 'o':
        print("Opération annulée.")
        return

    # 5. Exécuter le renommage
    print("\nDébut du renommage...")
    renamed_count = 0
    for old_name, new_name in rename_plan:
        old_path = os.path.join(source_folder, old_name)
        new_path = os.path.join(source_folder, new_name)
        
        # Vérifier si un fichier avec le nouveau nom existe déjà
        if os.path.exists(new_path):
            print(f"  ⚠️ Avertissement : Un fichier nommé '{new_name}' existe déjà. Le fichier '{old_name}' n'a pas été renommé.")
            continue
            
        try:
            os.rename(old_path, new_path)
            renamed_count += 1
        except Exception as e:
            print(f"  ❌ Erreur lors du renommage de '{old_name}': {e}")
            
    print(f"\n🎉 Terminé ! {renamed_count} fichier(s) sur {len(image_files)} ont été renommé(s).")


if __name__ == "__main__":
    main()
