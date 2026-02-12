from typing import List, Optional
from repository import FlashcardRepository
from services import ReviewService, CardService
from model import Flashcard

class ReviewController:
    def __init__(self, repo: FlashcardRepository, review_service: ReviewService):
        self.repo = repo
        self.review = review_service

    def start_daily(self) -> List[Flashcard]:
        cards = self.repo.list_all()
        return self.review.daily_due(cards)

    def start_marked(self) -> List[Flashcard]:
        cards = self.repo.list_all()
        return self.review.marked(cards)

    def answer(self, card_id: str, correct: bool) -> tuple[str, str, Flashcard]:
        cards = self.repo.list_all()
        card = next(c for c in cards if c.id == card_id)
        icon, message = self.review.apply_answer(card, correct)
        self.review.finalize_review(card)
        self.repo.save_all(cards)
        return icon, message, card

    def pass_card(self) -> tuple[str, str]:
        return "⏭️", "Carte passée."

class CardsController:
    def __init__(self, repo: FlashcardRepository, card_service: CardService):
        self.repo = repo
        self.cards = card_service

    def list_all(self) -> List[Flashcard]:
        return self.repo.list_all()

    def toggle_mark(self, card_id: str) -> Flashcard:
        cards = self.repo.list_all()
        card = next(c for c in cards if c.id == card_id)
        card.marked = not card.marked
        self.repo.save_all(cards)
        return card

    def delete(self, card_id: str) -> None:
        cards = self.repo.list_all()
        card = next(c for c in cards if c.id == card_id)
        self.cards.delete_card_assets(card)
        cards = [c for c in cards if c.id != card_id]
        self.repo.save_all(cards)

    def update(self, updated: Flashcard) -> Flashcard:
        cards = self.repo.list_all()
        idx = next(i for i, c in enumerate(cards) if c.id == updated.id)
        self.cards.recalc_next_review(updated)
        cards[idx] = updated
        self.repo.save_all(cards)
        return updated

    def create(self, card: Flashcard) -> None:
        cards = self.repo.list_all()
        cards.append(card)
        self.repo.save_all(cards)
