import streamlit as st
from settings import AppSettings, ensure_dirs
from repository import JsonFlashcardRepository
from services import ReviewService, CardService
from controllers import ReviewController, CardsController
from views import (
    ui_set_style, ui_check_password, ui_init_state, ui_nav,
    ui_review_page, ui_manage_page, ui_create_page
)

def main():
    settings = AppSettings()
    ensure_dirs(settings)

    repo = JsonFlashcardRepository(settings.cards_file)
    review_service = ReviewService(settings.max_box)
    card_service = CardService(settings.max_box)

    review_controller = ReviewController(repo, review_service)
    cards_controller = CardsController(repo, card_service)

    ui_set_style()

    if not ui_check_password():
        return

    ui_init_state()
    ui_nav()

    page = st.session_state.page
    if page == "review":
        ui_review_page(review_controller, cards_controller)
    elif page == "manage":
        ui_manage_page(cards_controller, settings.image_dir)
    elif page == "create":
        ui_create_page(cards_controller, card_service, settings.image_dir)

if __name__ == "__main__":
    main()
