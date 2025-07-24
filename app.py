import streamlit as st
import json
import os
from PIL import Image # Bibliothèque pour gérer les images
import uuid # Pour générer des noms de fichiers uniques

# --- CONFIGURATION ---
# Le dossier où les images seront stockées sur le VPS
IMAGE_DIR = "static_images"
# Crée le dossier s'il n'existe pas
os.makedirs(IMAGE_DIR, exist_ok=True)


# --- Classe Carte et fonctions de sauvegarde/chargement (inchangées) ---
class Carte:
    def __init__(self, index: int,
                 recto_text: str = "", recto_image_url: str = "",
                 verso_text: str = "", verso_image_url: str = ""):
        self.index = index
        self.recto_text = recto_text
        self.recto_image_url = recto_image_url
        self.verso_text = verso_text
        self.verso_image_url = verso_image_url
        self.is_recto_visible = True
    # ... (les autres méthodes de la classe restent identiques)
    def __repr__(self):
        face = "Recto" if self.is_recto_visible else "Verso"
        content = self.recto_text if self.recto_text else "[Image]"
        return f"Carte('{content}', index={self.index}, face='{face}')"
    def flip(self):
        self.is_recto_visible = not self.is_recto_visible
    def forward(self, main_list: list):
        if self.index < 60:
            main_list[self.index].remove(self); self.index += 1; main_list[self.index].append(self); self.flip()
    def backward(self, main_list: list):
        if self.index > 1:
            main_list[self.index].remove(self); self.index -= 1; main_list[self.index].append(self)
        self.flip()

# ... (les fonctions save_data et load_data restent identiques)
SAVE_FILE = "flashcards.json"
def save_data(main_list):
    data_to_save = []
    for box in main_list:
        data_to_save.append([vars(carte) for carte in box])
    with open(SAVE_FILE, "w", encoding="utf-8") as f: json.dump(data_to_save, f, indent=4)
def load_data():
    if not os.path.exists(SAVE_FILE): return [[] for _ in range(61)]
    with open(SAVE_FILE, "r", encoding="utf-8") as f:
        data_from_file = json.load(f)
        main_list_loaded = [[] for _ in range(61)]
        for i, box in enumerate(data_from_file):
            if i > 0:
                for card_dict in box:
                    carte = Carte(index=card_dict.get('index'), recto_text=card_dict.get('recto_text', card_dict.get('recto', '')), recto_image_url=card_dict.get('recto_image_url', ''), verso_text=card_dict.get('verso_text', card_dict.get('verso', '')), verso_image_url=card_dict.get('verso_image_url', card_dict.get('image_url', '')))
                    carte.is_recto_visible = card_dict.get('is_recto_visible', True)
                    main_list_loaded[i].append(carte)
        return main_list_loaded


st.title("Mon Système de Flashcards")
if 'main_list' not in st.session_state:
    st.session_state.main_list = load_data()

# --- NOUVEAU : Section pour la capture d'image ---
st.header("📸 Capturer une image")
img_file_buffer = st.camera_input("Prenez une photo pour vos cartes")

if img_file_buffer is not None:
    # Sauvegarde l'image sur le disque du VPS avec un nom unique
    img = Image.open(img_file_buffer)
    file_name = f"{uuid.uuid4()}.jpg"
    file_path = os.path.join(IMAGE_DIR, file_name)
    img.save(file_path, "JPEG")
    st.success(f"Image sauvegardée sous le nom : {file_name}")

# --- MODIFICATION : Formulaire de création ---
with st.expander("➡️ Ajouter une nouvelle carte"):
    # Récupère la liste des images disponibles
    available_images = [""] + sorted(os.listdir(IMAGE_DIR))

    with st.form("new_card_form", clear_on_submit=True):
        st.write("**Face Recto**")
        recto_type = st.radio("Type de contenu (Recto)", ["Texte", "Image"], key="recto_type")
        recto_text_content, recto_image_url_content = "", ""
        if recto_type == "Texte":
            recto_text_content = st.text_input("Texte du Recto")
        else:
            # On affiche un menu déroulant des images sauvegardées
            selected_image = st.selectbox("Choisir une image (Recto)", options=available_images)
            if selected_image:
                recto_image_url_content = f"/media/{selected_image}" # URL relative que Nginx comprendra

        # ... (logique similaire pour le Verso) ...
        st.write("**Face Verso**")
        verso_type = st.radio("Type de contenu (Verso)", ["Texte", "Image"], key="verso_type")
        verso_text_content, verso_image_url_content = "", ""
        if verso_type == "Texte":
            verso_text_content = st.text_area("Texte du Verso")
        else:
            selected_image = st.selectbox("Choisir une image (Verso)", options=available_images)
            if selected_image:
                verso_image_url_content = f"/media/{selected_image}"

        box_number = st.number_input("Dans quelle boîte la placer ?", min_value=1, max_value=60, step=1)
        submitted = st.form_submit_button("Créer la carte")

    if submitted:
        nouvelle_carte = Carte(index=box_number, recto_text=recto_text_content, recto_image_url=recto_image_url_content, verso_text=verso_text_content, verso_image_url=verso_image_url_content)
        st.session_state.main_list[box_number].append(nouvelle_carte)
        save_data(st.session_state.main_list)
        st.success("Carte ajoutée !")


# (Le reste du code pour la révision et la gestion reste similaire,
# il fonctionnera car il utilise déjà les URL pour afficher les images)
# ...

st.header("🧠 Session de Révision")
boites_non_vides_revision = [i for i, box in enumerate(st.session_state.main_list) if i > 0 and box]
if not boites_non_vides_revision:
    st.info("Aucune carte à réviser.")
else:
    boites_a_reviser = st.multiselect("Choisissez les boîtes à réviser :", options=boites_non_vides_revision)
    if boites_a_reviser:
        for box_num in boites_a_reviser:
            st.subheader(f"--- Boîte n°{box_num} ---")
            for carte in list(st.session_state.main_list[box_num]):
                with st.container(border=True):
                    if carte.is_recto_visible:
                        q_text, q_img, r_text, r_img = carte.recto_text, carte.recto_image_url, carte.verso_text, carte.verso_image_url
                    else:
                        q_text, q_img, r_text, r_img = carte.verso_text, carte.verso_image_url, carte.recto_text, carte.recto_image_url
                    st.markdown("**Question :**")
                    if q_img: st.image(q_img)
                    if q_text: st.markdown(q_text)
                    carte_id = id(carte)
                    if st.button("Révéler la réponse", key=f"reveal_{carte_id}"):
                        st.session_state[f"answer_visible_{carte_id}"] = True
                    if st.session_state.get(f"answer_visible_{carte_id}", False):
                        st.markdown("**Réponse :**")
                        if r_img: st.image(r_img)
                        if r_text: st.markdown(f"*{r_text}*")
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button("✅ Correct", key=f"correct_{carte_id}", use_container_width=True):
                                carte.forward(st.session_state.main_list); save_data(st.session_state.main_list); st.session_state[f"answer_visible_{carte_id}"] = False; st.rerun()
                        with col2:
                            if st.button("❌ Incorrect", key=f"incorrect_{carte_id}", use_container_width=True):
                                carte.backward(st.session_state.main_list); save_data(st.session_state.main_list); st.session_state[f"answer_visible_{carte_id}"] = False; st.rerun()

# --- CORRECTION DE LA SECTION DE GESTION ---
with st.expander("⚙️ Gérer les Cartes"):
    boites_non_vides_gestion = [i for i, box in enumerate(st.session_state.main_list) if i > 0 and box]
    if not boites_non_vides_gestion:
        st.info("Aucune carte à gérer.")
    else:
        for box_index, box_content in enumerate(st.session_state.main_list):
            if box_index > 0 and box_content:
                st.subheader(f"Boîte n°{box_index}")
                for card_index, carte in enumerate(box_content):
                    col1, col2, col3 = st.columns([0.6, 0.2, 0.2])
                    with col1:
                        # Affichage du contenu Recto
                        if carte.recto_image_url:
                            st.image(carte.recto_image_url, width=100)
                        elif carte.recto_text:
                            st.markdown(f"**{carte.recto_text}**")
                        # Affichage du contenu Verso
                        if carte.verso_image_url:
                            st.image(carte.verso_image_url, width=100)
                        elif carte.verso_text:
                            st.markdown(f"*{carte.verso_text}*")
                    
                    with col2:
                        with st.popover("Modifier"):
                            with st.form(f"edit_form_{box_index}_{card_index}"):
                                st.write("Modification de la carte")
                                # Logique d'édition pour le Recto
                                new_recto_type = st.radio("Type Recto", ["Texte", "Image"], index=1 if carte.recto_image_url else 0, key=f"edit_recto_{box_index}_{card_index}")
                                new_recto_text, new_recto_image_url = "", ""
                                if new_recto_type == "Texte":
                                    new_recto_text = st.text_area("Texte Recto", value=carte.recto_text, key=f"edit_recto_text_{box_index}_{card_index}")
                                else:
                                    new_recto_image_url = st.text_area("URL Image Recto", value=carte.recto_image_url, key=f"edit_recto_img_{box_index}_{card_index}")
                                # Logique d'édition pour le Verso
                                new_verso_type = st.radio("Type Verso", ["Texte", "Image"], index=1 if carte.verso_image_url else 0, key=f"edit_verso_{box_index}_{card_index}")
                                new_verso_text, new_verso_image_url = "", ""
                                if new_verso_type == "Texte":
                                    new_verso_text = st.text_area("Texte Verso", value=carte.verso_text, key=f"edit_verso_text_{box_index}_{card_index}")
                                else:
                                    new_verso_image_url = st.text_area("URL Image Verso", value=carte.verso_image_url, key=f"edit_verso_img_{box_index}_{card_index}")

                                new_box = st.number_input("Boîte", min_value=1, max_value=60, value=carte.index, key=f"edit_box_{box_index}_{card_index}")
                                if st.form_submit_button("Enregistrer"):
                                    carte.recto_text, carte.recto_image_url = new_recto_text, new_recto_image_url
                                    carte.verso_text, carte.verso_image_url = new_verso_text, new_verso_image_url
                                    if new_box != carte.index:
                                        st.session_state.main_list[carte.index].remove(carte)
                                        st.session_state.main_list[new_box].append(carte)
                                        carte.index = new_box
                                    save_data(st.session_state.main_list); st.success("Carte modifiée !"); st.rerun()
                    with col3:
                        if st.button("🗑️ Supprimer", key=f"delete_{box_index}_{card_index}", type="primary"):
                            st.session_state.main_list[box_index].pop(card_index); save_data(st.session_state.main_list); st.warning(f"Carte supprimée."); st.rerun()