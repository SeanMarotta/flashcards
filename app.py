import streamlit as st
import json
import os
from PIL import Image
import uuid

# --- CONFIGURATION ---
IMAGE_DIR = "static_images"
os.makedirs(IMAGE_DIR, exist_ok=True)

# --- Classe Carte (version simplifiée) et fonctions de sauvegarde/chargement ---
class Carte:
    def __init__(self, recto: str, verso: str, index: int, image_url: str = ""):
        self.recto = recto
        self.verso = verso
        self.index = index
        self.is_recto_visible = True
        self.image_url = image_url

    def __repr__(self):
        face = "Recto" if self.is_recto_visible else "Verso"
        return f"Carte('{self.recto}', index={self.index}, face='{face}')"

    def flip(self):
        self.is_recto_visible = not self.is_recto_visible

    def forward(self, main_list: list):
        if self.index < 60:
            main_list[self.index].remove(self)
            self.index += 1
            main_list[self.index].append(self)
        self.flip()

    def backward(self, main_list: list):
        if self.index > 1:
            main_list[self.index].remove(self)
            self.index -= 1
            main_list[self.index].append(self)
        self.flip()

# (Les fonctions save_data et load_data sont adaptées à cette structure simple)
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
                    # On s'assure de ne charger que les attributs de la classe simplifiée
                    carte = Carte(
                        recto=card_dict.get('recto', ''),
                        verso=card_dict.get('verso', ''),
                        index=card_dict.get('index'),
                        image_url=card_dict.get('image_url', '')
                    )
                    carte.is_recto_visible = card_dict.get('is_recto_visible', True)
                    main_list_loaded[i].append(carte)
        return main_list_loaded

st.title("Mon Système de Flashcards")
if 'main_list' not in st.session_state:
    st.session_state.main_list = load_data()

# --- NOUVEAU : Section pour l'envoi de fichiers ---
st.header("📤 Envoyer une image")
uploaded_file = st.file_uploader(
    "Choisissez une image sur votre appareil",
    type=['png', 'jpg', 'jpeg']
)

if uploaded_file is not None:
    try:
        img = Image.open(uploaded_file)
        # Génère un nom de fichier unique et le sauvegarde
        file_name = f"{uuid.uuid4()}.jpg"
        file_path = os.path.join(IMAGE_DIR, file_name)
        img.save(file_path, "JPEG")

        # Affiche le lien public à copier
        # NOTE : Remplacez VOTRE_IP_PUBLIQUE par votre véritable adresse IP si elle n'est pas détectée.
        full_url = f"http://VOTRE_IP_PUBLIQUE/media/{file_name}"
        st.success("Image envoyée avec succès !")
        st.markdown(f"Copiez ce lien pour l'utiliser dans une carte : `{full_url}`")
        st.image(img, width=200)
    except Exception as e:
        st.error(f"Une erreur est survenue : {e}")


# --- Formulaire de création (version simplifiée) ---
with st.expander("➡️ Ajouter une nouvelle carte"):
    with st.form("new_card_form", clear_on_submit=True):
        recto_content = st.text_input("Recto (la question)")
        verso_content = st.text_area("Verso (la réponse)")
        image_url_content = st.text_input("URL de l'image (optionnel)")
        box_number = st.number_input("Dans quelle boîte la placer ?", min_value=1, max_value=60, step=1)
        submitted = st.form_submit_button("Créer la carte")

    if submitted and recto_content and verso_content:
        nouvelle_carte = Carte(recto_content, verso_content, box_number, image_url_content)
        st.session_state.main_list[box_number].append(nouvelle_carte)
        save_data(st.session_state.main_list)
        st.success(f"Carte ajoutée !")

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