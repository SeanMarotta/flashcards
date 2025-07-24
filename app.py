import streamlit as st
import json
import os
import uuid
from datetime import datetime, timedelta

# --- Configuration et Initialisation ---
# Constantes pour les noms de fichiers et de répertoires
CARDS_FILE = "flashcards.json"
IMAGE_DIR = "images"

# Création du répertoire pour les images s'il n'existe pas
if not os.path.exists(IMAGE_DIR):
    os.makedirs(IMAGE_DIR)

# --- Fonctions Utilitaires pour la gestion des données ---

def load_flashcards():
    """Charge les flashcards depuis le fichier JSON. Retourne une liste vide si le fichier n'existe pas."""
    if not os.path.exists(CARDS_FILE):
        return []
    try:
        with open(CARDS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def save_flashcards(cards):
    """Sauvegarde la liste des flashcards dans le fichier JSON."""
    with open(CARDS_FILE, 'w', encoding='utf-8') as f:
        json.dump(cards, f, indent=4, ensure_ascii=False)

def save_uploaded_file(uploaded_file):
    """Sauvegarde un fichier (image) dans le répertoire des images et retourne son chemin."""
    if uploaded_file is not None:
        file_extension = os.path.splitext(uploaded_file.name)[1]
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        img_path = os.path.join(IMAGE_DIR, unique_filename)
        with open(img_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        return img_path
    return None

def delete_image_file(image_path):
    """Supprime un fichier image s'il est local et existe."""
    if image_path and not image_path.startswith('http') and os.path.exists(image_path):
        os.remove(image_path)

def get_cards_for_review(box_number):
    """Retourne une liste de cartes à réviser pour une boîte spécifique."""
    all_cards = load_flashcards()
    return [card for card in all_cards if card.get('box') == box_number]


# --- Initialisation du Session State ---
def initialize_session_state():
    """Initialise les variables nécessaires dans le state de la session."""
    if 'review_cards' not in st.session_state:
        st.session_state.review_cards = []
    if 'current_card_index' not in st.session_state:
        st.session_state.current_card_index = 0
    if 'show_answer' not in st.session_state:
        st.session_state.show_answer = False
    if 'editing_card_id' not in st.session_state:
        st.session_state.editing_card_id = None

initialize_session_state()


# --- Fonctions d'affichage de contenu ---
def display_content(content, title):
    """Affiche du texte ou une image (locale ou URL) avec un titre."""
    st.subheader(title)
    if not content:
        st.warning("Contenu introuvable.")
    # Si le contenu est une URL ou un chemin de fichier local
    elif isinstance(content, str) and (content.startswith(('http://', 'https://')) or os.path.exists(content)):
        st.image(content, use_container_width=True)
    # Sinon, suppose que c'est du texte
    else:
        st.markdown(f"<div style='font-size: 1.25rem; border: 1px solid #ddd; padding: 1rem; border-radius: 0.5rem; background-color: black;'>{content}</div>", unsafe_allow_html=True)

def display_card_face_content(col, title, path, text):
    """Affiche le contenu (texte ou image) d'une face de carte dans une colonne."""
    with col:
        st.markdown(f"**{title}**")
        if path:
            st.image(path, use_container_width=True)
        elif text:
            st.markdown(text)
        else:
            st.warning("Contenu vide")


# --- Interface Utilisateur (UI) ---
st.set_page_config(layout="wide", page_title="Révision Espacée")
st.title("🧠 Application de Révision à Répétition Espacée")

menu = st.sidebar.radio("Navigation", ("Séance de révision", "Gérer les cartes", "Créer une nouvelle carte"))
st.sidebar.markdown("---")


# --- Section 1: Séance de révision ---
def display_review_session():
    st.header("🎯 Séance de révision")
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Choisissez une boîte")
        all_cards = load_flashcards()
        if all_cards:
            existing_boxes = sorted(list(set(c['box'] for c in all_cards)))
            box_options = ["-- Choisir une boîte --"] + existing_boxes
            box_to_review = st.selectbox("Boîtes disponibles:", options=box_options)

            if st.button("Démarrer la révision", use_container_width=True):
                if box_to_review != "-- Choisir une boîte --":
                    st.session_state.review_cards = get_cards_for_review(box_number=int(box_to_review))
                    st.session_state.current_card_index = 0
                    st.session_state.show_answer = False
                    if not st.session_state.review_cards:
                        st.toast(f"La boîte {box_to_review} est vide.", icon="📦")
                    st.rerun()
                else:
                    st.warning("Veuillez sélectionner une boîte avant de commencer.")
        else:
            st.info("Aucune carte n'existe. Créez-en une pour commencer.")
            
    with col2:
        if st.session_state.review_cards and st.session_state.current_card_index < len(st.session_state.review_cards):
            card = st.session_state.review_cards[st.session_state.current_card_index]
            
            total_cards = len(st.session_state.review_cards)
            progress = st.session_state.current_card_index + 1
            st.progress(progress / total_cards, text=f"Carte {progress}/{total_cards}")

            is_recto_question = card.get('current_face', 'recto') == 'recto'
            
            question_content = card.get('recto_path') or card.get('recto_text') if is_recto_question else card.get('verso_path') or card.get('verso_text')
            answer_content = card.get('verso_path') or card.get('verso_text') if is_recto_question else card.get('recto_path') or card.get('recto_text')
            question_title = "Recto (Question)" if is_recto_question else "Verso (Question)"
            answer_title = "Verso (Réponse)" if is_recto_question else "Recto (Réponse)"

            display_content(question_content, question_title)
            st.markdown("---")

            if st.session_state.show_answer:
                display_content(answer_content, answer_title)
                st.markdown("---")
                btn_col1, btn_col2 = st.columns(2)
                
                def handle_response(correct):
                    all_cards = load_flashcards()
                    for i, c in enumerate(all_cards):
                        if c['id'] == card['id']:
                            if correct:
                                new_box = min(60, c['box'] + 1)
                                icon, message = "🎉", f"Bravo ! Carte déplacée vers la boîte n°{new_box}."
                            else:
                                new_box = max(1, c['box'] - 1)
                                icon, message = "📚", f"Pas de souci. Carte déplacée vers la boîte n°{new_box}."
                            
                            all_cards[i]['box'] = new_box
                            all_cards[i]['next_review_date'] = (datetime.now() + timedelta(days=new_box)).strftime('%Y-%m-%d')
                            all_cards[i]['current_face'] = 'verso' if c.get('current_face', 'recto') == 'recto' else 'recto'
                            break
                    save_flashcards(all_cards)
                    st.toast(message, icon=icon)
                    st.session_state.current_card_index += 1
                    st.session_state.show_answer = False
                    st.rerun()

                with btn_col1:
                    if st.button("✅ Correct", use_container_width=True, type="primary"):
                        handle_response(correct=True)
                with btn_col2:
                    if st.button("❌ Incorrect", use_container_width=True):
                        handle_response(correct=False)
            else:
                if st.button("Afficher la réponse", use_container_width=True):
                    st.session_state.show_answer = True
                    st.rerun()
        
        elif st.session_state.review_cards:
            st.success("🎉 Session de révision terminée ! Bravo !")
            st.session_state.review_cards = []


# --- Section 2: Gérer les cartes ---
def display_card_management():
    st.header("🗂️ Gérer les cartes existantes")
    all_cards = load_flashcards()
    if not all_cards:
        st.info("Aucune carte n'a été créée. Allez dans 'Créer une nouvelle carte' pour commencer.")
        return

    if st.session_state.editing_card_id:
        display_edit_form()
        return

    for card in sorted(all_cards, key=lambda x: x['box']):
        current_face_str = card.get('current_face', 'recto').capitalize()
        expander_title = f"Boîte n°{card['box']} - Face actuelle: {current_face_str} - Prochaine révision: {card.get('next_review_date', 'N/A')}"
        with st.expander(expander_title):
            col1, col2, col3 = st.columns([2, 2, 1])
            display_card_face_content(col1, "Recto", card.get('recto_path'), card.get('recto_text'))
            display_card_face_content(col2, "Verso", card.get('verso_path'), card.get('verso_text'))
            with col3:
                st.markdown("**Actions**")
                if st.button("Modifier", key=f"edit_{card['id']}", use_container_width=True):
                    st.session_state.editing_card_id = card['id']
                    st.rerun()
                if st.button("Supprimer", key=f"del_{card['id']}", use_container_width=True, type="secondary"):
                    delete_image_file(card.get('recto_path'))
                    delete_image_file(card.get('verso_path'))
                    cards_after_deletion = [c for c in all_cards if c['id'] != card['id']]
                    save_flashcards(cards_after_deletion)
                    st.toast("Carte supprimée !", icon="🗑️")
                    st.rerun()


# --- Section 3: Modifier une carte ---
def display_edit_form():
    st.subheader("✏️ Modification de la carte")
    all_cards = load_flashcards()
    card_to_edit = next((c for c in all_cards if c['id'] == st.session_state.editing_card_id), None)
    if not card_to_edit:
        st.error("Carte non trouvée. Retour à la liste.")
        st.session_state.editing_card_id = None
        return

    with st.form("edit_card_form"):
        st.write(f"Modification de la carte de la boîte n°{card_to_edit['box']}")
        new_box = st.number_input("Changer la boîte (1-60)", min_value=1, max_value=60, value=card_to_edit['box'])
        
        st.markdown("**Contenu Recto**")
        display_card_face_content(st, "", card_to_edit.get('recto_path'), card_to_edit.get('recto_text'))
        new_recto_text = st.text_area("Changer le texte du Recto", value=card_to_edit.get('recto_text', ''), key="edit_recto_text")
        new_recto_url = st.text_input("Ou changer le lien de l'image web", value=card_to_edit.get('recto_path', '') if card_to_edit.get('recto_path','').startswith('http') else '', key="edit_recto_url")
        new_recto_upload = st.file_uploader("Ou changer l'image locale", type=['png', 'jpg', 'jpeg'], key="edit_recto_img")
        
        st.markdown("**Contenu Verso**")
        display_card_face_content(st, "", card_to_edit.get('verso_path'), card_to_edit.get('verso_text'))
        new_verso_text = st.text_area("Changer le texte du Verso", value=card_to_edit.get('verso_text', ''), key="edit_verso_text")
        new_verso_url = st.text_input("Ou changer le lien de l'image web", value=card_to_edit.get('verso_path', '') if card_to_edit.get('verso_path','').startswith('http') else '', key="edit_verso_url")
        new_verso_upload = st.file_uploader("Ou changer l'image locale", type=['png', 'jpg', 'jpeg'], key="edit_verso_img")

        if st.form_submit_button("Sauvegarder les modifications"):
            for i, c in enumerate(all_cards):
                if c['id'] == st.session_state.editing_card_id:
                    all_cards[i]['box'] = new_box
                    all_cards[i]['next_review_date'] = (datetime.now() + timedelta(days=new_box)).strftime('%Y-%m-%d')
                    
                    # Logique de mise à jour pour Recto (Priorité: Upload > URL > Texte)
                    if new_recto_upload:
                        delete_image_file(c.get('recto_path'))
                        all_cards[i]['recto_path'] = save_uploaded_file(new_recto_upload)
                        all_cards[i]['recto_text'] = None
                    elif new_recto_url:
                        delete_image_file(c.get('recto_path'))
                        all_cards[i]['recto_path'] = new_recto_url
                        all_cards[i]['recto_text'] = None
                    elif new_recto_text:
                        delete_image_file(c.get('recto_path'))
                        all_cards[i]['recto_path'] = None
                        all_cards[i]['recto_text'] = new_recto_text

                    # Logique de mise à jour pour Verso (Priorité: Upload > URL > Texte)
                    if new_verso_upload:
                        delete_image_file(c.get('verso_path'))
                        all_cards[i]['verso_path'] = save_uploaded_file(new_verso_upload)
                        all_cards[i]['verso_text'] = None
                    elif new_verso_url:
                        delete_image_file(c.get('verso_path'))
                        all_cards[i]['verso_path'] = new_verso_url
                        all_cards[i]['verso_text'] = None
                    elif new_verso_text:
                        delete_image_file(c.get('verso_path'))
                        all_cards[i]['verso_path'] = None
                        all_cards[i]['verso_text'] = new_verso_text
                    break
            
            save_flashcards(all_cards)
            st.toast("Carte modifiée avec succès !", icon="✅")
            st.session_state.editing_card_id = None
            st.rerun()
    if st.button("Annuler l'édition"):
        st.session_state.editing_card_id = None
        st.rerun()


# --- Section 4: Créer une nouvelle carte ---
def display_create_card():
    st.header("➕ Créer une nouvelle carte")
    with st.form("new_card_form"):
        st.subheader("Contenu du Recto (Question)")
        recto_text = st.text_area("🇦 Écrire du texte pour le recto", key="recto_txt")
        recto_url = st.text_input("🔗 Entrer un lien vers une image web", key="recto_url")
        st.write("ou")
        recto_upload = st.file_uploader("🖼️ Importer une image locale", type=['png', 'jpg', 'jpeg'], key="recto_up")
        st.markdown("---")
        
        st.subheader("Contenu du Verso (Réponse)")
        verso_text = st.text_area("🇦 Écrire du texte pour le verso", key="verso_txt")
        verso_url = st.text_input("🔗 Entrer un lien vers une image web", key="verso_url")
        st.write("ou")
        verso_upload = st.file_uploader("🖼️ Importer une image locale", type=['png', 'jpg', 'jpeg'], key="verso_up")
        st.markdown("---")

        initial_box = st.number_input("Placer dans la boîte n°", min_value=1, max_value=60, value=1)
        
        if st.form_submit_button("Ajouter la carte"):
            # Déterminer le contenu du Recto (Priorité: Upload > Camera > URL > Texte)
            recto_path_val, recto_text_val = None, None
            recto_file = recto_upload
            if recto_file:
                recto_path_val = save_uploaded_file(recto_file)
            elif recto_url:
                recto_path_val = recto_url
            elif recto_text:
                recto_text_val = recto_text

            # Déterminer le contenu du Verso (Priorité: Upload > Camera > URL > Texte)
            verso_path_val, verso_text_val = None, None
            verso_file = verso_upload
            if verso_file:
                verso_path_val = save_uploaded_file(verso_file)
            elif verso_url:
                verso_path_val = verso_url
            elif verso_text:
                verso_text_val = verso_text

            if (recto_path_val or recto_text_val) and (verso_path_val or verso_text_val):
                all_cards = load_flashcards()
                new_card = {
                    "id": str(uuid.uuid4()),
                    "recto_path": recto_path_val, "recto_text": recto_text_val,
                    "verso_path": verso_path_val, "verso_text": verso_text_val,
                    "box": initial_box,
                    "creation_date": datetime.now().strftime('%Y-%m-%d'),
                    "next_review_date": (datetime.now() + timedelta(days=initial_box)).strftime('%Y-%m-%d'),
                    "current_face": "recto"
                }
                all_cards.append(new_card)
                save_flashcards(all_cards)
                st.success("Nouvelle carte ajoutée avec succès !")
                st.rerun()
            else:
                st.error("Veuillez fournir un contenu (texte ou image) pour le recto ET pour le verso.")


# --- Routage principal ---
if menu == "Séance de révision":
    display_review_session()
elif menu == "Gérer les cartes":
    display_card_management()
elif menu == "Créer une nouvelle carte":
    display_create_card()