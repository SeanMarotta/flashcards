from dataclasses import dataclass
import os

@dataclass(frozen=True)
class AppSettings:
    cards_file: str = "flashcards.json"
    image_dir: str = "images"
    max_box: int = 60

def ensure_dirs(s: AppSettings) -> None:
    os.makedirs(s.image_dir, exist_ok=True)
