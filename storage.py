import os
import uuid
from typing import Optional

def save_uploaded_file(uploaded_file, image_dir: str) -> Optional[str]:
    if uploaded_file is None:
        return None
    ext = os.path.splitext(uploaded_file.name)[1]
    filename = f"{uuid.uuid4()}{ext}"
    path = os.path.join(image_dir, filename)
    with open(path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return path

def delete_image_file(image_path: Optional[str]) -> None:
    if not image_path:
        return
    if image_path.startswith(("http://", "https://")):
        return
    if os.path.exists(image_path):
        os.remove(image_path)
