import os
from PIL import Image
import sys

# --- Configuration ---
QUALITY = 50         # Qualité de compression pour les JPG (de 1 à 95, 80 est un bon compromis)

def compress_image(file_path):
    """Compresse une image en optimisant sa taille et écrase l'original."""
    try:
        img = Image.open(file_path)
        original_size = os.path.getsize(file_path)

        file_extension = os.path.splitext(file_path)[1].lower()

        if file_extension in ['.jpg', '.jpeg']:
            # Pour les JPG, on ajuste la qualité
            img.save(file_path, 'JPEG', quality=QUALITY, optimize=True)
        elif file_extension == '.png':
            # Pour les PNG, on utilise l'option d'optimisation
            img.save(file_path, 'PNG', optimize=True)
        else:
            # Ne fait rien pour les autres formats
            return original_size, original_size

        new_size = os.path.getsize(file_path)
        return original_size, new_size
        
    except Exception as e:
        print(f"Erreur lors du traitement de {os.path.basename(file_path)}: {e}")
        return 0, 0

def main():
    """Fonction principale du script."""
    print("--- Script de Compression d'Images ---")
    
    try:
        target_dir = input("Veuillez entrer le chemin du dossier à compresser : ")
        if not os.path.isdir(target_dir):
            print(f"\nErreur : Le dossier '{target_dir}' n'a pas été trouvé ou n'est pas un répertoire valide.")
            return
    except KeyboardInterrupt:
        print("\nOpération annulée par l'utilisateur.")
        return

    print(f"\nLe script va compresser les images dans le dossier : '{target_dir}'")
    print("\033[91mATTENTION : Les fichiers originaux seront écrasés.\033[0m")
    print("Il est conseillé de faire une sauvegarde de ce dossier avant de continuer.")
    
    try:
        # Demande de confirmation à l'utilisateur
        choice = input("Voulez-vous continuer ? (o/n) : ").lower()
        if choice != 'o':
            print("Opération annulée.")
            return
    except KeyboardInterrupt:
        print("\nOpération annulée par l'utilisateur.")
        return

    total_original_size = 0
    total_new_size = 0
    files_processed = 0

    image_files = [f for f in os.listdir(target_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]

    if not image_files:
        print("Aucune image PNG ou JPG à compresser dans le dossier.")
        return

    print("\nDébut de la compression...")

    for filename in image_files:
        file_path = os.path.join(target_dir, filename)
        if os.path.isfile(file_path):
            original_size, new_size = compress_image(file_path)
            
            if original_size > 0:
                total_original_size += original_size
                total_new_size += new_size
                files_processed += 1
                
                reduction = original_size - new_size
                reduction_percent = (reduction / original_size * 100) if original_size > 0 else 0
                
                # Affiche une ligne par fichier traité
                sys.stdout.write(f"\r- Traitement de {filename:<40} | Réduction: {reduction/1024:.2f} Ko ({reduction_percent:.1f}%)")
                sys.stdout.flush()

    print("\n\n--- Rapport de Compression ---")
    if files_processed > 0:
        total_reduction = total_original_size - total_new_size
        total_reduction_percent = (total_reduction / total_original_size * 100) if total_original_size > 0 else 0
        
        print(f"Nombre d'images traitées : {files_processed}")
        print(f"Taille originale totale    : {total_original_size/1024/1024:.2f} Mo")
        print(f"Nouvelle taille totale     : {total_new_size/1024/1024:.2f} Mo")
        print(f"Espace total économisé     : \033[92m{total_reduction/1024/1024:.2f} Mo ({total_reduction_percent:.1f}%)\033[0m")
    else:
        print("Aucun fichier n'a pu être traité.")

if __name__ == "__main__":
    main()
