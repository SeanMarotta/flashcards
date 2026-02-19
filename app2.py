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
APP_PASSWORD = os.environ.get("APP_PASSWORD", "VOTRE_MOT_DE_PASSE_PAR_DEFAUT")

CARDS_FILE = "flashcards.json"
IMAGE_DIR = "images"
REVIEW_DIR = "review_sessions"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(REVIEW_DIR, exist_ok=True)

# ─── Server-side review session storage (avoids cookie size limits) ──────────

def _review_path():
    sid = session.get("_review_sid")
    if not sid:
        sid = str(uuid.uuid4())
        session["_review_sid"] = sid
    return os.path.join(REVIEW_DIR, f"{sid}.json")

def save_review_state(cards, index, show_answer):
    data = {"cards": cards, "index": index, "show_answer": show_answer}
    with open(_review_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

def load_review_state():
    p = _review_path()
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"cards": [], "index": 0, "show_answer": False}

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
    save_review_state(cards, 0, False)
    return redirect(url_for("review_card"))

@app.route("/review")
@login_required
def review_card():
    state = load_review_state()
    cards = state["cards"]
    idx = state["index"]
    if not cards or idx >= len(cards):
        clear_review_state()
        return render_template_string(REVIEW_DONE_HTML)
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
    return redirect(url_for("review_card"))

@app.route("/review/answer/<result>")
@login_required
def review_answer(result):
    state = load_review_state()
    cards = state["cards"]
    idx = state["index"]
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
    save_review_state(cards, idx + 1, False)
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

        # Verso
        verso_upload = request.files.get("verso_upload")
        verso_url = request.form.get("verso_url", "").strip()
        verso_text = request.form.get("verso_text", "").strip()
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

        recto_path = recto_text_val = verso_path = verso_text_val = None

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

        if (recto_path or recto_text_val) and (verso_path or verso_text_val):
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
                "verso_path": verso_path,
                "verso_text": verso_text_val,
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
        return render_template_string(DASHBOARD_HTML, total=0, mastery=0, long_term_ratio=0, box_data=[], timeline_data=[], workload_data=[])

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

    return render_template_string(
        DASHBOARD_HTML,
        total=total, mastery=mastery, long_term_ratio=long_term_ratio,
        box_data=box_data, timeline_data=cumulative, workload_data=workload
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
}

def base_template(title, active, content, body_class=""):
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="theme-color" content="#0c0c0f">
<title>{title}</title>
<style>{BASE_CSS}</style>
</head>
<body class="{body_class}">
<div class="topbar">
    <h1>⚡ Flashcards</h1>
    <div class="topbar-actions">
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
</nav>
</body>
</html>"""

# Jinja helper for rendering card content (text or image)
CONTENT_MACRO = """
{% macro render_content(path, text) %}
{% if path and path.startswith('http') %}
    <img src="{{ path }}" alt="card image" loading="lazy">
{% elif path %}
    <img src="/{{ path }}" alt="card image" loading="lazy">
{% elif text %}
    <div>{{ text }}</div>
{% else %}
    <span style="color:var(--text2)">—</span>
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
        {{{{ render_content(card.recto_path if (card.current_face|default('recto'))=='recto' else card.verso_path, card.recto_text if (card.current_face|default('recto'))=='recto' else card.verso_text) }}}}
    </div>

    {{% if show_answer %}}
    <div style="border-top:1px solid var(--border);padding-top:20px;margin-top:12px;">
        <div class="card-content" style="padding-top:8px;">
            {{{{ render_content(card.verso_path if (card.current_face|default('recto'))=='recto' else card.recto_path, card.verso_text if (card.current_face|default('recto'))=='recto' else card.recto_text) }}}}
        </div>
    </div>
    {{% endif %}}
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
<div class="review-action-bar">
    <div class="action-buttons">
        {{% if show_answer %}}
        <a href="/review/answer/correct" class="btn btn-success">✅ Correct</a>
        <a href="/review/answer/incorrect" class="btn btn-danger">❌ Faux</a>
        <a href="/review/answer/pass" class="btn btn-ghost">⏭️ Pass</a>
        {{% else %}}
        <a href="/review/show" class="btn btn-primary" style="grid-column:1/-1;">Voir la réponse</a>
        {{% endif %}}
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
</script>
""", body_class="review-mode")

# ── Review done ──────────────────────────────────────────────────────────────

REVIEW_DONE_HTML = base_template("Terminé !", "review", """
<div class="done-wrap">
    <div class="emoji">🎉</div>
    <h2>Session terminée !</h2>
    <p>Bravo, toutes les cartes ont été révisées.</p>
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
        {{{{ render_content(card.recto_path, card.recto_text) }}}}
    </div>
    <div class="detail-face">
        <h4>Verso</h4>
        {{{{ render_content(card.verso_path, card.verso_text) }}}}
    </div>

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
    {{{{ render_content(card.recto_path, card.recto_text) }}}}
</div>
<div class="detail-face">
    <h4>Verso actuel</h4>
    {{{{ render_content(card.verso_path, card.verso_text) }}}}
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
    <h3>Charge cognitive future</h3>
    <canvas id="workloadChart" height="200"></canvas>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
const colors = { accent: '#7f5af0', accent2: '#2cb67d', border: '#2a2a32', text2: '#94929d', surface2: '#1e1e24' };
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

// Workload chart
const wlData = {{ workload_data | tojson }};
new Chart(document.getElementById('workloadChart'), {
    type: 'bar',
    data: { labels: wlData.map(d => d.date), datasets: [{ data: wlData.map(d => d.count), backgroundColor: colors.accent + '66', borderColor: colors.accent, borderWidth: 1, borderRadius: 4 }] },
    options: defaults
});
</script>
{% endif %}
""")


# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
