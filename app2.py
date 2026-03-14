"""
Flashcards — Révision Espacée
Flask webapp mobile-first, remplacement de l'app Streamlit.
Templates dans le dossier templates/.
"""

import fcntl
import json
import os
import uuid
import random
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, send_from_directory
)
from werkzeug.utils import secure_filename

# ─── Configuration ───────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "Kiwy")

CARDS_FILE = "flashcards.json"
IMAGE_DIR = "images"
AUDIO_DIR = "audios"
REVIEW_DIR = "review_sessions"
BACKUP_DIR = "backups"
MAX_BACKUPS = 20
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_AUDIO = {"mp3", "wav", "ogg", "m4a", "aac"}
MAX_NEW_CARDS_PER_DAY = 10
MAX_DAILY_REVIEWS = 350

def box_interval(box):
    """Intervalle de révision : linéaire pour les boîtes 1-8, puis box^1.1."""
    if box <= 8:
        return box
    return round(box ** 1.1)

os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(REVIEW_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

# ─── Server-side review session storage (avoids cookie size limits) ──────────

def _review_path():
    sid = session.get("_review_sid")
    if not sid:
        sid = str(uuid.uuid4())
        session["_review_sid"] = sid
    return os.path.join(REVIEW_DIR, f"{sid}.json")

def save_review_state(cards, index, show_answer, **extra):
    p = _review_path()
    existing = {}
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass
    data = {
        "cards": cards,
        "index": index,
        "show_answer": show_answer,
        "correct": extra.get("correct", existing.get("correct", 0)),
        "incorrect": extra.get("incorrect", existing.get("incorrect", 0)),
        "pass_count": extra.get("pass_count", existing.get("pass_count", 0)),
        "start_time": extra.get("start_time", existing.get("start_time", datetime.now().isoformat())),
    }
    with open(_review_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

def load_review_state():
    p = _review_path()
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("correct", 0)
        data.setdefault("incorrect", 0)
        data.setdefault("pass_count", 0)
        data.setdefault("start_time", datetime.now().isoformat())
        return data
    return {"cards": [], "index": 0, "show_answer": False,
            "correct": 0, "incorrect": 0, "pass_count": 0,
            "start_time": datetime.now().isoformat()}

def clear_review_state():
    p = _review_path()
    if os.path.exists(p):
        os.remove(p)

def cleanup_stale_sessions(max_age_hours=24):
    """Remove review session files older than max_age_hours."""
    now = datetime.now().timestamp()
    for fname in os.listdir(REVIEW_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(REVIEW_DIR, fname)
        try:
            age_hours = (now - os.path.getmtime(path)) / 3600
            if age_hours > max_age_hours:
                os.remove(path)
        except OSError:
            pass

# ─── Helpers ─────────────────────────────────────────────────────────────────

def create_backup():
    """Snapshot the current flashcards.json into backups/ before any write."""
    if not os.path.exists(CARDS_FILE):
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BACKUP_DIR, f"flashcards_{ts}.json")
    try:
        import shutil
        shutil.copy2(CARDS_FILE, dest)
        # Keep only the MAX_BACKUPS most recent files
        backups = sorted(
            [f for f in os.listdir(BACKUP_DIR) if f.endswith(".json")],
            reverse=True
        )
        for old in backups[MAX_BACKUPS:]:
            os.remove(os.path.join(BACKUP_DIR, old))
    except Exception:
        pass

def list_backups():
    """Return backup metadata sorted newest first."""
    files = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.endswith(".json")],
        reverse=True
    )
    result = []
    for fname in files:
        path = os.path.join(BACKUP_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            count = len(data) if isinstance(data, list) else 0
        except Exception:
            count = "?"
        size_kb = round(os.path.getsize(path) / 1024, 1)
        # Parse timestamp from filename: flashcards_YYYYMMDD_HHMMSS.json
        try:
            ts_str = fname.replace("flashcards_", "").replace(".json", "")
            dt = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            label = dt.strftime("%d/%m/%Y à %H:%M:%S")
        except Exception:
            label = fname
        result.append({"filename": fname, "label": label, "count": count, "size_kb": size_kb})
    return result

LOCK_FILE = CARDS_FILE + ".lock"

def load_flashcards():
    if not os.path.exists(CARDS_FILE):
        return []
    try:
        with open(CARDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def save_flashcards(cards):
    create_backup()
    with open(CARDS_FILE, "w", encoding="utf-8") as f:
        json.dump(cards, f, indent=4, ensure_ascii=False, sort_keys=True)

@contextmanager
def locked_flashcards():
    """Load, yield, and save flashcards with an exclusive file lock.
    Usage:
        with locked_flashcards() as cards:
            # modify cards in place
    Cards are saved automatically on exit (unless an exception occurs).
    """
    with open(LOCK_FILE, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            cards = load_flashcards()
            yield cards
            save_flashcards(cards)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def save_uploaded_image(file_storage):
    if file_storage and allowed_file(file_storage.filename):
        ext = file_storage.filename.rsplit(".", 1)[1].lower()
        unique_name = f"{uuid.uuid4()}.{ext}"
        path = os.path.join(IMAGE_DIR, unique_name)
        file_storage.save(path)
        return path
    return None

def delete_image_file(path):
    if path and not path.startswith("http") and os.path.exists(path):
        os.remove(path)

def allowed_audio_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_AUDIO

def save_uploaded_audio(file_storage):
    if file_storage and allowed_audio_file(file_storage.filename):
        ext = file_storage.filename.rsplit(".", 1)[1].lower()
        unique_name = f"{uuid.uuid4()}.{ext}"
        path = os.path.join(AUDIO_DIR, unique_name)
        file_storage.save(path)
        return unique_name  # store only filename, served via /audios/
    return None

def index_by_id(cards):
    """Build a dict {card_id: (index, card)} for O(1) lookup."""
    return {c["id"]: (i, c) for i, c in enumerate(cards)}

def next_available_review_date(all_cards):
    """Find the earliest day (starting tomorrow) with fewer than MAX_NEW_CARDS_PER_DAY new cards scheduled."""
    from collections import Counter
    tomorrow = datetime.now() + timedelta(days=1)
    # Count new cards (box 1, never reviewed) per scheduled date
    new_card_counts = Counter(
        c["next_review_date"] for c in all_cards
        if c.get("box") == 1 and c.get("last_reviewed_date") is None
    )
    day = tomorrow
    while True:
        date_str = day.strftime("%Y-%m-%d")
        if new_card_counts.get(date_str, 0) < MAX_NEW_CARDS_PER_DAY:
            return date_str
        day += timedelta(days=1)

def get_daily_review_cards():
    today = datetime.now().strftime("%Y-%m-%d")
    due = [c for c in load_flashcards() if c.get("next_review_date", "") <= today]
    if len(due) <= MAX_DAILY_REVIEWS:
        return due, len(due)
    # Priority: low boxes first, then most overdue
    due.sort(key=lambda c: (c.get("box", 1), c.get("next_review_date", "")))
    return due[:MAX_DAILY_REVIEWS], len(due)

def get_marked_cards():
    return [c for c in load_flashcards() if c.get("marked", False)]

# ─── Auth ────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        flash("Mot de passe incorrect.", "error")
    return render_template("login.html", title="Connexion", body_class="", active="")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ─── Serve local images ─────────────────────────────────────────────────────

@app.route("/images/<path:filename>")
@login_required
def serve_image(filename):
    return send_from_directory(IMAGE_DIR, filename)

@app.route("/audios/<path:filename>")
@login_required
def serve_audio(filename):
    return send_from_directory(AUDIO_DIR, filename)

# ─── Pages ───────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    daily, total_due = get_daily_review_cards()
    marked = get_marked_cards()
    return render_template("index.html", title="Réviser", active="review", body_class="",
                           daily_count=len(daily), total_due=total_due, marked_count=len(marked))

# ── Review session ───────────────────────────────────────────────────────────

@app.route("/review/start/<mode>")
@login_required
def review_start(mode):
    cleanup_stale_sessions()
    if mode == "daily":
        cards, _ = get_daily_review_cards()
    elif mode == "marked":
        cards = get_marked_cards()
    else:
        cards = []
    random.shuffle(cards)
    if not cards:
        flash("Aucune carte à réviser !" if mode == "daily" else "Aucune carte marquée.", "info")
        return redirect(url_for("index"))
    save_review_state(cards, 0, False,
                      correct=0, incorrect=0, pass_count=0,
                      start_time=datetime.now().isoformat())
    return redirect(url_for("review_card"))

@app.route("/review")
@login_required
def review_card():
    state = load_review_state()
    cards = state["cards"]
    idx = state["index"]
    if not cards or idx >= len(cards):
        # Compute duration
        try:
            start_dt = datetime.fromisoformat(state.get("start_time", datetime.now().isoformat()))
            elapsed = int((datetime.now() - start_dt).total_seconds())
        except Exception:
            elapsed = 0
        minutes, seconds = divmod(elapsed, 60)
        duration = f"{minutes}m {seconds:02d}s"
        summary = {
            "correct": state.get("correct", 0),
            "incorrect": state.get("incorrect", 0),
            "pass_count": state.get("pass_count", 0),
            "total": len(cards),
            "duration": duration,
        }
        clear_review_state()
        return render_template("review_done.html", title="Terminé !", active="review", body_class="", **summary)
    card = cards[idx]
    show_answer = state["show_answer"]
    is_recto = card.get("current_face", "recto") == "recto"
    question = card.get("recto_path") or card.get("recto_text") if is_recto else card.get("verso_path") or card.get("verso_text")
    answer = card.get("verso_path") or card.get("verso_text") if is_recto else card.get("recto_path") or card.get("recto_text")
    return render_template(
        "review.html", title="Révision", active="review", body_class="review-mode",
        card=card, question=question, answer=answer,
        show_answer=show_answer, idx=idx, total=len(cards)
    )

@app.route("/review/show")
@login_required
def review_show():
    state = load_review_state()
    save_review_state(state["cards"], state["index"], True)
    return ("", 204)  # Called via fetch from JS fade animation

@app.route("/review/answer/<result>")
@login_required
def review_answer(result):
    state = load_review_state()
    cards = state["cards"]
    idx = state["index"]
    correct = state.get("correct", 0)
    incorrect = state.get("incorrect", 0)
    pass_count = state.get("pass_count", 0)
    if result == "correct":
        correct += 1
    elif result == "incorrect":
        incorrect += 1
    else:
        pass_count += 1
    if idx < len(cards):
        card = cards[idx]
        with locked_flashcards() as all_cards:
            card_index = index_by_id(all_cards)
            if card["id"] in card_index:
                i, c = card_index[card["id"]]
                now = datetime.now()
                if result == "correct":
                    all_cards[i]["box"] = min(60, c["box"] + 1)
                elif result == "incorrect":
                    all_cards[i]["box"] = max(1, c["box"] - 1)
                # pass → no change
                if result != "pass":
                    all_cards[i]["last_reviewed_date"] = now.strftime("%Y-%m-%d")
                    all_cards[i]["next_review_date"] = (now + timedelta(days=box_interval(all_cards[i]["box"]))).strftime("%Y-%m-%d")
                    all_cards[i]["current_face"] = "verso" if c.get("current_face", "recto") == "recto" else "recto"
    save_review_state(cards, idx + 1, False, correct=correct, incorrect=incorrect, pass_count=pass_count)
    return redirect(url_for("review_card"))

# ── Toggle mark from review ─────────────────────────────────────────────────

@app.route("/review/toggle_mark/<card_id>", methods=["POST"])
@login_required
def review_toggle_mark(card_id):
    with locked_flashcards() as all_cards:
        card_index = index_by_id(all_cards)
        if card_id in card_index:
            i, c = card_index[card_id]
            all_cards[i]["marked"] = not c.get("marked", False)
            # Also update server-side review session
            state = load_review_state()
            session_index = index_by_id(state["cards"])
            if card_id in session_index:
                ri, _ = session_index[card_id]
                state["cards"][ri]["marked"] = all_cards[i]["marked"]
            save_review_state(state["cards"], state["index"], state["show_answer"])
    return redirect(url_for("review_card"))

# ── Delete from review ───────────────────────────────────────────────────────

@app.route("/review/delete/<card_id>", methods=["POST"])
@login_required
def review_delete(card_id):
    with locked_flashcards() as all_cards:
        card_index = index_by_id(all_cards)
        _, card = card_index.get(card_id, (None, None))
        if card:
            delete_image_file(card.get("recto_path"))
            delete_image_file(card.get("verso_path"))
            all_cards[:] = [c for c in all_cards if c["id"] != card_id]
    # Remove from server-side review session
    state = load_review_state()
    new_cards = [c for c in state["cards"] if c["id"] != card_id]
    save_review_state(new_cards, state["index"], state["show_answer"])
    return redirect(url_for("review_card"))

# ── Quit review session ──────────────────────────────────────────────────────

@app.route("/review/quit", methods=["POST"])
@login_required
def review_quit():
    clear_review_state()
    return redirect(url_for("index"))

# ── Manage cards ─────────────────────────────────────────────────────────────

@app.route("/manage")
@login_required
def manage():
    all_cards = load_flashcards()
    boxes = sorted(set(c["box"] for c in all_cards))
    selected_box = request.args.get("box", type=int)
    filter_mode = request.args.get("filter", "")

    if filter_mode == "never_reviewed":
        cards_in_box = [c for c in all_cards if not c.get("last_reviewed_date")]
    elif selected_box is not None:
        cards_in_box = [c for c in all_cards if c["box"] == selected_box]
    else:
        cards_in_box = []

    never_count = sum(1 for c in all_cards if not c.get("last_reviewed_date"))
    return render_template("manage.html", title="Gérer", active="manage", body_class="",
                           boxes=boxes, selected_box=selected_box,
                           cards=cards_in_box, filter_mode=filter_mode, never_count=never_count)

@app.route("/card/<card_id>")
@login_required
def card_detail(card_id):
    all_cards = load_flashcards()
    _, card = index_by_id(all_cards).get(card_id, (None, None))
    if not card:
        flash("Carte introuvable.", "error")
        return redirect(url_for("manage"))
    return render_template("card_detail.html", title="Détails", active="manage", body_class="", card=card)

@app.route("/card/<card_id>/delete", methods=["POST"])
@login_required
def card_delete(card_id):
    with locked_flashcards() as all_cards:
        _, card = index_by_id(all_cards).get(card_id, (None, None))
        if card:
            delete_image_file(card.get("recto_path"))
            delete_image_file(card.get("verso_path"))
            all_cards[:] = [c for c in all_cards if c["id"] != card_id]
            flash("Carte supprimée.", "success")
    return redirect(url_for("manage"))

@app.route("/card/<card_id>/toggle_mark", methods=["POST"])
@login_required
def card_toggle_mark(card_id):
    with locked_flashcards() as all_cards:
        card_index = index_by_id(all_cards)
        if card_id in card_index:
            i, c = card_index[card_id]
            all_cards[i]["marked"] = not c.get("marked", False)
    return redirect(request.referrer or url_for("manage"))

@app.route("/card/<card_id>/edit", methods=["GET", "POST"])
@login_required
def card_edit(card_id):
    if request.method == "GET":
        all_cards = load_flashcards()
        _, card = index_by_id(all_cards).get(card_id, (None, None))
        if not card:
            flash("Carte introuvable.", "error")
            return redirect(url_for("manage"))
        from_review = request.args.get("from_review", "")
        return render_template("edit.html", title="Modifier", active="manage", body_class="",
                               card=card, from_review=from_review)

    # POST — lock for read-modify-write
    with locked_flashcards() as all_cards:
        card_index = index_by_id(all_cards)
        if card_id not in card_index:
            flash("Carte introuvable.", "error")
            return redirect(url_for("manage"))
        idx, card = card_index[card_id]

        new_box = int(request.form.get("box", card["box"]))
        all_cards[idx]["box"] = new_box
        base = all_cards[idx].get("last_reviewed_date") or all_cards[idx].get("creation_date")
        base_dt = datetime.strptime(base, "%Y-%m-%d") if base else datetime.now()
        all_cards[idx]["next_review_date"] = (base_dt + timedelta(days=box_interval(new_box))).strftime("%Y-%m-%d")

        # Recto
        recto_upload = request.files.get("recto_upload")
        recto_url = request.form.get("recto_url", "").strip()
        recto_text = request.form.get("recto_text", "").strip()
        recto_audio_upload = request.files.get("recto_audio_upload")
        if recto_upload and recto_upload.filename:
            delete_image_file(all_cards[idx].get("recto_path"))
            all_cards[idx]["recto_path"] = save_uploaded_image(recto_upload)
            all_cards[idx]["recto_text"] = None
        elif recto_url:
            delete_image_file(all_cards[idx].get("recto_path"))
            all_cards[idx]["recto_path"] = recto_url
            all_cards[idx]["recto_text"] = None
        else:
            delete_image_file(all_cards[idx].get("recto_path"))
            all_cards[idx]["recto_path"] = None
            all_cards[idx]["recto_text"] = recto_text or None
        if recto_audio_upload and recto_audio_upload.filename:
            all_cards[idx]["recto_audio"] = save_uploaded_audio(recto_audio_upload)

        # Verso
        verso_upload = request.files.get("verso_upload")
        verso_url = request.form.get("verso_url", "").strip()
        verso_text = request.form.get("verso_text", "").strip()
        verso_audio_upload = request.files.get("verso_audio_upload")
        if verso_upload and verso_upload.filename:
            delete_image_file(all_cards[idx].get("verso_path"))
            all_cards[idx]["verso_path"] = save_uploaded_image(verso_upload)
            all_cards[idx]["verso_text"] = None
        elif verso_url:
            delete_image_file(all_cards[idx].get("verso_path"))
            all_cards[idx]["verso_path"] = verso_url
            all_cards[idx]["verso_text"] = None
        else:
            delete_image_file(all_cards[idx].get("verso_path"))
            all_cards[idx]["verso_path"] = None
            all_cards[idx]["verso_text"] = verso_text or None
        if verso_audio_upload and verso_audio_upload.filename:
            all_cards[idx]["verso_audio"] = save_uploaded_audio(verso_audio_upload)

    flash("Carte modifiée !", "success")

    # If editing from review, go back to review
    if request.form.get("from_review"):
        # Update server-side review session
        state = load_review_state()
        session_index = index_by_id(state["cards"])
        if card_id in session_index:
            ri, _ = session_index[card_id]
            state["cards"][ri] = all_cards[idx]
        save_review_state(state["cards"], state["index"], state["show_answer"])
        return redirect(url_for("review_card"))
    return redirect(url_for("card_detail", card_id=card_id))

# ── Create card ──────────────────────────────────────────────────────────────

@app.route("/create", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        recto_upload = request.files.get("recto_upload")
        recto_url = request.form.get("recto_url", "").strip()
        recto_text = request.form.get("recto_text", "").strip()

        verso_upload = request.files.get("verso_upload")
        verso_url = request.form.get("verso_url", "").strip()
        verso_text = request.form.get("verso_text", "").strip()
        recto_audio_upload = request.files.get("recto_audio_upload")
        verso_audio_upload = request.files.get("verso_audio_upload")

        recto_path = recto_text_val = verso_path = verso_text_val = None
        recto_audio = verso_audio = None

        if recto_upload and recto_upload.filename:
            recto_path = save_uploaded_image(recto_upload)
        elif recto_url:
            recto_path = recto_url
        else:
            recto_text_val = recto_text

        if verso_upload and verso_upload.filename:
            verso_path = save_uploaded_image(verso_upload)
        elif verso_url:
            verso_path = verso_url
        else:
            verso_text_val = verso_text

        if recto_audio_upload and recto_audio_upload.filename:
            recto_audio = save_uploaded_audio(recto_audio_upload)
        if verso_audio_upload and verso_audio_upload.filename:
            verso_audio = save_uploaded_audio(verso_audio_upload)

        if (recto_path or recto_text_val or recto_audio) and (verso_path or verso_text_val or verso_audio):
            with locked_flashcards() as all_cards:
                now = datetime.now()
                review_date = next_available_review_date(all_cards)
                new_card = {
                    "box": 1,
                    "creation_date": now.strftime("%Y-%m-%d"),
                    "current_face": "recto",
                    "id": str(uuid.uuid4()),
                    "last_reviewed_date": None,
                    "marked": False,
                    "next_review_date": review_date,
                    "recto_path": recto_path,
                    "recto_text": recto_text_val,
                    "recto_audio": recto_audio,
                    "verso_path": verso_path,
                    "verso_text": verso_text_val,
                    "verso_audio": verso_audio,
                }
                all_cards.append(new_card)
            flash("Carte ajoutée !", "success")
            return redirect(url_for("create"))
        else:
            flash("Le recto et le verso doivent avoir un contenu.", "error")

    return render_template("create.html", title="Créer", active="create", body_class="")

# ── Dashboard ────────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    cards = load_flashcards()
    total = len(cards)
    if total == 0:
        return render_template("dashboard.html", title="Dashboard", active="dashboard", body_class="",
                               total=0, mastery=0, long_term_ratio=0,
                               box_data=[], timeline_data=[], workload_data=[],
                               activity_data=[], stage_data=[], health_data={},
                               creation_heatmap=[])

    box_sum = sum(c["box"] for c in cards)
    mastery = (box_sum / (total * 60)) * 100
    long_term = sum(1 for c in cards if c["box"] >= 20)
    long_term_ratio = (long_term / total) * 100

    # Box distribution
    from collections import Counter
    box_counts = Counter(c["box"] for c in cards)
    box_data = sorted(box_counts.items())

    # Timeline (cumulative cards by creation date)
    dates = sorted(c["creation_date"] for c in cards if c.get("creation_date"))
    date_counts = Counter(dates)
    cumulative = []
    running = 0
    for d in sorted(date_counts):
        running += date_counts[d]
        cumulative.append({"date": d, "count": running})

    # Future workload
    review_dates = [c["next_review_date"] for c in cards if c.get("next_review_date")]
    review_counts = Counter(review_dates)
    workload = [{"date": d, "count": n} for d, n in sorted(review_counts.items()) if d is not None][:30]

    today = datetime.now().date()

    # ── NEW: Creation heatmap (full year) ─────────────────────────────────────
    creation_counts = Counter(c["creation_date"] for c in cards if c.get("creation_date"))
    # Build a full 52-week grid ending today
    heatmap_end = today
    heatmap_start = heatmap_end - timedelta(days=364)
    heatmap_data = {}
    d = heatmap_start
    while d <= heatmap_end:
        ds = d.strftime("%Y-%m-%d")
        heatmap_data[ds] = creation_counts.get(ds, 0)
        d += timedelta(days=1)
    creation_heatmap = [{"date": ds, "count": v} for ds, v in sorted(heatmap_data.items())]

    # ── NEW: Daily review activity (last 30 days) ──────────────────────────────
    last_30 = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(29, -1, -1)]
    reviewed_dates = [c["last_reviewed_date"] for c in cards if c.get("last_reviewed_date")]
    reviewed_counts = Counter(reviewed_dates)
    activity_data = [{"date": d, "count": reviewed_counts.get(d, 0)} for d in last_30]

    # ── NEW: Stage distribution (Donut) ───────────────────────────────────────
    stage_data = {
        "Débutant (1–5)":       sum(1 for c in cards if 1 <= c["box"] <= 5),
        "Intermédiaire (6–19)": sum(1 for c in cards if 6 <= c["box"] <= 19),
        "Avancé (20–59)":       sum(1 for c in cards if 20 <= c["box"] <= 59),
        "Maîtrisé (60)":        sum(1 for c in cards if c["box"] >= 60),
    }

    # ── NEW: Card health (overdue / due today / upcoming / never reviewed) ─────
    today_str = today.strftime("%Y-%m-%d")
    health_data = {
        "En retard":         sum(1 for c in cards if c.get("next_review_date","") < today_str and c.get("last_reviewed_date")),
        "À réviser":         sum(1 for c in cards if c.get("next_review_date","") == today_str),
        "À venir":           sum(1 for c in cards if c.get("next_review_date","") > today_str),
        "Jamais révisées":   sum(1 for c in cards if not c.get("last_reviewed_date")),
    }

    return render_template(
        "dashboard.html", title="Dashboard", active="dashboard", body_class="",
        total=total, mastery=mastery, long_term_ratio=long_term_ratio,
        box_data=box_data, timeline_data=cumulative, workload_data=workload,
        activity_data=activity_data, stage_data=stage_data, health_data=health_data,
        creation_heatmap=creation_heatmap
    )

# ── API for search / filter (AJAX) ──────────────────────────────────────────

@app.route("/api/cards")
@login_required
def api_cards():
    q = request.args.get("q", "").lower()
    box = request.args.get("box", type=int)
    cards = load_flashcards()
    if box is not None:
        cards = [c for c in cards if c["box"] == box]
    if q:
        cards = [c for c in cards if q in (c.get("recto_text") or "").lower() or q in (c.get("verso_text") or "").lower()]
    return jsonify(cards[:100])  # Limit for perf

# ── Backups ──────────────────────────────────────────────────────────────────

@app.route("/backups")
@login_required
def backups():
    return render_template("backups.html", title="Sauvegardes", active="backups", body_class="",
                           backups=list_backups(), max_backups=MAX_BACKUPS)

@app.route("/backups/restore/<filename>", methods=["POST"])
@login_required
def backup_restore(filename):
    # Security: only allow filenames that match our pattern
    if not filename.startswith("flashcards_") or not filename.endswith(".json") or "/" in filename or ".." in filename:
        flash("Fichier invalide.", "error")
        return redirect(url_for("backups"))
    path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(path):
        flash("Sauvegarde introuvable.", "error")
        return redirect(url_for("backups"))
    try:
        with open(path, "r", encoding="utf-8") as f:
            restored = json.load(f)
        with locked_flashcards() as cards:
            cards[:] = restored
        flash(f"✅ Restauration réussie — {len(restored)} cartes rechargées.", "success")
    except Exception as e:
        flash(f"Erreur lors de la restauration : {e}", "error")
    return redirect(url_for("backups"))

@app.route("/backups/preview/<filename>")
@login_required
def backup_preview(filename):
    if not filename.startswith("flashcards_") or not filename.endswith(".json") or "/" in filename or ".." in filename:
        return jsonify({"error": "Fichier invalide"}), 400
    path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(path):
        return jsonify({"error": "Introuvable"}), 404
    try:
        with open(path, "r", encoding="utf-8") as f:
            cards = json.load(f)
        sample = [{"recto": c.get("recto_text", "🖼️ Image"), "verso": c.get("verso_text", "🖼️ Image"), "box": c.get("box")} for c in cards[:5]]
        return jsonify({"count": len(cards), "sample": sample})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Mindfulness / Zen ───────────────────────────────────────────────────────

@app.route("/zen")
@login_required
def zen():
    return render_template("zen.html", title="Zen", active="zen", body_class="")


# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
