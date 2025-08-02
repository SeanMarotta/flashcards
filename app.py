import streamlit as st
import json
import os
import uuid
from datetime import datetime, timedelta
import time
from habit_tracker import display_habit_tracker

# --- Fonction de vérification du mot de passe ---
def check_password():
    """Retourne True si l'utilisateur a entré le bon mot de passe."""

    def password_entered():
        """Vérifie si le mot de passe entré par l'utilisateur est correct."""
        if "password" in st.session_state and st.session_state["password"] == st.secrets["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # Ne pas garder le mot de passe en mémoire
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # Première exécution, demander le mot de passe.
        st.text_input(
            "Mot de passe", type="password", on_change=password_entered, key="password"
        )
        return False
    elif not st.session_state["password_correct"]:
        # Mot de passe incorrect, redemander.
        st.text_input(
            "Mot de passe", type="password", on_change=password_entered, key="password"
        )
        st.error("😕 Mot de passe incorrect.")
        return False
    else:
        # Mot de passe correct.
        return True

# --- Configuration et Initialisation ---
CARDS_FILE = "flashcards.json"
IMAGE_DIR = "images"
if not os.path.exists(IMAGE_DIR):
    os.makedirs(IMAGE_DIR)

# --- Fonctions Utilitaires ---

def load_flashcards():
    """Charge les flashcards depuis le fichier JSON."""
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
        json.dump(cards, f, indent=4, ensure_ascii=False, sort_keys=True)

def save_uploaded_file(uploaded_file):
    """Sauvegarde un fichier uploadé et retourne son chemin."""
    if uploaded_file is not None:
        file_extension = os.path.splitext(uploaded_file.name)[1]
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        img_path = os.path.join(IMAGE_DIR, unique_filename)
        with open(img_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        return img_path
    return None

def delete_image_file(image_path):
    """Supprime un fichier image local s'il existe."""
    if image_path and not image_path.startswith('http') and os.path.exists(image_path):
        os.remove(image_path)

def get_cards_for_box_review(box_number):
    """Retourne les cartes pour une boîte spécifique."""
    all_cards = load_flashcards()
    return [card for card in all_cards if card.get('box') == box_number]

def get_cards_for_daily_review():
    """Retourne les cartes dont la date de révision est aujourd'hui ou passée."""
    all_cards = load_flashcards()
    today_str = datetime.now().strftime('%Y-%m-%d')
    return [card for card in all_cards if card.get('next_review_date', '') <= today_str]


# --- Initialisation du Session State ---
def initialize_session_state():
    """Initialise les variables de session."""
    if 'review_cards' not in st.session_state:
        st.session_state.review_cards = []
    if 'current_card_index' not in st.session_state:
        st.session_state.current_card_index = 0
    if 'show_answer' not in st.session_state:
        st.session_state.show_answer = False
    if 'editing_card_id' not in st.session_state:
        st.session_state.editing_card_id = None

# --- Fonctions d'affichage ---
def display_content(content, title):
    """Affiche le contenu (texte ou image)."""
    st.subheader(title)
    if not content:
        st.warning("Contenu introuvable.")
    elif isinstance(content, str) and (content.startswith(('http://', 'https://')) or os.path.exists(content)):
        st.image(content, use_container_width=True)
    elif isinstance(content, str):
         st.markdown(f"<div style='font-size: 1.25rem; border: 1px solid #ddd; padding: 1rem; border-radius: 0.5rem; background-color: #1C83E1;'>{content}</div>", unsafe_allow_html=True)
    else:
        st.warning(f"Contenu inattendu ou chemin invalide : {content}")

def display_card_face_content(container, title, path, text):
    """Affiche le contenu d'une face de carte dans un conteneur donné (st, col, etc.)."""
    if title:
        container.markdown(f"**{title}**")
        
    if path:
        if path.startswith(('http://', 'https://')) or os.path.exists(path):
            container.image(path, use_container_width=True)
        else:
            container.error(f"Image locale introuvable : {os.path.basename(path)}")
    elif text:
        container.markdown(text)
    else:
        container.warning("Contenu vide")


# --- Section 1: Séance de révision ---
def display_review_session():
    st.header("🎯 Séance de révision")
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Choisissez un mode de révision")

        # Mode 1: Révision du jour
        st.markdown("**Révision du Jour**")
        cards_due_today = get_cards_for_daily_review()
        if st.button(f"Démarrer la révision du jour ({len(cards_due_today)} cartes)", use_container_width=True, type="primary"):
            if cards_due_today:
                st.session_state.review_cards = cards_due_today
                st.session_state.current_card_index = 0
                st.session_state.show_answer = False
                st.rerun()
            else:
                st.toast("Aucune carte à réviser pour aujourd'hui. Reposez-vous !", icon="🌴")

        st.markdown("---")

        # Mode 2: Révision par boîte
        st.markdown("**Révision par Boîte**")
        all_cards = load_flashcards()
        if all_cards:
            existing_boxes = sorted(list(set(c['box'] for c in all_cards)))
            box_options = ["-- Choisir une boîte --"] + existing_boxes
            box_to_review = st.selectbox("Boîtes disponibles:", options=box_options)

            if st.button("Démarrer la révision de la boîte", use_container_width=True):
                if box_to_review != "-- Choisir une boîte --":
                    st.session_state.review_cards = get_cards_for_box_review(box_number=int(box_to_review))
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
            
            question_content = (card.get('recto_path') or card.get('recto_text')) if is_recto_question else (card.get('verso_path') or card.get('verso_text'))
            answer_content = (card.get('verso_path') or card.get('verso_text')) if is_recto_question else (card.get('recto_path') or card.get('recto_text'))
            question_title = "Recto (Question)" if is_recto_question else "Verso (Question)"
            answer_title = "Verso (Réponse)" if is_recto_question else "Recto (Réponse)"

            display_content(question_content, question_title)
            st.markdown("---")

            if st.session_state.show_answer:
                display_content(answer_content, answer_title)
                st.markdown("---")

                def handle_response(correct):
                    all_cards = load_flashcards()
                    # La date de la révision actuelle est la base pour les calculs
                    review_date = datetime.now()
                    

                    for i, c in enumerate(all_cards):
                        if c['id'] == card['id']:
                            if correct:
                                new_box = min(60, c['box'] + 1)
                                icon, message = "🎉", f"Bravo ! Carte déplacée vers la boîte n°{new_box}."
                            else:
                                new_box = max(1, c['box'] - 1)
                                icon, message = "📚", f"Pas de souci. Carte déplacée vers la boîte n°{new_box}."
                            
                            all_cards[i]['box'] = new_box
                            # === MODIFICATION ===
                            # La date de révision devient la date du jour.
                            all_cards[i]['last_reviewed_date'] = review_date.strftime('%Y-%m-%d')
                            # La prochaine révision est calculée à partir de la date de révision actuelle.
                            all_cards[i]['next_review_date'] = (review_date + timedelta(days=new_box)).strftime('%Y-%m-%d')
                            # ====================
                            all_cards[i]['current_face'] = 'verso' if c.get('current_face', 'recto') == 'recto' else 'recto'
                            break
                    save_flashcards(all_cards)
                    st.toast(message, icon=icon)
                    st.session_state.current_card_index += 1
                    st.session_state.show_answer = False
                    time.sleep(1)
                    st.rerun()

                def handle_pass():
                    st.toast("Carte passée.", icon="⏭️")
                    st.session_state.current_card_index += 1
                    st.session_state.show_answer = False
                    time.sleep(1)
                    st.rerun()

                btn_col1, btn_col2, btn_col3 = st.columns(3)
                with btn_col1:
                    if st.button("✅ Correct", use_container_width=True, type="primary"): handle_response(correct=True)
                with btn_col2:
                    if st.button("❌ Incorrect", use_container_width=True): handle_response(correct=False)
                with btn_col3:
                    if st.button("⏭️ Pass", use_container_width=True, type="secondary"): handle_pass()
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
        st.info("Aucune carte créée. Allez dans 'Créer une nouvelle carte'.")
        return

    if st.session_state.editing_card_id:
        display_edit_form()
        return

    # 1. Sélection de la boîte
    existing_boxes = sorted(list(set(c['box'] for c in all_cards)))
    box_options = ["-- Choisir une boîte --"] + existing_boxes
    selected_box = st.selectbox("Choisissez une boîte à inspecter:", options=box_options)

    if selected_box != "-- Choisir une boîte --":
        cards_in_box = [c for c in all_cards if c['box'] == int(selected_box)]
        
        # 2. Sélection de la carte dans la boîte
        card_labels = ["-- Choisir une carte --"]
        for i, card in enumerate(cards_in_box):
            recto_content = card.get('recto_text') or os.path.basename(card.get('recto_path', ''))
            label = f"Carte {i+1}: {str(recto_content)[:30]}..." if recto_content else f"Carte {i+1}"
            card_labels.append(f"{label} ({card['id']})")
        
        selected_card_label = st.selectbox("Choisissez une carte:", options=card_labels)

        if selected_card_label != "-- Choisir une carte --":
            card_id_to_display = selected_card_label.split('(')[-1].replace(')', '')
            card_to_display = next((c for c in cards_in_box if c['id'] == card_id_to_display), None)
            
            if card_to_display:
                # 3. Affichage de la carte sélectionnée
                st.markdown("---")
                st.subheader(f"Détails de la carte (Boîte n°{card_to_display['box']})")

                creation_date = card_to_display.get('creation_date', 'N/A')
                last_review = card_to_display.get('last_reviewed_date') or 'Jamais'
                next_review = card_to_display.get('next_review_date', 'N/A')
                face = card_to_display.get('current_face', 'recto').capitalize()
                
                st.markdown(f"""
                - **Date de création :** `{creation_date}`
                - **Dernière révision :** `{last_review}`
                - **Prochaine révision :** `{next_review}`
                - **Face pour la question :** `{face}`
                """)
                st.markdown("---")

                c1, c2, c3 = st.columns([2, 2, 1])
                display_card_face_content(c1, "Recto", card_to_display.get('recto_path'), card_to_display.get('recto_text'))
                display_card_face_content(c2, "Verso", card_to_display.get('verso_path'), card_to_display.get('verso_text'))
                
                with c3:
                    st.markdown("**Actions**")
                    if st.button("Modifier", key=f"edit_{card_to_display['id']}", use_container_width=True):
                        st.session_state.editing_card_id = card_to_display['id']
                        st.rerun()
                    if st.button("Supprimer", key=f"del_{card_to_display['id']}", use_container_width=True, type="secondary"):
                        delete_image_file(card_to_display.get('recto_path'))
                        delete_image_file(card_to_display.get('verso_path'))
                        new_cards = [c for c in all_cards if c['id'] != card_to_display['id']]
                        save_flashcards(new_cards)
                        st.toast("Carte supprimée !", icon="🗑️")
                        st.rerun()

# --- Section 3: Modifier une carte ---
def display_edit_form():
    st.subheader("✏️ Modification de la carte")
    all_cards = load_flashcards()
    card_to_edit = next((c for c in all_cards if c['id'] == st.session_state.editing_card_id), None)
    if not card_to_edit:
        st.error("Carte non trouvée.")
        st.session_state.editing_card_id = None
        return

    with st.form("edit_card_form"):
        st.write(f"Modification de la carte de la boîte n°{card_to_edit['box']}")
        new_box = st.number_input("Changer la boîte", min_value=1, max_value=60, value=card_to_edit['box'])
        
        st.markdown("**Contenu Recto Actuel**")
        display_card_face_content(st, "", card_to_edit.get('recto_path'), card_to_edit.get('recto_text'))
        new_recto_text = st.text_area("Nouveau Texte Recto", value=card_to_edit.get('recto_text', ''), key="edit_recto_text")
        
        # --- FIX STARTS HERE ---
        recto_path_value = card_to_edit.get('recto_path')
        recto_url_default = recto_path_value if isinstance(recto_path_value, str) and recto_path_value.startswith('http') else ''
        new_recto_url = st.text_input("Nouveau Lien image Recto", value=recto_url_default, key="edit_recto_url")
        # --- FIX ENDS HERE ---
        
        new_recto_upload = st.file_uploader("Nouvelle Image locale Recto", type=['png', 'jpg', 'jpeg'], key="edit_recto_img")
        
        st.markdown("**Contenu Verso Actuel**")
        display_card_face_content(st, "", card_to_edit.get('verso_path'), card_to_edit.get('verso_text'))
        new_verso_text = st.text_area("Nouveau Texte Verso", value=card_to_edit.get('verso_text', ''), key="edit_verso_text")

        # --- FIX STARTS HERE ---
        verso_path_value = card_to_edit.get('verso_path')
        verso_url_default = verso_path_value if isinstance(verso_path_value, str) and verso_path_value.startswith('http') else ''
        new_verso_url = st.text_input("Nouveau Lien image Verso", value=verso_url_default, key="edit_verso_url")
        # --- FIX ENDS HERE ---

        new_verso_upload = st.file_uploader("Nouvelle Image locale Verso", type=['png', 'jpg', 'jpeg'], key="edit_verso_img")

        if st.form_submit_button("Sauvegarder"):
            idx = next((i for i, c in enumerate(all_cards) if c['id'] == st.session_state.editing_card_id), -1)
            if idx != -1:
                all_cards[idx]['box'] = new_box

                # === MODIFICATION ===
                # Pour le recalcul manuel, on se base sur la dernière date de révision si elle existe,
                # sinon sur la date de création.
                base_date_str = all_cards[idx].get('last_reviewed_date') or all_cards[idx].get('creation_date')
                if base_date_str:
                    base_date = datetime.strptime(base_date_str, '%Y-%m-%d')
                else:
                    # Fallback au cas où aucune date n'existe
                    base_date = datetime.now()
                all_cards[idx]['next_review_date'] = (base_date + timedelta(days=new_box)).strftime('%Y-%m-%d')
                # ====================

                # Mise à jour Recto
                if new_recto_upload:
                    delete_image_file(all_cards[idx].get('recto_path'))
                    all_cards[idx]['recto_path'] = save_uploaded_file(new_recto_upload)
                    all_cards[idx]['recto_text'] = None
                elif new_recto_url:
                    delete_image_file(all_cards[idx].get('recto_path'))
                    all_cards[idx]['recto_path'] = new_recto_url
                    all_cards[idx]['recto_text'] = None
                else:
                    delete_image_file(all_cards[idx].get('recto_path'))
                    all_cards[idx]['recto_path'] = None
                    all_cards[idx]['recto_text'] = new_recto_text
                
                # Mise à jour Verso
                if new_verso_upload:
                    delete_image_file(all_cards[idx].get('verso_path'))
                    all_cards[idx]['verso_path'] = save_uploaded_file(new_verso_upload)
                    all_cards[idx]['verso_text'] = None
                elif new_verso_url:
                    delete_image_file(all_cards[idx].get('verso_path'))
                    all_cards[idx]['verso_path'] = new_verso_url
                    all_cards[idx]['verso_text'] = None
                else:
                    delete_image_file(all_cards[idx].get('verso_path'))
                    all_cards[idx]['verso_path'] = None
                    all_cards[idx]['verso_text'] = new_verso_text

                save_flashcards(all_cards)
                st.toast("Carte modifiée !", icon="✅")
                st.session_state.editing_card_id = None
                st.rerun()

    if st.button("Annuler"):
        st.session_state.editing_card_id = None
        st.rerun()

# --- Section 4: Créer une carte ---
def display_create_card():
    st.header("➕ Créer une nouvelle carte")
    with st.form("new_card_form", clear_on_submit=True):
        st.subheader("Recto (Question)")
        recto_text = st.text_area("Texte", key="recto_txt")
        recto_url = st.text_input("Lien image web", key="recto_url")
        recto_upload = st.file_uploader("Image locale", type=['png', 'jpg', 'jpeg'], key="recto_up")
        
        st.subheader("Verso (Réponse)")
        verso_text = st.text_area("Texte", key="verso_txt")
        verso_url = st.text_input("Lien image web", key="verso_url")
        verso_upload = st.file_uploader("Image locale", type=['png', 'jpg', 'jpeg'], key="verso_up")
        
        initial_box = st.number_input("Boîte de départ", min_value=1, max_value=60, value=1)
        
        submitted = st.form_submit_button("Ajouter la carte")
        if submitted:
            recto_path, recto_text_val = (save_uploaded_file(recto_upload), None) if recto_upload else (recto_url, None) if recto_url else (None, recto_text)
            verso_path, verso_text_val = (save_uploaded_file(verso_upload), None) if verso_upload else (verso_url, None) if verso_url else (None, verso_text)

            if (recto_path or recto_text_val) and (verso_path or verso_text_val):
                all_cards = load_flashcards()
                creation_date = datetime.now()
                new_card = {
                    "box": initial_box,
                    "creation_date": creation_date.strftime('%Y-%m-%d'),
                    "current_face": "recto",
                    "id": str(uuid.uuid4()),
                    "last_reviewed_date": None,
                    "next_review_date": (creation_date + timedelta(days=initial_box)).strftime('%Y-%m-%d'),
                    "recto_path": recto_path, 
                    "recto_text": recto_text_val,
                    "verso_path": verso_path, 
                    "verso_text": verso_text_val
                }
                all_cards.append(new_card)
                save_flashcards(all_cards)
                st.success("Carte ajoutée ! Le formulaire a été réinitialisé.")
            else:
                st.error("Le recto et le verso doivent avoir un contenu.")

# --- Point d'entrée principal ---
st.set_page_config(layout="wide", page_title="Révision Espacée")
st.title("🧠 Application de Révision à Répétition Espacée")

if check_password():
    initialize_session_state()
    menu = st.sidebar.radio("Navigation", ("Séance de révision", "Gérer les cartes", "Créer une nouvelle carte", "Habit Tracker"))
    st.sidebar.markdown("---")

    if menu == "Séance de révision":
        display_review_session()
    elif menu == "Gérer les cartes":
        display_card_management()
    elif menu == "Créer une nouvelle carte":
        display_create_card()
    elif menu == "Habit Tracker":
        display_habit_tracker()
