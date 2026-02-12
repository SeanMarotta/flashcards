import pytest
from typing import List
from repository import FlashcardRepository
from model import Flashcard

class InMemoryRepo(FlashcardRepository):
    def __init__(self, cards: List[Flashcard] | None = None):
        self._cards = list(cards or [])

    def list_all(self) -> List[Flashcard]:
        return list(self._cards)

    def save_all(self, cards: List[Flashcard]) -> None:
        self._cards = list(cards)

@pytest.fixture
def repo():
    return InMemoryRepo()
