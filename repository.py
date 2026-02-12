import json
import os
from typing import List, Optional
from model import Flashcard

class FlashcardRepository:
    def list_all(self) -> List[Flashcard]:
        raise NotImplementedError

    def save_all(self, cards: List[Flashcard]) -> None:
        raise NotImplementedError

    def get_by_id(self, card_id: str) -> Optional[Flashcard]:
        cards = self.list_all()
        return next((c for c in cards if c.id == card_id), None)

class JsonFlashcardRepository(FlashcardRepository):
    def __init__(self, cards_file: str):
        self.cards_file = cards_file

    def list_all(self) -> List[Flashcard]:
        if not os.path.exists(self.cards_file):
            return []
        try:
            with open(self.cards_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return [Flashcard.from_dict(x) for x in raw]
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def save_all(self, cards: List[Flashcard]) -> None:
        with open(self.cards_file, "w", encoding="utf-8") as f:
            json.dump([c.to_dict() for c in cards], f, indent=4, ensure_ascii=False, sort_keys=True)
