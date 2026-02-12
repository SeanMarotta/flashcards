from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

DATE_FMT = "%Y-%m-%d"

@dataclass
class Flashcard:
    id: str
    box: int
    creation_date: str
    next_review_date: str
    last_reviewed_date: Optional[str]
    current_face: str  # "recto" or "verso"
    recto_text: Optional[str]
    recto_path: Optional[str]
    verso_text: Optional[str]
    verso_path: Optional[str]
    marked: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Flashcard":
        # compat: si "marked" absent
        if "marked" not in d:
            d = dict(d)
            d["marked"] = False
        return Flashcard(**d)

    def due_on_or_before(self, date_str: str) -> bool:
        return (self.next_review_date or "") <= date_str

    def toggle_face(self) -> None:
        self.current_face = "verso" if self.current_face == "recto" else "recto"

    def schedule_next(self, review_date: datetime, max_box: int) -> None:
        self.last_reviewed_date = review_date.strftime(DATE_FMT)
        self.next_review_date = (review_date + timedelta(days=self.box)).strftime(DATE_FMT)
        if self.box > max_box:
            self.box = max_box

def today_str() -> str:
    return datetime.now().strftime(DATE_FMT)
