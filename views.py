import os
import streamlit as st
from typing import Optional, List
from model import Flashcard
from storage import save_uploaded_file, delete_image_file

def ui_set_style():
    st.set_page_config(layout="wide", page_title="Révision espacée (MVC)")
    st.markdown("""
    <style>
    img { max-height: 420px; object-fit: contain; }
    .flashcard {
      border: 1px solid rgba(255,255,255,0.12);
      background: rgba(255,255,255,0.06);
      padding: 1.1rem;
      border-radius: 16px;
      font-size: 1.3rem;      /* ← taille du texte */
      line-height: 1.5;       /* ← confort de lecture */
      font-weight: 400;      
    }
    </style>
    """, unsafe_allow_html=True)

def ui_check_password() -> bool:
    def password_entered():
        if "password" in st.session_state and st.session_state["password"] == st.secrets.get("password", "VOTRE_MOT_DE_PASSE_PAR_DEFAUT"):
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Mot de passe", type="password", on_change=password_entered, key="password")
        return False
    if not st.session_state["password_correct"]:
        st.text_input("Mot de passe", type="password", on_change=password_entered, key="password")
        st.error("😕 Mot de passe incorrect.")
        return False
    return True

def ui_init_state():
    st.session_state.setdefault("page", "review")
    st.session_state.setdefault("review_cards", [])
    st.session_state.setdefault("current_idx", 0)
    st.session_state.setdefault("show_answer", False)
    st.session_state.setdefault("editing_id", None)

def ui_display_face(content_path: Optional[str], content_text: Optional[str]):
    if content_path:
        if content_path.startswith(("http://", "https://")) or os.path.exists(content_path):
            st.image(content_path, use_container_width=True)
        else:
            st.error(f"Image introuvable : {os.path.basename(content_path)}")
    elif content_text:
        st.markdown(f"<div class='flashcard'>{content_text}</div>", unsafe_allow_html=True)
    else:
        st.warning("Contenu vide")

def ui_nav():
    st.sidebar.title("Navigation")
    choice = st.sidebar.radio("Menu", ["Séance de révision", "Gérer les cartes", "Créer une carte"])
    st.sidebar.markdown("---")
    st.session_state.page = {
        "Séance de révision": "review",
        "Gérer les cartes": "manage",
        "Créer une carte": "create",
    }[choice]

def ui_review_page(review_controller, cards_controller):
    col1, col2 = st.columns([1, 2])

    with col2:
        if st.button("😃 Démarrer la révision du jour", use_container_width=True):
            st.session_state.review_cards = review_controller.start_daily()
            st.session_state.current_idx = 0
            st.session_state.show_answer = False
            st.rerun()

        if st.button("📦 Réviser les cartes marquées", use_container_width=True):
            st.session_state.review_cards = review_controller.start_marked()
            st.session_state.current_idx = 0
            st.session_state.show_answer = False
            st.rerun()

    with col1:
        cards: List[Flashcard] = st.session_state.review_cards
        idx = st.session_state.current_idx

        if not cards:
            st.info("Aucune session en cours.")
            return
        if idx >= len(cards):
            st.success("🎉 Session terminée !")
            st.session_state.review_cards = []
            return

        card = cards[idx]

        # question/answer selon face courante
        is_recto_question = (card.current_face == "recto")
        q_path, q_text = (card.recto_path, card.recto_text) if is_recto_question else (card.verso_path, card.verso_text)
        a_path, a_text = (card.verso_path, card.verso_text) if is_recto_question else (card.recto_path, card.recto_text)

        if st.session_state.show_answer:
            b1, b2, b3 = st.columns(3)
            with b1:
                if st.button("✅ Correct", use_container_width=True, type="primary"):
                    icon, msg, updated = review_controller.answer(card.id, True)
                    st.toast(msg, icon=icon)
                    # refresh carte en session
                    st.session_state.review_cards[idx] = updated
                    st.session_state.current_idx += 1
                    st.session_state.show_answer = False
                    st.rerun()
            with b2:
                if st.button("❌ Incorrect", use_container_width=True):
                    icon, msg, updated = review_controller.answer(card.id, False)
                    st.toast(msg, icon=icon)
                    st.session_state.review_cards[idx] = updated
                    st.session_state.current_idx += 1
                    st.session_state.show_answer = False
                    st.rerun()
            with b3:
                if st.button("⏭️ Pass", use_container_width=True):
                    icon, msg = review_controller.pass_card()
                    st.toast(msg, icon=icon)
                    st.session_state.current_idx += 1
                    st.session_state.show_answer = False
                    st.rerun()

            ui_display_face(a_path, a_text)
            st.markdown("")
        else:
            if st.button("Afficher la réponse", use_container_width=True, type="primary"):
                st.session_state.show_answer = True
                st.rerun()

        ui_display_face(q_path, q_text)

        st.markdown("---")
        total = len(cards)
        progress = min(idx + 1, total)
        st.progress(progress / total, text=f"Carte {progress}/{total}")
        st.info(f"Boîte n°{card.box}")

        c1, c2, c3 = st.columns(3)
        with c1:
            label = "🔖 Démarquer" if card.marked else "🔖 Marquer"
            if st.button(label, use_container_width=True):
                updated = cards_controller.toggle_mark(card.id)
                st.session_state.review_cards[idx] = updated
                st.rerun()
        with c2:
            if st.button("✏️ Modifier", use_container_width=True):
                st.session_state.editing_id = card.id
                st.session_state.page = "manage"
                st.rerun()
        with c3:
            if st.button("🗑️ Supprimer", use_container_width=True, type="secondary"):
                cards_controller.delete(card.id)
                st.session_state.review_cards.pop(idx)
                st.toast("Carte supprimée !", icon="🗑️")
                st.rerun()

def ui_manage_page(cards_controller, image_dir: str):
    st.header("🗂️ Gérer les cartes")
    cards = cards_controller.list_all()
    if not cards:
        st.info("Aucune carte.")
        return

    # mode édition
    if st.session_state.editing_id:
        card = next((c for c in cards if c.id == st.session_state.editing_id), None)
        if not card:
            st.session_state.editing_id = None
            st.rerun()
        ui_edit_form(cards_controller, card, image_dir)
        return

    boxes = sorted(set(c.box for c in cards))
    selected = st.selectbox("Boîte", ["--"] + boxes)
    if selected == "--":
        return

    box_cards = [c for c in cards if c.box == int(selected)]
    labels = ["--"] + [f"{'🔖 ' if c.marked else ''}{(c.recto_text or os.path.basename(c.recto_path or '') or 'Carte')[:35]} ({c.id})" for c in box_cards]
    choice = st.selectbox("Carte", labels)
    if choice == "--":
        return

    card_id = choice.split("(")[-1].replace(")", "")
    card = next(c for c in box_cards if c.id == card_id)

    st.markdown("---")
    c1, c2, c3 = st.columns([2,2,1])
    with c1:
        st.subheader("Recto")
        ui_display_face(card.recto_path, card.recto_text)
    with c2:
        st.subheader("Verso")
        ui_display_face(card.verso_path, card.verso_text)
    with c3:
        st.subheader("Actions")
        if st.button("✏️ Modifier", use_container_width=True):
            st.session_state.editing_id = card.id
            st.rerun()
        if st.button("🗑️ Supprimer", use_container_width=True, type="secondary"):
            cards_controller.delete(card.id)
            st.toast("Carte supprimée", icon="🗑️")
            st.rerun()
        label = "Démarquer" if card.marked else "Marquer"
        if st.button(f"🔖 {label}", use_container_width=True):
            cards_controller.toggle_mark(card.id)
            st.rerun()

def ui_edit_form(cards_controller, card: Flashcard, image_dir: str):
    st.subheader("✏️ Modification")
    with st.form("edit_form"):
        new_box = st.number_input("Boîte", min_value=1, max_value=60, value=int(card.box))

        st.markdown("### Recto")
        ui_display_face(card.recto_path, card.recto_text)
        recto_text = st.text_area("Texte recto", value=card.recto_text or "")
        recto_url = st.text_input("URL image recto", value=card.recto_path if (card.recto_path or "").startswith("http") else "")
        recto_upload = st.file_uploader("Image locale recto", type=["png","jpg","jpeg"])

        st.markdown("### Verso")
        ui_display_face(card.verso_path, card.verso_text)
        verso_text = st.text_area("Texte verso", value=card.verso_text or "")
        verso_url = st.text_input("URL image verso", value=card.verso_path if (card.verso_path or "").startswith("http") else "")
        verso_upload = st.file_uploader("Image locale verso", type=["png","jpg","jpeg"])

        ok = st.form_submit_button("Sauvegarder")
        if ok:
            card.box = int(new_box)

            # Recto: upload > url > texte
            if recto_upload:
                delete_image_file(card.recto_path)
                card.recto_path = save_uploaded_file(recto_upload, image_dir)
                card.recto_text = None
            elif recto_url.strip():
                delete_image_file(card.recto_path)
                card.recto_path = recto_url.strip()
                card.recto_text = None
            else:
                delete_image_file(card.recto_path)
                card.recto_path = None
                card.recto_text = recto_text.strip() or None

            # Verso
            if verso_upload:
                delete_image_file(card.verso_path)
                card.verso_path = save_uploaded_file(verso_upload, image_dir)
                card.verso_text = None
            elif verso_url.strip():
                delete_image_file(card.verso_path)
                card.verso_path = verso_url.strip()
                card.verso_text = None
            else:
                delete_image_file(card.verso_path)
                card.verso_path = None
                card.verso_text = verso_text.strip() or None

            cards_controller.update(card)
            st.toast("Carte modifiée !", icon="✅")
            st.session_state.editing_id = None
            st.rerun()

    if st.button("Annuler"):
        st.session_state.editing_id = None
        st.rerun()

def ui_create_page(cards_controller, card_service, image_dir: str):
    st.header("➕ Créer une carte")
    with st.form("create_form", clear_on_submit=True):
        recto_text = st.text_input("Recto texte")
        recto_url = st.text_input("Recto URL image")
        recto_up = st.file_uploader("Recto image locale", type=["png","jpg","jpeg"])

        verso_text = st.text_input("Verso texte")
        verso_url = st.text_input("Verso URL image")
        verso_up = st.file_uploader("Verso image locale", type=["png","jpg","jpeg"])

        submitted = st.form_submit_button("Ajouter")
        if submitted:
            r_path = save_uploaded_file(recto_up, image_dir) if recto_up else (recto_url.strip() or None)
            v_path = save_uploaded_file(verso_up, image_dir) if verso_up else (verso_url.strip() or None)
            r_text = None if r_path else (recto_text.strip() or None)
            v_text = None if v_path else (verso_text.strip() or None)

            if not (r_path or r_text) or not (v_path or v_text):
                st.error("Recto et verso doivent avoir un contenu.")
                return

            card = card_service.create_card(r_text, r_path, v_text, v_path, initial_box=1)
            cards_controller.create(card)
            st.success("Carte ajoutée !")
