import random
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from model import Flashcard, today_str, DATE_FMT
from storage import delete_image_file

class ReviewService:
    def __init__(self, max_box: int):
        self.max_box = max_box

    def daily_due(self, cards: List[Flashcard]) -> List[Flashcard]:
        t = today_str()
        due = [c for c in cards if c.due_on_or_before(t)]
        random.shuffle(due)
        return due

    def marked(self, cards: List[Flashcard]) -> List[Flashcard]:
        res = [c for c in cards if c.marked]
        random.shuffle(res)
        return res

    def apply_answer(self, card: Flashcard, correct: bool) -> Tuple[str, str]:
        # retourne (icon, message)
        if correct:
            card.box = min(self.max_box, card.box + 1)
            return "🎉", f"Bravo ! boîte n°{card.box}."
        card.box = max(1, card.box - 1)
        return "📚", f"Incorrect. boîte n°{card.box}."

    def finalize_review(self, card: Flashcard) -> None:
        now = datetime.now()
        card.schedule_next(now, self.max_box)
        card.toggle_face()

class CardService:
    def __init__(self, max_box: int):
        self.max_box = max_box

    def create_card(
        self,
        recto_text: Optional[str], recto_path: Optional[str],
        verso_text: Optional[str], verso_path: Optional[str],
        initial_box: int = 1
    ) -> Flashcard:
        creation_date = datetime.now()
        return Flashcard(
            id=str(uuid.uuid4()),
            box=initial_box,
            creation_date=creation_date.strftime(DATE_FMT),
            next_review_date=(creation_date + timedelta(days=initial_box)).strftime(DATE_FMT),
            last_reviewed_date=None,
            current_face="recto",
            recto_text=recto_text, recto_path=recto_path,
            verso_text=verso_text, verso_path=verso_path,
            marked=False,
        )

    def recalc_next_review(self, card: Flashcard) -> None:
        base_str = card.last_reviewed_date or card.creation_date
        base = datetime.strptime(base_str, DATE_FMT) if base_str else datetime.now()
        card.next_review_date = (base + timedelta(days=card.box)).strftime(DATE_FMT)

    def delete_card_assets(self, card: Flashcard) -> None:
        delete_image_file(card.recto_path)
        delete_image_file(card.verso_path)
