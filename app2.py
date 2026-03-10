"""
Flashcards — Révision Espacée
Flask webapp mobile-first, remplacement de l'app Streamlit.
Un seul fichier Python. Templates HTML embarqués via render_template_string.
"""

import json
import os
import uuid
import random
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template_string, request, redirect,
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
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_AUDIO = {"mp3", "wav", "ogg", "m4a", "aac"}

os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(REVIEW_DIR, exist_ok=True)

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

# ─── Helpers ─────────────────────────────────────────────────────────────────

def load_flashcards():
    if not os.path.exists(CARDS_FILE):
        return []
    try:
        with open(CARDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def save_flashcards(cards):
    with open(CARDS_FILE, "w", encoding="utf-8") as f:
        json.dump(cards, f, indent=4, ensure_ascii=False, sort_keys=True)

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

def get_daily_review_cards():
    today = datetime.now().strftime("%Y-%m-%d")
    return [c for c in load_flashcards() if c.get("next_review_date", "") <= today]

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
    return render_template_string(LOGIN_HTML)

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
    daily = get_daily_review_cards()
    marked = get_marked_cards()
    return render_template_string(INDEX_HTML, daily_count=len(daily), marked_count=len(marked))

# ── Review session ───────────────────────────────────────────────────────────

@app.route("/review/start/<mode>")
@login_required
def review_start(mode):
    if mode == "daily":
        cards = get_daily_review_cards()
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
        return render_template_string(REVIEW_DONE_HTML, **summary)
    card = cards[idx]
    show_answer = state["show_answer"]
    is_recto = card.get("current_face", "recto") == "recto"
    question = card.get("recto_path") or card.get("recto_text") if is_recto else card.get("verso_path") or card.get("verso_text")
    answer = card.get("verso_path") or card.get("verso_text") if is_recto else card.get("recto_path") or card.get("recto_text")
    return render_template_string(
        REVIEW_HTML,
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
        all_cards = load_flashcards()
        for i, c in enumerate(all_cards):
            if c["id"] == card["id"]:
                now = datetime.now()
                if result == "correct":
                    all_cards[i]["box"] = min(60, c["box"] + 1)
                elif result == "incorrect":
                    all_cards[i]["box"] = max(1, c["box"] - 1)
                # pass → no change
                if result != "pass":
                    all_cards[i]["last_reviewed_date"] = now.strftime("%Y-%m-%d")
                    all_cards[i]["next_review_date"] = (now + timedelta(days=all_cards[i]["box"])).strftime("%Y-%m-%d")
                    all_cards[i]["current_face"] = "verso" if c.get("current_face", "recto") == "recto" else "recto"
                break
        save_flashcards(all_cards)
    save_review_state(cards, idx + 1, False, correct=correct, incorrect=incorrect, pass_count=pass_count)
    return redirect(url_for("review_card"))

# ── Toggle mark from review ─────────────────────────────────────────────────

@app.route("/review/toggle_mark/<card_id>")
@login_required
def review_toggle_mark(card_id):
    all_cards = load_flashcards()
    for i, c in enumerate(all_cards):
        if c["id"] == card_id:
            all_cards[i]["marked"] = not c.get("marked", False)
            # Also update server-side review session
            state = load_review_state()
            cards = state["cards"]
            for ri, rc in enumerate(cards):
                if rc["id"] == card_id:
                    cards[ri]["marked"] = all_cards[i]["marked"]
                    break
            save_review_state(cards, state["index"], state["show_answer"])
            break
    save_flashcards(all_cards)
    return redirect(url_for("review_card"))

# ── Delete from review ───────────────────────────────────────────────────────

@app.route("/review/delete/<card_id>")
@login_required
def review_delete(card_id):
    all_cards = load_flashcards()
    card = next((c for c in all_cards if c["id"] == card_id), None)
    if card:
        delete_image_file(card.get("recto_path"))
        delete_image_file(card.get("verso_path"))
        all_cards = [c for c in all_cards if c["id"] != card_id]
        save_flashcards(all_cards)
    # Remove from server-side review session
    state = load_review_state()
    new_cards = [c for c in state["cards"] if c["id"] != card_id]
    save_review_state(new_cards, state["index"], state["show_answer"])
    return redirect(url_for("review_card"))

# ── Quit review session ──────────────────────────────────────────────────────

@app.route("/review/quit")
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
    cards_in_box = [c for c in all_cards if c["box"] == selected_box] if selected_box is not None else []
    return render_template_string(MANAGE_HTML, boxes=boxes, selected_box=selected_box, cards=cards_in_box)

@app.route("/card/<card_id>")
@login_required
def card_detail(card_id):
    all_cards = load_flashcards()
    card = next((c for c in all_cards if c["id"] == card_id), None)
    if not card:
        flash("Carte introuvable.", "error")
        return redirect(url_for("manage"))
    return render_template_string(CARD_DETAIL_HTML, card=card)

@app.route("/card/<card_id>/delete")
@login_required
def card_delete(card_id):
    all_cards = load_flashcards()
    card = next((c for c in all_cards if c["id"] == card_id), None)
    if card:
        delete_image_file(card.get("recto_path"))
        delete_image_file(card.get("verso_path"))
        all_cards = [c for c in all_cards if c["id"] != card_id]
        save_flashcards(all_cards)
        flash("Carte supprimée.", "success")
    return redirect(url_for("manage"))

@app.route("/card/<card_id>/toggle_mark")
@login_required
def card_toggle_mark(card_id):
    all_cards = load_flashcards()
    for i, c in enumerate(all_cards):
        if c["id"] == card_id:
            all_cards[i]["marked"] = not c.get("marked", False)
            break
    save_flashcards(all_cards)
    return redirect(request.referrer or url_for("manage"))

@app.route("/card/<card_id>/edit", methods=["GET", "POST"])
@login_required
def card_edit(card_id):
    all_cards = load_flashcards()
    card = next((c for c in all_cards if c["id"] == card_id), None)
    if not card:
        flash("Carte introuvable.", "error")
        return redirect(url_for("manage"))

    if request.method == "POST":
        idx = next(i for i, c in enumerate(all_cards) if c["id"] == card_id)
        new_box = int(request.form.get("box", card["box"]))
        all_cards[idx]["box"] = new_box
        base = all_cards[idx].get("last_reviewed_date") or all_cards[idx].get("creation_date")
        base_dt = datetime.strptime(base, "%Y-%m-%d") if base else datetime.now()
        all_cards[idx]["next_review_date"] = (base_dt + timedelta(days=new_box)).strftime("%Y-%m-%d")

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

        save_flashcards(all_cards)
        flash("Carte modifiée !", "success")

        # If editing from review, go back to review
        if request.form.get("from_review"):
            # Update server-side review session
            state = load_review_state()
            for ri, rc in enumerate(state["cards"]):
                if rc["id"] == card_id:
                    state["cards"][ri] = all_cards[idx]
                    break
            save_review_state(state["cards"], state["index"], state["show_answer"])
            return redirect(url_for("review_card"))
        return redirect(url_for("card_detail", card_id=card_id))

    from_review = request.args.get("from_review", "")
    return render_template_string(EDIT_HTML, card=card, from_review=from_review)

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
            all_cards = load_flashcards()
            now = datetime.now()
            new_card = {
                "box": 1,
                "creation_date": now.strftime("%Y-%m-%d"),
                "current_face": "recto",
                "id": str(uuid.uuid4()),
                "last_reviewed_date": None,
                "marked": False,
                "next_review_date": (now + timedelta(days=1)).strftime("%Y-%m-%d"),
                "recto_path": recto_path,
                "recto_text": recto_text_val,
                "recto_audio": recto_audio,
                "verso_path": verso_path,
                "verso_text": verso_text_val,
                "verso_audio": verso_audio,
            }
            all_cards.append(new_card)
            save_flashcards(all_cards)
            flash("Carte ajoutée !", "success")
            return redirect(url_for("create"))
        else:
            flash("Le recto et le verso doivent avoir un contenu.", "error")

    return render_template_string(CREATE_HTML)

# ── Dashboard ────────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    cards = load_flashcards()
    total = len(cards)
    if total == 0:
        return render_template_string(DASHBOARD_HTML, total=0, mastery=0, long_term_ratio=0,
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

    return render_template_string(
        DASHBOARD_HTML,
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

# ── Mindfulness / Zen ───────────────────────────────────────────────────────

@app.route("/zen")
@login_required
def zen():
    return render_template_string(MINDFULNESS_HTML)

# ═══════════════════════════════════════════════════════════════════════════════
#  TEMPLATES
# ═══════════════════════════════════════════════════════════════════════════════

BASE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,500;0,9..40,700;1,9..40,400&family=Space+Mono:wght@400;700&display=swap');

:root {
    --bg: #0c0c0f;
    --surface: #16161a;
    --surface2: #1e1e24;
    --border: #2a2a32;
    --text: #e8e6e3;
    --text2: #94929d;
    --accent: #7f5af0;
    --accent2: #2cb67d;
    --danger: #e53170;
    --warning: #fbbf24;
    --radius: 16px;
    --radius-sm: 10px;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: 'DM Sans', sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100dvh;
    -webkit-font-smoothing: antialiased;
    overflow-x: hidden;
}

a { color: var(--accent); text-decoration: none; }

.container {
    max-width: 560px;
    margin: 0 auto;
    padding: 0 20px 100px 20px;
}

/* ── Top bar ─────────────────── */
.topbar {
    position: sticky;
    top: 0;
    z-index: 100;
    background: rgba(12,12,15,.85);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border-bottom: 1px solid var(--border);
    padding: 14px 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.topbar h1 {
    font-family: 'Space Mono', monospace;
    font-size: 1rem;
    letter-spacing: -0.5px;
}
.topbar-actions { display: flex; gap: 6px; }

/* ── Bottom nav ──────────────── */
/* ── Fixed review action bar ── */
.review-action-bar {
    position: fixed;
    bottom: 0;
    left: 0; right: 0;
    z-index: 110;
    background: rgba(12,12,15,.95);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border-top: 1px solid var(--border);
    padding: 12px 16px max(12px, env(safe-area-inset-bottom));
}
.review-action-bar .action-buttons {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 10px;
    max-width: 560px;
    margin: 0 auto;
}
.review-action-bar .btn { font-size: 1rem; padding: 16px 12px; }

/* When review bar is active, hide bottom nav and add extra padding */
body.review-mode .bottomnav { display: none; }
body.review-mode .container { padding-bottom: 120px; }

.bottomnav {
    position: fixed;
    bottom: 0;
    left: 0; right: 0;
    z-index: 100;
    background: rgba(12,12,15,.92);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border-top: 1px solid var(--border);
    display: flex;
    justify-content: space-around;
    padding: 8px 0 max(8px, env(safe-area-inset-bottom));
}
.bottomnav a {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    color: var(--text2);
    font-size: 0.7rem;
    padding: 6px 12px;
    border-radius: 12px;
    transition: all .2s;
}
.bottomnav a.active,
.bottomnav a:hover {
    color: var(--accent);
    background: rgba(127,90,240,.08);
}
.bottomnav a svg { width: 22px; height: 22px; }

/* ── Cards / Surfaces ────────── */
.card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 24px;
    margin-bottom: 16px;
    transition: transform .15s;
}
.card:active { transform: scale(0.985); }

.card-content {
    font-size: 1.25rem;
    line-height: 1.5;
    font-weight: 500;
    text-align: center;
    padding: 20px 0;
}
.card-content img {
    max-width: 100%;
    max-height: 50vh;
    object-fit: contain;
    border-radius: var(--radius-sm);
}

/* ── Buttons ─────────────────── */
.btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 14px 24px;
    border-radius: var(--radius-sm);
    font-family: 'DM Sans', sans-serif;
    font-size: 0.95rem;
    font-weight: 600;
    border: none;
    cursor: pointer;
    transition: all .2s;
    text-decoration: none;
    width: 100%;
}
.btn:active { transform: scale(0.97); }
.btn-primary { background: var(--accent); color: #fff; }
.btn-primary:hover { background: #6b46d6; }
.btn-success { background: var(--accent2); color: #fff; }
.btn-success:hover { background: #24a06e; }
.btn-danger { background: var(--danger); color: #fff; }
.btn-danger:hover { background: #c42a5f; }
.btn-ghost {
    background: transparent;
    color: var(--text);
    border: 1px solid var(--border);
}
.btn-ghost:hover { background: var(--surface2); }
.btn-sm { padding: 10px 16px; font-size: 0.85rem; }

.btn-row {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 10px;
    margin: 16px 0;
}
.btn-row-2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    margin: 16px 0;
}

/* ── Progress ────────────────── */
.progress-wrap {
    background: var(--surface2);
    border-radius: 99px;
    height: 6px;
    margin: 16px 0 8px;
    overflow: hidden;
}
.progress-bar {
    height: 100%;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    border-radius: 99px;
    transition: width .4s ease;
}
.progress-label {
    font-size: 0.8rem;
    color: var(--text2);
    text-align: center;
    font-family: 'Space Mono', monospace;
}

/* ── Badges / chips ──────────── */
.badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 12px;
    border-radius: 99px;
    font-size: 0.75rem;
    font-weight: 600;
    font-family: 'Space Mono', monospace;
}
.badge-accent { background: rgba(127,90,240,.15); color: var(--accent); }
.badge-green { background: rgba(44,182,125,.15); color: var(--accent2); }
.badge-warning { background: rgba(251,191,36,.15); color: var(--warning); }

/* ── Stats grid ──────────────── */
.stats-grid {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 12px;
    margin-bottom: 20px;
}
.stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 16px 12px;
    text-align: center;
}
.stat-value {
    font-family: 'Space Mono', monospace;
    font-size: 1.4rem;
    font-weight: 700;
    color: var(--accent);
}
.stat-label {
    font-size: 0.7rem;
    color: var(--text2);
    margin-top: 4px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

/* ── Chart ────────────────────── */
.chart-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px;
    margin-bottom: 16px;
}
.chart-card h3 {
    font-size: 0.85rem;
    color: var(--text2);
    margin-bottom: 12px;
    font-weight: 500;
}

/* ── Forms ────────────────────── */
.form-group { margin-bottom: 16px; }
.form-group label {
    display: block;
    font-size: 0.8rem;
    color: var(--text2);
    margin-bottom: 6px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.form-group input[type="text"],
.form-group input[type="number"],
.form-group input[type="password"],
.form-group textarea,
.form-group select {
    width: 100%;
    padding: 12px 16px;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text);
    font-family: 'DM Sans', sans-serif;
    font-size: 1rem;
    outline: none;
    transition: border-color .2s;
}
.form-group input:focus,
.form-group textarea:focus,
.form-group select:focus { border-color: var(--accent); }
.form-group textarea { min-height: 80px; resize: vertical; }
.form-group input[type="file"] {
    color: var(--text2);
    font-size: 0.85rem;
}

/* ── Flash messages ──────────── */
.flash {
    padding: 12px 16px;
    border-radius: var(--radius-sm);
    margin-bottom: 16px;
    font-size: 0.9rem;
    animation: slideDown .3s ease;
}
.flash-success { background: rgba(44,182,125,.12); color: var(--accent2); border: 1px solid rgba(44,182,125,.25); }
.flash-error { background: rgba(229,49,112,.12); color: var(--danger); border: 1px solid rgba(229,49,112,.25); }
.flash-info { background: rgba(127,90,240,.12); color: var(--accent); border: 1px solid rgba(127,90,240,.25); }

@keyframes slideDown { from { opacity:0; transform:translateY(-10px); } to { opacity:1; transform:translateY(0); } }

/* ── Box list ────────────────── */
.box-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(70px, 1fr));
    gap: 8px;
}
.box-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 12px 8px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    text-decoration: none;
    transition: all .2s;
}
.box-item:hover, .box-item.active {
    border-color: var(--accent);
    background: rgba(127,90,240,.06);
}
.box-num { font-family:'Space Mono',monospace; font-weight:700; font-size:1.1rem; color:var(--accent); }
.box-count { font-size:0.7rem; color:var(--text2); margin-top:2px; }

/* ── Card list items ─────────── */
.card-list-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 14px 16px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    margin-bottom: 8px;
    text-decoration: none;
    color: var(--text);
    transition: all .2s;
}
.card-list-item:hover { border-color: var(--accent); }
.card-list-item .preview {
    flex: 1;
    font-size: 0.9rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.card-list-item .marked-icon { color: var(--warning); }
.card-list-item img.thumb {
    width: 44px;
    height: 44px;
    object-fit: cover;
    border-radius: 8px;
    flex-shrink: 0;
}

/* ── Misc ────────────────────── */
.section-title {
    font-size: 0.8rem;
    color: var(--text2);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin: 24px 0 12px;
    font-weight: 600;
}
.empty-state {
    text-align: center;
    padding: 48px 20px;
    color: var(--text2);
}
.empty-state .icon { font-size: 3rem; margin-bottom: 12px; }

.meta-row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 12px 0;
}

.detail-face {
    background: var(--surface2);
    border-radius: var(--radius-sm);
    padding: 20px;
    margin-bottom: 12px;
    text-align: center;
}
.detail-face h4 {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--text2);
    margin-bottom: 12px;
}
.detail-face img { max-width:100%; max-height:40vh; object-fit:contain; border-radius:8px; }

/* ── Login ────────────────────── */
.login-wrap {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100dvh;
    padding: 20px;
}
.login-box {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 40px 32px;
    width: 100%;
    max-width: 380px;
    text-align: center;
}
.login-box h1 {
    font-family: 'Space Mono', monospace;
    font-size: 1.4rem;
    margin-bottom: 8px;
}
.login-box p { color: var(--text2); font-size: 0.9rem; margin-bottom: 24px; }

/* ── Review done ─────────────── */
.done-wrap {
    text-align: center;
    padding: 60px 20px;
}
.done-wrap .emoji { font-size: 4rem; margin-bottom: 16px; }
.done-wrap h2 { margin-bottom: 8px; }
.done-wrap p { color: var(--text2); margin-bottom: 24px; }

/* ── Confirm dialog ──────────── */
.confirm-overlay {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,.6);
    backdrop-filter: blur(4px);
    z-index: 200;
    align-items: center;
    justify-content: center;
    padding: 20px;
}
.confirm-overlay.show { display: flex; }
.confirm-box {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 28px 24px;
    max-width: 340px;
    width: 100%;
    text-align: center;
}
.confirm-box p { margin-bottom: 20px; font-size: 0.95rem; }
"""

NAV_ICONS = {
    "review": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
    "manage": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/></svg>',
    "create": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
    "dashboard": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
    "zen": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/><path d="M8 12s1-2 4-2 4 2 4 2"/><path d="M9 9h.01M15 9h.01"/></svg>',
}

def base_template(title, active, content, body_class=""):
    quit_btn = '<a href="/review/quit" class="btn btn-ghost btn-sm" style="width:auto;padding:8px 14px;font-size:.75rem;">🏠 Menu</a>' if body_class == "review-mode" else ""
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0c0c0f">
<title>{title}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🧠</text></svg>">
<style>{BASE_CSS}</style>
</head>
<body class="{body_class}">
<div class="topbar">
    <h1>⚡ Flashcards</h1>
    <div class="topbar-actions">
        {quit_btn}
        <a href="/logout" class="btn btn-ghost btn-sm" style="width:auto;padding:8px 14px;font-size:.75rem;">Déconnexion</a>
    </div>
</div>

<div class="container" style="padding-top:20px;">
    {{% with messages = get_flashed_messages(with_categories=true) %}}
    {{% if messages %}}
        {{% for category, message in messages %}}
        <div class="flash flash-{{{{ category }}}}">{{{{ message }}}}</div>
        {{% endfor %}}
    {{% endif %}}
    {{% endwith %}}

    {content}
</div>

<nav class="bottomnav">
    <a href="/" class="{{% if active == 'review' %}}active{{% endif %}}">
        {NAV_ICONS["review"]}<span>Réviser</span>
    </a>
    <a href="/manage" class="{{% if active == 'manage' %}}active{{% endif %}}">
        {NAV_ICONS["manage"]}<span>Gérer</span>
    </a>
    <a href="/create" class="{{% if active == 'create' %}}active{{% endif %}}">
        {NAV_ICONS["create"]}<span>Créer</span>
    </a>
    <a href="/dashboard" class="{{% if active == 'dashboard' %}}active{{% endif %}}">
        {NAV_ICONS["dashboard"]}<span>Stats</span>
    </a>
    <a href="/zen" class="{{% if active == 'zen' %}}active{{% endif %}}">
        {NAV_ICONS["zen"]}<span>Zen</span>
    </a>
</nav>
</body>
</html>"""

# Jinja helper for rendering card content (text or image + optional audio)
CONTENT_MACRO = """
{% macro render_content(path, text, audio=None) %}
{% if path and path.startswith('http') %}
    <img src="{{ path }}" alt="card image" loading="lazy">
{% elif path %}
    <img src="/{{ path }}" alt="card image" loading="lazy">
{% elif text %}
    <div>{{ text }}</div>
{% else %}
    <span style="color:var(--text2)">—</span>
{% endif %}
{% if audio %}
    <audio controls style="width:100%;margin-top:12px;border-radius:8px;">
        <source src="/audios/{{ audio }}">
    </audio>
{% endif %}
{% endmacro %}
"""

# ── Login ────────────────────────────────────────────────────────────────────

LOGIN_HTML = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0c0c0f">
<title>Connexion</title>
<style>{BASE_CSS}</style>
</head>
<body>
<div class="login-wrap">
    <div class="login-box">
        <h1>⚡ Flashcards</h1>
        <p>Révision espacée</p>
        {{% with messages = get_flashed_messages(with_categories=true) %}}
        {{% if messages %}}
            {{% for category, message in messages %}}
            <div class="flash flash-{{{{ category }}}}" style="text-align:left;">{{{{ message }}}}</div>
            {{% endfor %}}
        {{% endif %}}
        {{% endwith %}}
        <form method="POST">
            <div class="form-group">
                <input type="password" name="password" placeholder="Mot de passe" autofocus>
            </div>
            <button type="submit" class="btn btn-primary">Entrer</button>
        </form>
    </div>
</div>
</body>
</html>"""

# ── Index / Home ─────────────────────────────────────────────────────────────

INDEX_HTML = base_template("Réviser", "review", f"""
{CONTENT_MACRO}
<div style="padding:20px 0 8px;text-align:center;">
    <div style="font-size:2.5rem;margin-bottom:8px;">⚡</div>
    <h2 style="font-size:1.3rem;margin-bottom:4px;">Prêt à réviser ?</h2>
    <p style="color:var(--text2);font-size:0.9rem;">Choisis ton mode de révision</p>
</div>

<a href="/review/start/daily" class="btn btn-primary" style="margin-bottom:12px;">
    😃 Révision du jour — {{{{ daily_count }}}} cartes
</a>
<a href="/review/start/marked" class="btn btn-ghost" style="margin-bottom:12px;">
    📦 Cartes marquées — {{{{ marked_count }}}} cartes
</a>
""")

# ── Review card ──────────────────────────────────────────────────────────────

REVIEW_HTML = base_template("Révision", "review", f"""
{CONTENT_MACRO}

<div class="progress-wrap">
    <div class="progress-bar" style="width:{{{{ ((idx+1)/total*100)|round }}}}%"></div>
</div>
<div class="progress-label">{{{{ idx+1 }}}}/{{{{ total }}}}</div>

<div class="card">
    <div class="card-content">
        {{{{ render_content(
            card.recto_path if (card.current_face|default('recto'))=='recto' else card.verso_path,
            card.recto_text if (card.current_face|default('recto'))=='recto' else card.verso_text,
            card.recto_audio if (card.current_face|default('recto'))=='recto' else card.verso_audio
        ) }}}}
    </div>

    <div id="answer-section" style="border-top:1px solid var(--border);padding-top:20px;margin-top:12px;opacity:{{% if show_answer %}}1{{% else %}}0{{% endif %}};transition:opacity 0.5s ease;{{% if not show_answer %}}pointer-events:none;{{% endif %}}">
        <div class="card-content" style="padding-top:8px;">
            {{{{ render_content(
                card.verso_path if (card.current_face|default('recto'))=='recto' else card.recto_path,
                card.verso_text if (card.current_face|default('recto'))=='recto' else card.recto_text,
                card.verso_audio if (card.current_face|default('recto'))=='recto' else card.recto_audio
            ) }}}}
        </div>
    </div>
</div>

<div class="meta-row" style="justify-content:center;">
    <span class="badge badge-accent">Boîte {{{{ card.box }}}}</span>
    {{% if card.marked %}}<span class="badge badge-warning">🔖 Marquée</span>{{% endif %}}
</div>

<div class="btn-row" style="margin-top:8px;">
    <a href="/review/toggle_mark/{{{{ card.id }}}}" class="btn btn-ghost btn-sm">
        {{% if card.marked %}}🔖 Démarquer{{% else %}}🔖 Marquer{{% endif %}}
    </a>
    <a href="/card/{{{{ card.id }}}}/edit?from_review=1" class="btn btn-ghost btn-sm">✏️ Modifier</a>
    <button class="btn btn-ghost btn-sm" onclick="showConfirm()" style="color:var(--danger)">🗑️ Supprimer</button>
</div>

<!-- Fixed bottom action bar -->
<div id="bar-show" class="review-action-bar" style="{{% if show_answer %}}display:none;{{% endif %}}">
    <div class="action-buttons">
        <button onclick="revealAnswer()" class="btn btn-primary" style="grid-column:1/-1;">Voir la réponse</button>
    </div>
</div>
<div id="bar-answer" class="review-action-bar" style="{{% if not show_answer %}}display:none;{{% endif %}}">
    <div class="action-buttons">
        <a href="/review/answer/correct" class="btn btn-success">✅ Correct</a>
        <a href="/review/answer/incorrect" class="btn btn-danger">❌ Faux</a>
        <a href="/review/answer/pass" class="btn btn-ghost">⏭️ Pass</a>
    </div>
</div>

<div class="confirm-overlay" id="confirmDelete">
    <div class="confirm-box">
        <p>Supprimer cette carte ?</p>
        <div class="btn-row-2">
            <a href="/review/delete/{{{{ card.id }}}}" class="btn btn-danger btn-sm">Supprimer</a>
            <button class="btn btn-ghost btn-sm" onclick="hideConfirm()">Annuler</button>
        </div>
    </div>
</div>

<script>
function showConfirm() {{ document.getElementById('confirmDelete').classList.add('show'); }}
function hideConfirm() {{ document.getElementById('confirmDelete').classList.remove('show'); }}
async function revealAnswer() {{
    fetch('/review/show');  // update server state in background
    const ans = document.getElementById('answer-section');
    ans.style.pointerEvents = 'auto';
    requestAnimationFrame(() => {{ ans.style.opacity = '1'; }});
    document.getElementById('bar-show').style.display = 'none';
    document.getElementById('bar-answer').style.display = '';
}}
</script>
""", body_class="review-mode")

# ── Review done ──────────────────────────────────────────────────────────────

REVIEW_DONE_HTML = base_template("Terminé !", "review", """
<div class="done-wrap">
    <div class="emoji">🎉</div>
    <h2>Session terminée !</h2>
    <p>{{ total }} carte{{ 's' if total > 1 else '' }} révisée{{ 's' if total > 1 else '' }}</p>

    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin:24px 0;">
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:16px 8px;text-align:center;">
            <div style="font-size:1.6rem;font-weight:700;color:#2cb67d;">{{ correct }}</div>
            <div style="font-size:0.75rem;color:var(--text2);margin-top:4px;">✅ Correct</div>
        </div>
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:16px 8px;text-align:center;">
            <div style="font-size:1.6rem;font-weight:700;color:#e53170;">{{ incorrect }}</div>
            <div style="font-size:0.75rem;color:var(--text2);margin-top:4px;">❌ Faux</div>
        </div>
        <div style="background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:16px 8px;text-align:center;">
            <div style="font-size:1.6rem;font-weight:700;color:var(--text2);">{{ pass_count }}</div>
            <div style="font-size:0.75rem;color:var(--text2);margin-top:4px;">⏭️ Pass</div>
        </div>
    </div>

    <div style="font-size:0.9rem;color:var(--text2);margin-bottom:24px;">⏱️ Durée : {{ duration }}</div>

    <a href="/" class="btn btn-primary" style="max-width:280px;margin:0 auto;">Retour</a>
</div>
""")

# ── Manage cards ─────────────────────────────────────────────────────────────

MANAGE_HTML = base_template("Gérer", "manage", f"""
{CONTENT_MACRO}

<h2 style="font-size:1.2rem;margin-bottom:16px;">🗂️ Gérer les cartes</h2>

{{% if boxes %}}
<p class="section-title">Boîtes</p>
<div class="box-grid">
    {{% for box in boxes %}}
    <a href="/manage?box={{{{ box }}}}" class="box-item {{% if selected_box == box %}}active{{% endif %}}">
        <span class="box-num">{{{{ box }}}}</span>
        <span class="box-count">n°{{{{ box }}}}</span>
    </a>
    {{% endfor %}}
</div>
{{% else %}}
<div class="empty-state">
    <div class="icon">📭</div>
    <p>Aucune carte. Créez-en une !</p>
</div>
{{% endif %}}

{{% if selected_box is not none %}}
<p class="section-title">Boîte {{{{ selected_box }}}} — {{{{ cards|length }}}} cartes</p>
{{% for card in cards %}}
<a href="/card/{{{{ card.id }}}}" class="card-list-item">
    {{% if card.marked %}}<span class="marked-icon">🔖</span>{{% endif %}}
    {{% if card.recto_path and card.recto_path.startswith('http') %}}
        <img src="{{{{ card.recto_path }}}}" class="thumb" loading="lazy">
    {{% elif card.recto_path %}}
        <img src="/{{{{ card.recto_path }}}}" class="thumb" loading="lazy">
    {{% endif %}}
    <span class="preview">{{{{ card.recto_text or '🖼️ Image' }}}}</span>
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
</a>
{{% endfor %}}
{{% endif %}}
""")

# ── Card detail ──────────────────────────────────────────────────────────────

CARD_DETAIL_HTML = base_template("Détails", "manage", f"""
{CONTENT_MACRO}

<a href="/manage?box={{{{ card.box }}}}" style="font-size:0.85rem;color:var(--text2);">← Boîte {{{{ card.box }}}}</a>

<div style="margin-top:16px;">
    <div class="meta-row">
        <span class="badge badge-accent">Boîte {{{{ card.box }}}}</span>
        <span class="badge {{% if card.marked %}}badge-warning{{% else %}}badge-green{{% endif %}}">
            {{% if card.marked %}}🔖 Marquée{{% else %}}Non marquée{{% endif %}}
        </span>
    </div>

    <div style="font-size:0.8rem;color:var(--text2);margin:8px 0 16px;">
        Créée le {{{{ card.creation_date }}}} · Révisée le {{{{ card.last_reviewed_date or 'jamais' }}}} · Prochaine le {{{{ card.next_review_date }}}}
    </div>

    <div class="detail-face">
        <h4>Recto</h4>
        {{{{ render_content(card.recto_path, card.recto_text, card.recto_audio) }}}}
    </div>
    <div class="detail-face">
        <h4>Verso</h4>
        {{{{ render_content(card.verso_path, card.verso_text) }}}}
        {{{{ render_content(card.verso_path, card.verso_text, card.verso_audio) }}}}

    <div class="btn-row">
        <a href="/card/{{{{ card.id }}}}/edit" class="btn btn-ghost btn-sm">✏️ Modifier</a>
        <a href="/card/{{{{ card.id }}}}/toggle_mark" class="btn btn-ghost btn-sm">
            {{% if card.marked %}}🔖 Démarquer{{% else %}}🔖 Marquer{{% endif %}}
        </a>
        <button class="btn btn-ghost btn-sm" onclick="showConfirm()" style="color:var(--danger)">🗑️ Supprimer</button>
    </div>
</div>

<div class="confirm-overlay" id="confirmDelete">
    <div class="confirm-box">
        <p>Supprimer cette carte ?</p>
        <div class="btn-row-2">
            <a href="/card/{{{{ card.id }}}}/delete" class="btn btn-danger btn-sm">Supprimer</a>
            <button class="btn btn-ghost btn-sm" onclick="hideConfirm()">Annuler</button>
        </div>
    </div>
</div>
<script>
function showConfirm() {{ document.getElementById('confirmDelete').classList.add('show'); }}
function hideConfirm() {{ document.getElementById('confirmDelete').classList.remove('show'); }}
</script>
""")

# ── Edit card ────────────────────────────────────────────────────────────────

EDIT_HTML = base_template("Modifier", "manage", f"""
{CONTENT_MACRO}

<h2 style="font-size:1.2rem;margin-bottom:16px;">✏️ Modifier la carte</h2>

<div class="detail-face">
    <h4>Recto actuel</h4>
    {{{{ render_content(card.recto_path, card.recto_text, card.recto_audio) }}}}
</div>
<div class="detail-face">
    <h4>Verso actuel</h4>
    {{{{ render_content(card.verso_path, card.verso_text, card.verso_audio) }}}}
</div>

<form method="POST" enctype="multipart/form-data">
    {{% if from_review %}}<input type="hidden" name="from_review" value="1">{{% endif %}}

    <div class="form-group">
        <label>Boîte</label>
        <input type="number" name="box" value="{{{{ card.box }}}}" min="1" max="60">
    </div>

    <p class="section-title">Recto</p>
    <div class="form-group">
        <label>Texte</label>
        <textarea name="recto_text">{{{{ card.recto_text or '' }}}}</textarea>
    </div>
    <div class="form-group">
        <label>URL image</label>
        <input type="text" name="recto_url" value="{{{{ card.recto_path if card.recto_path and card.recto_path.startswith('http') else '' }}}}">
    </div>
    <div class="form-group">
        <label>Upload image</label>
        <input type="file" name="recto_upload" accept="image/*">
    </div>
    <div class="form-group">
        <label>🎵 Audio — {{% if card.recto_audio %}}fichier actuel : {{{{ card.recto_audio }}}}{{% else %}}aucun{{% endif %}}</label>
        <input type="file" name="recto_audio_upload" accept="audio/*">
    </div>

    <p class="section-title">Verso</p>
    <div class="form-group">
        <label>Texte</label>
        <textarea name="verso_text">{{{{ card.verso_text or '' }}}}</textarea>
    </div>
    <div class="form-group">
        <label>URL image</label>
        <input type="text" name="verso_url" value="{{{{ card.verso_path if card.verso_path and card.verso_path.startswith('http') else '' }}}}">
    </div>
    <div class="form-group">
        <label>Upload image</label>
        <input type="file" name="verso_upload" accept="image/*">
    </div>
    <div class="form-group">
        <label>🎵 Audio — {{% if card.verso_audio %}}fichier actuel : {{{{ card.verso_audio }}}}{{% else %}}aucun{{% endif %}}</label>
        <input type="file" name="verso_audio_upload" accept="audio/*">
    </div>

    <button type="submit" class="btn btn-primary" style="margin-bottom:12px;">Sauvegarder</button>
    <a href="{{% if from_review %}}/review{{% else %}}/card/{{{{ card.id }}}}{{% endif %}}" class="btn btn-ghost">Annuler</a>
</form>
""")

# ── Create card ──────────────────────────────────────────────────────────────

CREATE_HTML = base_template("Créer", "create", """
<h2 style="font-size:1.2rem;margin-bottom:16px;">➕ Nouvelle carte</h2>

<form method="POST" enctype="multipart/form-data">
    <p class="section-title">Recto</p>
    <div class="form-group">
        <label>Texte</label>
        <input type="text" name="recto_text" placeholder="Question ou mot...">
    </div>
    <div class="form-group">
        <label>URL image</label>
        <input type="text" name="recto_url" placeholder="https://...">
    </div>
    <div class="form-group">
        <label>Upload image</label>
        <input type="file" name="recto_upload" accept="image/*">
    </div>
    <div class="form-group">
        <label>🎵 Audio (mp3, wav, ogg…)</label>
        <input type="file" name="recto_audio_upload" accept="audio/*">
    </div>

    <p class="section-title">Verso</p>
    <div class="form-group">
        <label>Texte</label>
        <input type="text" name="verso_text" placeholder="Réponse...">
    </div>
    <div class="form-group">
        <label>URL image</label>
        <input type="text" name="verso_url" placeholder="https://...">
    </div>
    <div class="form-group">
        <label>Upload image</label>
        <input type="file" name="verso_upload" accept="image/*">
    </div>
    <div class="form-group">
        <label>🎵 Audio (mp3, wav, ogg…)</label>
        <input type="file" name="verso_audio_upload" accept="audio/*">
    </div>

    <button type="submit" class="btn btn-primary">Ajouter la carte</button>
</form>
""")

# ── Dashboard ────────────────────────────────────────────────────────────────

DASHBOARD_HTML = base_template("Dashboard", "dashboard", """
<h2 style="font-size:1.2rem;margin-bottom:16px;">📊 Tableau de bord</h2>

{% if total == 0 %}
<div class="empty-state">
    <div class="icon">📭</div>
    <p>Aucune carte pour les statistiques.</p>
</div>
{% else %}

<div class="stats-grid">
    <div class="stat-card">
        <div class="stat-value">{{ "%.1f"|format(mastery) }}%</div>
        <div class="stat-label">Maîtrise</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{{ "%.1f"|format(long_term_ratio) }}%</div>
        <div class="stat-label">Long terme</div>
    </div>
    <div class="stat-card">
        <div class="stat-value">{{ total }}</div>
        <div class="stat-label">Cartes</div>
    </div>
</div>

<div class="chart-card">
    <h3>Cartes par boîte</h3>
    <canvas id="boxChart" height="200"></canvas>
</div>

<div class="chart-card">
    <h3>Croissance du savoir</h3>
    <canvas id="timelineChart" height="200"></canvas>
</div>

<div class="chart-card">
    <h3>Calendrier de création — 12 derniers mois</h3>
    <div id="heatmapWrap" style="overflow-x:auto;padding-bottom:4px;">
        <canvas id="heatmapChart"></canvas>
    </div>
</div>

<div class="chart-card">
    <h3>Charge cognitive future</h3>
    <canvas id="workloadChart" height="200"></canvas>
</div>

<div class="chart-card">
    <h3>Activité de révision — 30 derniers jours</h3>
    <canvas id="activityChart" height="200"></canvas>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
    <div class="chart-card" style="margin-bottom:0">
        <h3>Stades d'apprentissage</h3>
        <canvas id="stageChart" height="220"></canvas>
    </div>
    <div class="chart-card" style="margin-bottom:0">
        <h3>Santé des cartes</h3>
        <canvas id="healthChart" height="220"></canvas>
    </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
const colors = { accent: '#7f5af0', accent2: '#2cb67d', border: '#2a2a32', text2: '#94929d', surface2: '#1e1e24', danger: '#e53170', warning: '#fbbf24' };
const defaults = { responsive: true, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: colors.text2, maxTicksLimit: 8 }, grid: { color: colors.border } }, y: { ticks: { color: colors.text2 }, grid: { color: colors.border } } } };

// Box chart
const boxData = {{ box_data | tojson }};
new Chart(document.getElementById('boxChart'), {
    type: 'bar',
    data: { labels: boxData.map(d => d[0]), datasets: [{ data: boxData.map(d => d[1]), backgroundColor: colors.accent + '88', borderColor: colors.accent, borderWidth: 1, borderRadius: 4 }] },
    options: defaults
});

// Timeline chart
const tlData = {{ timeline_data | tojson }};
new Chart(document.getElementById('timelineChart'), {
    type: 'line',
    data: { labels: tlData.map(d => d.date), datasets: [{ data: tlData.map(d => d.count), borderColor: colors.accent2, backgroundColor: colors.accent2 + '15', fill: true, tension: 0.3, pointRadius: 0 }] },
    options: defaults
});

// ── NEW: Creation heatmap ───────────────────────────────────────────────────
(function() {
    const hmRaw = {{ creation_heatmap | tojson }};
    if (!hmRaw.length) return;

    const COLS = 53, ROWS = 7, CELL = 13, GAP = 3;
    const PAD_LEFT = 28, PAD_TOP = 22, PAD_BOTTOM = 20;
    const W = PAD_LEFT + COLS * (CELL + GAP);
    const H = PAD_TOP + ROWS * (CELL + GAP) + PAD_BOTTOM;

    const canvas = document.getElementById('heatmapChart');
    canvas.width  = W;
    canvas.height = H;
    canvas.style.width  = W + 'px';
    canvas.style.height = H + 'px';
    const ctx = canvas.getContext('2d');

    const maxCount = Math.max(...hmRaw.map(d => d.count), 1);
    const logMax = Math.log1p(maxCount); // log(1 + max) to handle 0 safely
    const dataMap = {};
    hmRaw.forEach(d => dataMap[d.date] = d.count);

    // Build weeks: first cell = hmRaw[0].date (a Monday-aligned start)
    const startDate = new Date(hmRaw[0].date + 'T00:00:00');
    // Align to Monday
    const dow = startDate.getDay(); // 0=Sun
    const offset = (dow === 0 ? 6 : dow - 1);
    startDate.setDate(startDate.getDate() - offset);

    const MONTH_NAMES = ['Jan','Fév','Mar','Avr','Mai','Juin','Juil','Aoû','Sep','Oct','Nov','Déc'];
    const DAY_NAMES   = ['L','M','M','J','V','S','D'];

    // Draw day labels
    ctx.fillStyle = '#94929d';
    ctx.font = '10px DM Sans, sans-serif';
    ctx.textAlign = 'right';
    for (let r = 0; r < ROWS; r++) {
        if (r % 2 === 0) {
            const y = PAD_TOP + r * (CELL + GAP) + CELL - 2;
            ctx.fillText(DAY_NAMES[r], PAD_LEFT - 4, y);
        }
    }

    // Draw cells
    let prevMonth = -1;
    for (let col = 0; col < COLS; col++) {
        for (let row = 0; row < ROWS; row++) {
            const d = new Date(startDate);
            d.setDate(startDate.getDate() + col * 7 + row);
            const ds = d.toISOString().slice(0, 10);
            const count = dataMap[ds] || 0;
            const x = PAD_LEFT + col * (CELL + GAP);
            const y = PAD_TOP  + row * (CELL + GAP);

            // Month label at top of first row of each new month
            if (row === 0) {
                const m = d.getMonth();
                if (m !== prevMonth) {
                    ctx.fillStyle = '#94929d';
                    ctx.font = '10px DM Sans, sans-serif';
                    ctx.textAlign = 'left';
                    ctx.fillText(MONTH_NAMES[m], x, PAD_TOP - 6);
                    prevMonth = m;
                }
            }

            // Cell color (log scale to avoid outlier domination)
            const ratio = count === 0 ? 0 : Math.log1p(count) / logMax;
            let fill;
            if (count === 0) {
                fill = '#1e1e24';
            } else if (ratio < 0.25) {
                fill = '#2cb67d33';
            } else if (ratio < 0.5) {
                fill = '#2cb67d77';
            } else if (ratio < 0.75) {
                fill = '#2cb67dbb';
            } else {
                fill = '#2cb67d';
            }
            ctx.fillStyle = fill;
            ctx.beginPath();
            ctx.roundRect(x, y, CELL, CELL, 3);
            ctx.fill();

            // Tooltip stored as dataset on canvas (handled via mousemove)
        }
    }

    // Tooltip on hover
    const tooltip = document.createElement('div');
    tooltip.style.cssText = 'position:fixed;background:#16161a;border:1px solid #2a2a32;color:#e8e6e3;font-size:11px;padding:5px 9px;border-radius:7px;pointer-events:none;display:none;z-index:999;font-family:DM Sans,sans-serif;';
    document.body.appendChild(tooltip);

    canvas.addEventListener('mousemove', function(e) {
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const col = Math.floor((mx - PAD_LEFT) / (CELL + GAP));
        const row = Math.floor((my - PAD_TOP)  / (CELL + GAP));
        if (col >= 0 && col < COLS && row >= 0 && row < ROWS) {
            const d = new Date(startDate);
            d.setDate(startDate.getDate() + col * 7 + row);
            const ds = d.toISOString().slice(0, 10);
            const count = dataMap[ds] || 0;
            tooltip.style.display = 'block';
            tooltip.style.left = (e.clientX + 12) + 'px';
            tooltip.style.top  = (e.clientY - 28) + 'px';
            tooltip.innerHTML = `<strong>${count} carte${count !== 1 ? 's' : ''}</strong> — ${ds}`;
        } else {
            tooltip.style.display = 'none';
        }
    });
    canvas.addEventListener('mouseleave', () => tooltip.style.display = 'none');

    // Legend
    ctx.fillStyle = '#94929d';
    ctx.font = '10px DM Sans, sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText('Moins', PAD_LEFT, H - 4);
    const legendX = PAD_LEFT + 36;
    ['#1e1e24','#2cb67d33','#2cb67d77','#2cb67dbb','#2cb67d'].forEach((c, i) => {
        ctx.fillStyle = c;
        ctx.beginPath();
        ctx.roundRect(legendX + i * (CELL + 3), H - PAD_BOTTOM + 4, CELL, CELL, 3);
        ctx.fill();
    });
    ctx.fillStyle = '#94929d';
    ctx.fillText('Plus', legendX + 5 * (CELL + 3) + 2, H - 4);
})();

// Workload chart
const wlData = {{ workload_data | tojson }};
new Chart(document.getElementById('workloadChart'), {
    type: 'bar',
    data: { labels: wlData.map(d => d.date), datasets: [{ data: wlData.map(d => d.count), backgroundColor: colors.accent + '66', borderColor: colors.accent, borderWidth: 1, borderRadius: 4 }] },
    options: defaults
});

// ── NEW: Activity chart (last 30 days) ─────────────────────────────────────
const actData = {{ activity_data | tojson }};
const actMax = Math.max(...actData.map(d => d.count), 1);
new Chart(document.getElementById('activityChart'), {
    type: 'bar',
    data: {
        labels: actData.map(d => d.date.slice(5)),  // MM-DD
        datasets: [{
            data: actData.map(d => d.count),
            backgroundColor: actData.map(d => {
                const ratio = d.count / actMax;
                return `rgba(44,182,125,${0.15 + ratio * 0.75})`;
            }),
            borderColor: colors.accent2,
            borderWidth: d => d.raw > 0 ? 1 : 0,
            borderRadius: 3,
        }]
    },
    options: {
        ...defaults,
        scales: {
            x: { ticks: { color: colors.text2, maxTicksLimit: 10 }, grid: { color: colors.border } },
            y: { ticks: { color: colors.text2, stepSize: 1 }, grid: { color: colors.border }, beginAtZero: true }
        }
    }
});

// ── NEW: Stage donut chart ──────────────────────────────────────────────────
const stageRaw = {{ stage_data | tojson }};
new Chart(document.getElementById('stageChart'), {
    type: 'doughnut',
    data: {
        labels: Object.keys(stageRaw),
        datasets: [{
            data: Object.values(stageRaw),
            backgroundColor: ['#e53170cc', '#fbbf24cc', colors.accent + 'cc', colors.accent2 + 'cc'],
            borderColor:     ['#e53170',   '#fbbf24',   colors.accent,         colors.accent2],
            borderWidth: 2,
            hoverOffset: 6,
        }]
    },
    options: {
        responsive: true,
        cutout: '65%',
        plugins: {
            legend: {
                display: true,
                position: 'bottom',
                labels: { color: colors.text2, font: { size: 11 }, boxWidth: 12, padding: 10 }
            }
        }
    }
});

// ── NEW: Health horizontal bar chart ───────────────────────────────────────
const healthRaw = {{ health_data | tojson }};
new Chart(document.getElementById('healthChart'), {
    type: 'bar',
    data: {
        labels: Object.keys(healthRaw),
        datasets: [{
            data: Object.values(healthRaw),
            backgroundColor: [colors.danger + 'aa', colors.warning + 'aa', colors.accent2 + 'aa', colors.text2 + '66'],
            borderColor:     [colors.danger,         colors.warning,         colors.accent2,         colors.text2],
            borderWidth: 1,
            borderRadius: 4,
        }]
    },
    options: {
        indexAxis: 'y',
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
            x: { ticks: { color: colors.text2 }, grid: { color: colors.border }, beginAtZero: true },
            y: { ticks: { color: colors.text2 }, grid: { display: false } }
        }
    }
});
</script>
{% endif %}
""")


# ── Mindfulness template ─────────────────────────────────────────────────────

MINDFULNESS_HTML = base_template("Zen", "zen", """
<style>
/* ── Zen-specific overrides ── */
.zen-hero {
    text-align: center;
    padding: 32px 0 24px;
}
.zen-hero .eyebrow {
    font-size: 0.7rem;
    letter-spacing: 0.3em;
    text-transform: uppercase;
    color: var(--accent2);
    margin-bottom: 10px;
    font-weight: 500;
}
.zen-hero h2 {
    font-size: 2rem;
    font-weight: 300;
    letter-spacing: -0.5px;
    margin-bottom: 8px;
}
.zen-hero p {
    font-size: 0.9rem;
    color: var(--text2);
    line-height: 1.6;
}

/* Breath widget */
.breath-widget {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 28px 20px;
    text-align: center;
    margin-bottom: 16px;
    position: relative;
    overflow: hidden;
}
.breath-widget::before {
    content: '';
    position: absolute; inset: 0;
    background: radial-gradient(ellipse at 50% 0%, rgba(44,182,125,0.08) 0%, transparent 65%);
    pointer-events: none;
}
.breath-widget-label {
    font-size: 0.7rem;
    letter-spacing: 0.25em;
    text-transform: uppercase;
    color: var(--text2);
    margin-bottom: 24px;
    font-weight: 500;
}
.breath-ring-wrap {
    position: relative; width: 140px; height: 140px;
    margin: 0 auto 20px;
}
.b-ring {
    position: absolute; inset: 0;
    border-radius: 50%;
    border: 1px solid rgba(44,182,125,0.25);
    animation: bpulse 4s ease-in-out infinite;
}
.b-ring:nth-child(2) { inset: -14px; animation-delay:.5s; opacity:.5; }
.b-ring:nth-child(3) { inset: -28px; animation-delay:1s; opacity:.2; }
.b-circle {
    position: absolute; inset: 10px;
    border-radius: 50%;
    background: radial-gradient(circle at 38% 38%, #2cb67d, #1a7a52);
    display: flex; align-items: center; justify-content: center;
    cursor: pointer;
    box-shadow: 0 0 32px rgba(44,182,125,0.3);
    transition: transform 0.2s;
}
.b-circle:hover { transform: scale(1.04); }
.b-circle-text {
    font-size: 0.75rem;
    font-weight: 600;
    color: #e8ece4;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    user-select: none;
}
.b-phase {
    font-size: 1.2rem;
    font-weight: 300;
    color: var(--text);
    margin-bottom: 4px;
    min-height: 28px;
}
.b-count {
    font-family: 'Space Mono', monospace;
    font-size: 0.85rem;
    color: var(--text2);
    min-height: 20px;
}
@keyframes bpulse {
    0%,100% { transform:scale(1); opacity:.4; }
    50% { transform:scale(1.07); opacity:1; }
}
@keyframes bIn  { from{transform:scale(1)} to{transform:scale(1.3)} }
@keyframes bOut { from{transform:scale(1.3)} to{transform:scale(1)} }

/* Practice cards */
.zen-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px;
    margin-bottom: 12px;
    cursor: pointer;
    transition: all .2s;
    position: relative;
    overflow: hidden;
}
.zen-card::after {
    content: '';
    position: absolute;
    bottom: 0; left: 0; right: 0; height: 2px;
    background: var(--zc-accent, var(--accent2));
    transform: scaleX(0);
    transition: transform .3s;
    transform-origin: left;
}
.zen-card:hover { border-color: var(--zc-accent, var(--accent2)); }
.zen-card:hover::after, .zen-card.open::after { transform: scaleX(1); }
.zen-card.open { border-color: var(--zc-accent, var(--accent2)); background: var(--surface2); }

.zen-card-head {
    display: flex; align-items: center; gap: 14px;
}
.zen-card-icon { font-size: 1.5rem; flex-shrink: 0; }
.zen-card-title { font-size: 1rem; font-weight: 600; color: var(--text); }
.zen-card-desc { font-size: 0.82rem; color: var(--text2); margin-top: 2px; line-height: 1.5; }
.zen-card-meta {
    margin-left: auto;
    display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex-shrink: 0;
}
.zen-card-dur {
    font-family: 'Space Mono', monospace;
    font-size: 0.65rem;
    color: var(--zc-accent, var(--accent2));
}
.zen-chevron {
    font-size: 0.75rem; color: var(--text2);
    transition: transform .3s;
}
.zen-card.open .zen-chevron { transform: rotate(180deg); }

/* Steps panel */
.zen-steps {
    max-height: 0;
    overflow: hidden;
    transition: max-height .5s ease;
}
.zen-steps.open { max-height: 600px; }
.zen-steps-inner {
    padding-top: 20px;
}
.zen-step {
    display: flex; gap: 12px; margin-bottom: 14px; align-items: flex-start;
}
.zen-step-num {
    width: 24px; height: 24px;
    border-radius: 50%;
    background: rgba(44,182,125,0.12);
    color: var(--zc-accent, var(--accent2));
    font-size: 0.7rem; font-weight: 700;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0; margin-top: 2px;
}
.zen-step-text {
    font-size: 0.88rem; color: var(--text2);
    line-height: 1.65;
}
.zen-tip {
    margin-top: 12px;
    padding: 12px 14px;
    background: rgba(44,182,125,0.06);
    border-left: 2px solid var(--zc-accent, var(--accent2));
    border-radius: 0 8px 8px 0;
    font-size: 0.82rem; color: var(--text2);
    line-height: 1.6; font-style: italic;
}

/* Checklist */
.zen-checklist {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 20px;
    margin-bottom: 16px;
}
.zen-checklist-title {
    font-size: 0.8rem; font-weight: 600;
    text-transform: uppercase; letter-spacing: 1px;
    color: var(--text2); margin-bottom: 16px;
    display: flex; align-items: center; gap: 8px;
}
.ck-item {
    display: flex; align-items: center; gap: 12px;
    padding: 10px 12px;
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: background .2s;
    user-select: none;
}
.ck-item:hover { background: var(--surface2); }
.ck-item.checked { opacity: 0.5; }
.ck-box {
    width: 20px; height: 20px;
    border-radius: 5px;
    border: 1.5px solid var(--border);
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
    transition: all .2s;
    font-size: 0.7rem; color: #fff;
}
.ck-item.checked .ck-box { background: var(--accent2); border-color: var(--accent2); }
.ck-label { font-size: 0.88rem; color: var(--text); }
.ck-item.checked .ck-label { text-decoration: line-through; color: var(--text2); }

/* Quote block */
.zen-quote {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 28px 24px;
    text-align: center;
    margin-bottom: 80px;
}
.zen-quote-mark { font-size: 3rem; line-height: 1; color: var(--accent); opacity: 0.3; margin-bottom: 8px; }
.zen-quote-text {
    font-size: 1.05rem; font-weight: 300;
    font-style: italic; color: var(--text);
    line-height: 1.6; margin-bottom: 12px;
}
.zen-quote-author {
    font-size: 0.72rem; letter-spacing: 0.25em;
    text-transform: uppercase; color: var(--accent2);
    font-weight: 600;
}
</style>

<div class="zen-hero">
    <p class="eyebrow">Espace de calme</p>
    <h2>Pleine Conscience</h2>
    <p>Ancrez-vous dans le moment présent,<br>une respiration à la fois.</p>
</div>

<!-- ── BREATHING ── -->
<div class="breath-widget">
    <p class="breath-widget-label">Respiration 4 – 7 – 8</p>
    <div class="breath-ring-wrap">
        <div class="b-ring"></div>
        <div class="b-ring"></div>
        <div class="b-ring"></div>
        <div class="b-circle" id="bCircle" onclick="toggleBreath()">
            <span class="b-circle-text" id="bStart">Démarrer</span>
        </div>
    </div>
    <div class="b-phase" id="bPhase"></div>
    <div class="b-count" id="bCount"></div>
    <button class="btn btn-ghost btn-sm" style="margin-top:16px;width:auto;padding:10px 28px;" onclick="toggleBreath()" id="bBtn">▶ &nbsp;Commencer</button>
</div>

<!-- ── PRACTICES ── -->
<p class="section-title">Pratiques guidées</p>
<div id="zenCards"></div>

<!-- ── DAILY CHECKLIST ── -->
<div class="zen-checklist">
    <div class="zen-checklist-title">
        <span>✦</span> Routine du jour
    </div>
    <div id="ckGrid"></div>
    <div class="progress-wrap" style="margin-top:16px;">
        <div class="progress-bar" id="ckBar" style="width:0%"></div>
    </div>
    <p class="progress-label" id="ckLabel">0 / 10</p>
</div>

<!-- ── QUOTE ── -->
<div class="zen-quote">
    <div class="zen-quote-mark">"</div>
    <p class="zen-quote-text" id="qText">Le passé est révolu, l'avenir n'est pas encore là. Il n'y a qu'un seul moment où l'on peut vivre : le moment présent.</p>
    <p class="zen-quote-author" id="qAuthor">— Thich Nhat Hanh</p>
    <button class="btn btn-ghost btn-sm" style="margin-top:20px;width:auto;padding:10px 24px;" onclick="nextQuote()">Nouvelle citation</button>
</div>

<script>
// ─── Data ──────────────────────────────────────────────────────────────────
const ZEN_PRACTICES = [
    { icon:"🍃", title:"Scan corporel", desc:"Relâchez les tensions en parcourant votre corps avec attention.", dur:"5–20 min", accent:"#2cb67d",
      steps:["Allongez-vous ou asseyez-vous confortablement. Fermez les yeux.",
             "Portez attention aux orteils — chaleur, picotements, pression.",
             "Remontez lentement : pieds, chevilles, mollets, genoux, cuisses.",
             "Continuez vers le ventre, la poitrine, les bras, les mains, les doigts.",
             "Terminez par le cou, le visage, le sommet du crâne.",
             "Respirez profondément, sentez votre corps entier."],
      tip:"Si l'esprit vagabonde, revenez sans jugement à l'endroit où vous étiez — c'est l'essence même de la pratique." },
    { icon:"🌬️", title:"Respiration consciente", desc:"L'ancrage le plus immédiat : observez simplement votre souffle.", dur:"2–10 min", accent:"#7f5af0",
      steps:["Asseyez-vous avec le dos droit, mains sur les cuisses.",
             "Fermez les yeux ou fixez un point devant vous.",
             "Observez l'air entrer par les narines — fraîcheur, texture.",
             "Suivez le souffle jusqu'au ventre. Notez la pause entre chaque cycle.",
             "À chaque distraction, nommez-la doucement puis revenez au souffle.",
             "Prenez 3 grandes respirations avant de rouvrir les yeux."],
      tip:"Vous ne faites pas de 'mauvaise' méditation. Chaque retour au souffle est une victoire de conscience." },
    { icon:"🚶", title:"Marche méditative", desc:"Transformez un trajet ordinaire en présence totale.", dur:"10–30 min", accent:"#fbbf24",
      steps:["Choisissez un espace calme : jardin, couloir, ou chambre.",
             "Marchez 2× plus lentement que d'habitude.",
             "Portez attention à chaque pied se levant, avançant, se posant.",
             "Synchronisez le souffle avec les pas (ex. 2 pas = inspiration).",
             "Engagez les sens : sons, textures, lumières.",
             "À la fin, immobilisez-vous. Ressentez le contraste."],
      tip:"La destination n'a aucune importance. Chaque pas est la destination." },
    { icon:"🫀", title:"Bienveillance aimante", desc:"Cultivez la compassion envers vous-même et les autres.", dur:"10–15 min", accent:"#e53170",
      steps:["Fermez les yeux. Posez les mains sur votre cœur.",
             "Visualisez quelqu'un que vous aimez facilement.",
             "Répétez mentalement : 'Que tu sois heureux·se. Que tu sois en paix.'",
             "Élargissez à vous-même : 'Que je sois heureux·se. Que je sois en paix.'",
             "Puis à des connaissances, des inconnus, et tous les êtres.",
             "Terminez en ressentant la chaleur dans la poitrine."],
      tip:"Il est souvent plus difficile d'envoyer de la bienveillance à soi-même — c'est là que la pratique est la plus précieuse." },
    { icon:"✍️", title:"Journaling libre", desc:"Observez vos pensées par écrit, sans filtre ni jugement.", dur:"5–15 min", accent:"#2cb67d",
      steps:["Prenez un carnet et un stylo. Pas d'écran.",
             "Écrivez la date et une sensation physique du moment.",
             "Pendant 5 minutes, écrivez sans arrêter — tout ce qui traverse l'esprit.",
             "Pas de correction, pas de relecture. Le stylo ne s'arrête pas.",
             "Relisez avec curiosité, non avec jugement.",
             "Cerclz un mot qui résonne. Méditez dessus 2 minutes."],
      tip:"Ce n'est pas un journal classique — c'est un filet pour attraper les pensées fugaces et les observer à distance." },
    { icon:"🌿", title:"Technique 5-4-3-2-1", desc:"Revenez instantanément au présent via vos cinq sens.", dur:"2–5 min", accent:"#7f5af0",
      steps:["Regardez et nommez mentalement 5 choses que vous voyez.",
             "Posez la main sur 4 surfaces différentes. Percevez les textures.",
             "Écoutez et identifiez 3 sons distincts autour de vous.",
             "Sentez 2 odeurs — proches ou lointaines.",
             "Notez 1 goût dans votre bouche en ce moment.",
             "Prenez 3 respirations lentes. Observez le calme."],
      tip:"Particulièrement efficace lors d'anxiété intense — elle interrompt la spirale mentale en ramenant aux sensations réelles." },
];

const ZEN_CHECKLIST = [
    "Méditation matinale (5 min)",
    "3 respirations avant chaque repas",
    "Marche sans téléphone (10 min)",
    "Pause sensorielle 5-4-3-2-1",
    "Écrire 3 gratitudes",
    "Respiration 4-7-8 le soir",
    "Manger en pleine conscience",
    "Scan corporel au coucher",
    "Bienveillance aimante (5 min)",
    "Journaling libre (5 min)",
];

const ZEN_QUOTES = [
    { text:"Le passé est révolu, l'avenir n'est pas encore là. Il n'y a qu'un seul moment où l'on peut vivre : le moment présent.", author:"Thich Nhat Hanh" },
    { text:"La pleine conscience n'est pas difficile. Ce qui est difficile, c'est de se souvenir d'être attentif.", author:"Sharon Salzberg" },
    { text:"Respirer, c'est la seule chose dont vous avez besoin pour commencer à méditer.", author:"Jon Kabat-Zinn" },
    { text:"Entre le stimulus et la réponse, il y a un espace. Dans cet espace résident notre liberté et notre pouvoir de choisir.", author:"Viktor Frankl" },
    { text:"Là où tu es, sois entièrement là.", author:"Eckhart Tolle" },
];

// ─── Render practices ──────────────────────────────────────────────────────
let openCard = -1;
function renderPractices() {
    const el = document.getElementById('zenCards');
    el.innerHTML = ZEN_PRACTICES.map((p, i) => `
        <div class="zen-card" id="zc${i}" style="--zc-accent:${p.accent}" onclick="toggleCard(${i})">
            <div class="zen-card-head">
                <span class="zen-card-icon">${p.icon}</span>
                <div>
                    <div class="zen-card-title">${p.title}</div>
                    <div class="zen-card-desc">${p.desc}</div>
                </div>
                <div class="zen-card-meta">
                    <span class="zen-card-dur">${p.dur}</span>
                    <span class="zen-chevron">▾</span>
                </div>
            </div>
            <div class="zen-steps" id="zs${i}">
                <div class="zen-steps-inner">
                    <ol style="list-style:none;">
                        ${p.steps.map((s,j) => `<li class="zen-step"><div class="zen-step-num" style="background:${p.accent}18;color:${p.accent}">${j+1}</div><div class="zen-step-text">${s}</div></li>`).join('')}
                    </ol>
                    <div class="zen-tip">💡 ${p.tip}</div>
                </div>
            </div>
        </div>
    `).join('');
}
function toggleCard(i) {
    if (openCard === i) {
        document.getElementById(`zc${i}`).classList.remove('open');
        document.getElementById(`zs${i}`).classList.remove('open');
        openCard = -1;
    } else {
        if (openCard >= 0) {
            document.getElementById(`zc${openCard}`).classList.remove('open');
            document.getElementById(`zs${openCard}`).classList.remove('open');
        }
        document.getElementById(`zc${i}`).classList.add('open');
        document.getElementById(`zs${i}`).classList.add('open');
        openCard = i;
    }
}

// ─── Checklist ─────────────────────────────────────────────────────────────
let ckState = new Array(ZEN_CHECKLIST.length).fill(false);
function renderChecklist() {
    const el = document.getElementById('ckGrid');
    el.innerHTML = ZEN_CHECKLIST.map((item, i) => `
        <div class="ck-item ${ckState[i]?'checked':''}" onclick="toggleCk(${i})">
            <div class="ck-box">${ckState[i]?'✓':''}</div>
            <div class="ck-label">${item}</div>
        </div>
    `).join('');
    const done = ckState.filter(Boolean).length;
    document.getElementById('ckBar').style.width = (done/ZEN_CHECKLIST.length*100)+'%';
    document.getElementById('ckLabel').textContent = `${done} / ${ZEN_CHECKLIST.length} complétées`;
}
function toggleCk(i) { ckState[i]=!ckState[i]; renderChecklist(); }

// ─── Quotes ────────────────────────────────────────────────────────────────
let qi = 0;
function nextQuote() {
    qi = (qi+1) % ZEN_QUOTES.length;
    const qt = document.getElementById('qText');
    const qa = document.getElementById('qAuthor');
    qt.style.opacity='0'; qa.style.opacity='0';
    setTimeout(()=>{
        qt.textContent = ZEN_QUOTES[qi].text;
        qa.textContent = '— '+ZEN_QUOTES[qi].author;
        qt.style.transition='opacity .4s'; qa.style.transition='opacity .4s';
        qt.style.opacity='1'; qa.style.opacity='1';
    }, 280);
}

// ─── Breathing ─────────────────────────────────────────────────────────────
let bRunning=false, bTimer=null;
function toggleBreath() { bRunning ? stopBreath() : startBreath(); }
function startBreath() {
    bRunning=true;
    document.getElementById('bBtn').textContent='■  Arrêter';
    document.getElementById('bStart').style.display='none';
    runPhase('Inspirez',4,()=>runPhase('Retenez',7,()=>runPhase('Expirez',8,()=>{ if(bRunning) startBreath(); })));
}
function runPhase(name, secs, cb) {
    if(!bRunning) return;
    document.getElementById('bPhase').textContent=name;
    const c=document.getElementById('bCircle');
    if(name==='Inspirez') c.style.animation=`bIn ${secs}s ease forwards`;
    else if(name==='Expirez') c.style.animation=`bOut ${secs}s ease forwards`;
    else c.style.animation='none';
    let r=secs;
    document.getElementById('bCount').textContent=r+'s';
    bTimer=setInterval(()=>{
        r--;
        document.getElementById('bCount').textContent=r>0?r+'s':'';
        if(r<=0){ clearInterval(bTimer); if(bRunning) cb(); }
    },1000);
}
function stopBreath() {
    bRunning=false; clearInterval(bTimer);
    document.getElementById('bPhase').textContent='';
    document.getElementById('bCount').textContent='';
    document.getElementById('bBtn').textContent='▶  Commencer';
    document.getElementById('bStart').style.display='block';
    document.getElementById('bCircle').style.animation='';
}

// ─── Init ───────────────────────────────────────────────────────────────────
renderPractices();
renderChecklist();
</script>
""")

# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)