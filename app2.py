"""
Flashcards — Révision Espacée
Flask webapp mobile-first, remplacement de l'app Streamlit.
Templates dans le dossier templates/.
"""

try:
    import fcntl  # Unix
except ImportError:
    fcntl = None  # Windows : pas de verrou fichier (voir locked_flashcards)
import json
import math
import os
import tempfile
import uuid
import random
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, send_file, send_from_directory
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

os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(REVIEW_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)


# ─── Couleur de boîte ────────────────────────────────────────────────────────
# La pastille « Boîte n » d'une carte de révision prend une couleur qui suit sa
# boîte Leitner : la boîte 1 (encore fragile) porte BOX_HUE_START, la boîte 60
# (acquis) porte BOX_HUE_END, et la teinte glisse de l'une à l'autre sur une
# échelle logarithmique — les premières boîtes changent vite de couleur, les
# dernières se rapprochent doucement de la teinte finale.
#
# Deux plages au choix — il suffit d'échanger les deux constantes :
#   0 → 140    rouge → ocre → mousse → vert   (route courte : rouge = fragile,
#              vert = acquis, la lecture la plus directe)
#   340 → 160  rose → violet → bleu → cyan → émeraude   (route longue : teintes
#              plus froides, chaque boîte un peu plus distincte de sa voisine)
#
# Le ton est calculé ici plutôt qu'en CSS : à clarté HSL égale, un jaune paraît
# bien plus lumineux qu'un bleu, ce qui ferait ressortir les boîtes du milieu
# comme une tache claire. On vise donc une luminance perçue (norme sRGB) et on
# résout la clarté qui l'atteint, teinte par teinte. Le gabarit pose la couleur
# en ligne, le CSS ne fait que la consommer.
BOX_MAX = 60
BOX_HUE_START = 0     # rouge — fragile
BOX_HUE_END = 140     # vert — acquis

# Pour chaque ton : (saturation boîte 1, saturation boîte 60,
#                    luminance perçue boîte 1, luminance perçue boîte 60).
# Monter la luminance éclaircit le ton, monter la saturation le colore. Ici la
# teinte seule varie d'une boîte à l'autre ; le texte de la pastille reste
# blanc, c'est donc le fond qui porte toute la couleur.
BOX_TONES = {
    "chip": (0.48, 0.48, 0.075, 0.075),     # fond de la pastille
}


def _box_progress(box):
    """Avancement 0 → 1 de la boîte, sur une échelle logarithmique."""
    try:
        b = int(box)
    except (TypeError, ValueError):
        b = 1
    b = max(1, min(BOX_MAX, b))
    return math.log(b) / math.log(BOX_MAX)


def _hsl_to_rgb(hue, sat, light):
    """hue en degrés, sat et light dans 0 → 1 ; renvoie trois canaux 0 → 1."""
    c = (1 - abs(2 * light - 1)) * sat
    hp = (hue % 360) / 60.0
    x = c * (1 - abs(hp % 2 - 1))
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x),
               (0, x, c), (x, 0, c), (c, 0, x)][int(hp) % 6]
    m = light - c / 2
    return r + m, g + m, b + m


def _luminance(rgb):
    """Luminance relative sRGB (norme WCAG) d'un triplet 0 → 1."""
    def channel(v):
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _tone(hue, sat, target):
    """Couleur hexadécimale de teinte `hue` et saturation `sat` dont la
    luminance perçue vaut `target` : on cherche la clarté par dichotomie."""
    low, high = 0.0, 1.0
    for _ in range(40):
        mid = (low + high) / 2
        if _luminance(_hsl_to_rgb(hue, sat, mid)) < target:
            low = mid
        else:
            high = mid
    rgb = _hsl_to_rgb(hue, sat, (low + high) / 2)
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v * 255))) for v in rgb)


@app.template_filter("box_style")
def box_style(box):
    """Les couleurs d'une boîte, prêtes à poser dans un attribut style."""
    p = _box_progress(box)
    hue = BOX_HUE_START - (BOX_HUE_START - BOX_HUE_END) * p
    return ";".join(
        "--box-%s:%s" % (name, _tone(hue, s1 + (s60 - s1) * p, l1 + (l60 - l1) * p))
        for name, (s1, s60, l1, l60) in BOX_TONES.items()
    )

# ─── Loi d'intervalle ────────────────────────────────────────────────────────
# Combien de jours séparent deux révisions d'une carte en boîte n ?
#
# Historiquement l'intervalle valait le numéro de boîte : boîte 20 → 20 jours.
# Cette règle linéaire récompense mal une carte solide — une bonne réponse en
# boîte 20 n'achetait qu'un seul jour de plus (+5 %), alors que le principe de
# la répétition espacée veut qu'un rappel réussi *multiplie* le délai tenable.
#
# On garde donc le linéaire tant que la carte s'installe (jusqu'à
# BOX_LINEAR_UNTIL), puis on accélère. La forme retenue est continue au seuil :
#
#     intervalle(n) = seuil × (n / seuil) ** puissance
#
# En n = seuil elle vaut exactement le seuil, et l'accélération s'installe
# progressivement — boîte 20 → 20 jours, boîte 21 → 23 jours. C'est ce qui la
# distingue d'un simple n ** puissance, qui ferait sauter l'intervalle de 20 à
# 96 jours d'une seule bonne réponse.
#
# Pour changer la loi il suffit des deux constantes ci-dessous ; les échéances
# déjà enregistrées se recalculent ensuite avec migrate_intervals.py.
BOX_LINEAR_UNTIL = 20      # en deçà : intervalle = numéro de boîte
BOX_INTERVAL_POWER = 2.5   # au-delà : accélération de la courbe
# Plafond de sécurité : on ne laisse jamais une carte dormir plus d'un an. Avec
# les réglages actuels la boîte 60 culmine à 312 jours, donc il ne mord pas —
# il est là pour rattraper une puissance montée trop haut par la suite.
BOX_INTERVAL_CAP = 365


def box_interval(box):
    """Nombre de jours avant la prochaine révision d'une carte en boîte `box`.

    Tolère une boîte absente ou illisible (repli sur 1) et la borne à BOX_MAX,
    comme _box_progress : cette fonction est appelée sur des données venues du
    disque et d'un formulaire, elle ne doit jamais lever."""
    try:
        b = int(box)
    except (TypeError, ValueError):
        b = 1
    b = max(1, min(BOX_MAX, b))
    if b <= BOX_LINEAR_UNTIL:
        days = b
    else:
        days = round(BOX_LINEAR_UNTIL * (b / BOX_LINEAR_UNTIL) ** BOX_INTERVAL_POWER)
    return min(days, BOX_INTERVAL_CAP)


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
        # Minuteur : secondes déjà passées en pause, et début de la pause en cours (None = actif).
        "paused_total": extra.get("paused_total", existing.get("paused_total", 0)),
        "paused_at": extra["paused_at"] if "paused_at" in extra else existing.get("paused_at"),
        # last_action: snapshot for the undo feature. None = nothing to undo.
        "last_action": extra["last_action"] if "last_action" in extra else existing.get("last_action"),
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
        data.setdefault("paused_total", 0)
        data.setdefault("paused_at", None)
        data.setdefault("last_action", None)
        return data
    return {"cards": [], "index": 0, "show_answer": False,
            "correct": 0, "incorrect": 0, "pass_count": 0,
            "start_time": datetime.now().isoformat(),
            "paused_total": 0, "paused_at": None,
            "last_action": None}

def clear_review_state():
    p = _review_path()
    if os.path.exists(p):
        os.remove(p)

def elapsed_seconds(state):
    """Secondes écoulées depuis le début de la session, pauses déduites.

    Si une pause est en cours, le chrono est figé à l'instant où elle a
    commencé. 0 si l'horodatage de départ est absent ou illisible."""
    try:
        start_dt = datetime.fromisoformat(state.get("start_time"))
    except Exception:
        return 0
    now = datetime.now()
    if state.get("paused_at"):
        try:
            now = min(now, datetime.fromisoformat(state["paused_at"]))
        except Exception:
            pass
    running = (now - start_dt).total_seconds() - (state.get("paused_total") or 0)
    return max(0, int(running))

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

def valid_backup_name(filename):
    """Un nom de sauvegarde légitime, sans échappement de dossier."""
    return (filename.startswith("flashcards_") and filename.endswith(".json")
            and "/" not in filename and ".." not in filename)

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
        if fcntl is not None:
            fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            cards = load_flashcards()
            yield cards
            save_flashcards(cards)
        finally:
            if fcntl is not None:
                fcntl.flock(lf, fcntl.LOCK_UN)

# ─── Journal des révisions ───────────────────────────────────────────────────
# Une carte ne garde qu'une seule `last_reviewed_date`, écrasée à chaque
# réponse : impossible de savoir combien de fois elle a été ratée, ni de tracer
# une courbe de progression. Ce journal comble le trou — une ligne JSON ajoutée
# par réponse, jamais réécrite.
#
# L'ajout est l'écriture la moins chère qui soit (quelques dizaines d'octets en
# fin de fichier, contre 2,4 Mo pour flashcards.json) et la plus sûre : une
# coupure en plein vol ne peut abîmer que la dernière ligne, que la lecture
# ignore. Le journal est donc écrit HORS du verrou des cartes.
#
# Une ligne :
#   {"ts": "2026-09-08T14:23:11", "card": "<uuid>", "result": "correct",
#    "from": 20, "to": 21, "mode": "focus", "face": "recto"}
#
# `result` vaut "correct", "incorrect", "pass" — ou "undo", qui annule la
# dernière réponse enregistrée pour cette carte (voir load_reviews).
REVIEWS_FILE = "reviews.jsonl"

# Dernière lecture analysée du journal, datée par (mtime, taille) du fichier.
_reviews_cache = {"stamp": None, "entries": []}


def log_review(card_id, result, box_from, box_to, mode, face=None):
    """Ajoute une ligne au journal. N'échoue jamais bruyamment : perdre une
    ligne de statistiques ne doit pas faire perdre une réponse à l'utilisateur."""
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "card": card_id,
        "result": result,
        "from": box_from,
        "to": box_to,
        "mode": mode,
    }
    if face:
        entry["face"] = face
    try:
        with open(REVIEWS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def load_reviews(since=None):
    """Le journal, annulations résolues, du plus ancien au plus récent.

    `since` : une date "YYYY-MM-DD" en deçà de laquelle on ne garde rien — le
    fichier grossit d'environ 400 lignes par jour, autant ne pas tout charger
    pour un graphique sur 30 jours.

    Une entrée "undo" retire la dernière réponse enregistrée pour la même carte,
    de sorte que le journal reste strictement en ajout tout en racontant ce qui
    s'est réellement passé. Les lignes illisibles (écriture interrompue) sont
    ignorées."""
    if not os.path.exists(REVIEWS_FILE):
        return []
    # Le journal ne fait que grandir (~400 lignes par jour) et plusieurs vues le
    # lisent dans la même requête. On garde la dernière analyse en mémoire, datée
    # par la taille et la date du fichier : un ajout invalide le cache, une
    # relecture à l'identique ne coûte rien.
    try:
        stamp = os.stat(REVIEWS_FILE)
        stamp = (stamp.st_mtime, stamp.st_size)
    except OSError:
        return []
    if _reviews_cache.get("stamp") == stamp:
        kept = _reviews_cache["entries"]
        return [e for e in kept if e.get("ts", "") >= since] if since else kept

    entries = []
    last_by_card = {}      # card_id -> position dans `entries` de sa dernière réponse
    try:
        with open(REVIEWS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue          # ligne tronquée : on passe
                if not isinstance(e, dict) or "card" not in e:
                    continue
                cid = e["card"]
                if e.get("result") == "undo":
                    pos = last_by_card.pop(cid, None)
                    if pos is not None:
                        entries[pos] = None
                    continue
                last_by_card[cid] = len(entries)
                entries.append(e)
    except OSError:
        return []
    kept = [e for e in entries if e is not None]
    _reviews_cache["stamp"], _reviews_cache["entries"] = stamp, kept
    if since:
        return [e for e in kept if e.get("ts", "") >= since]
    return kept


def review_stats(days=30):
    """Ce que le journal des révisions permet de dire, prêt pour le gabarit.

    Tout se calcule en une seule lecture du fichier. `pass` n'entre jamais dans
    un taux de réussite : une carte passée n'est ni sue ni ratée, la compter
    ferait baisser le taux sans qu'aucune réponse ait été fausse."""
    entries = load_reviews()
    if not entries:
        return {"total": 0}

    today = datetime.now().date()
    window_start = today - timedelta(days=days - 1)

    def rate(rows):
        """Taux de réussite en %, sur les seules réponses tranchées."""
        ok = sum(1 for e in rows if e.get("result") == "correct")
        ko = sum(1 for e in rows if e.get("result") == "incorrect")
        return (ok / (ok + ko) * 100) if (ok + ko) else None

    # Répartition par jour, sur toute l'histoire (sert au streak et à la fenêtre).
    by_day = {}
    for e in entries:
        by_day.setdefault(e.get("ts", "")[:10], []).append(e)

    # Fenêtre glissante : un point par jour, y compris les jours sans révision —
    # un trou dans la série est une information, pas une absence de donnée.
    daily = []
    for i in range(days):
        d = window_start + timedelta(days=i)
        ds = d.isoformat()
        rows = by_day.get(ds, [])
        daily.append({
            "date": ds,
            "correct": sum(1 for e in rows if e.get("result") == "correct"),
            "incorrect": sum(1 for e in rows if e.get("result") == "incorrect"),
            "passed": sum(1 for e in rows if e.get("result") == "pass"),
            "rate": rate(rows),
        })

    # Série de jours consécutifs. Ne pas avoir encore révisé aujourd'hui ne casse
    # pas la série : on part de la veille tant que la journée est en cours.
    cursor = today if by_day.get(today.isoformat()) else today - timedelta(days=1)
    streak = 0
    while by_day.get(cursor.isoformat()):
        streak += 1
        cursor -= timedelta(days=1)

    window = [e for e in entries if e.get("ts", "")[:10] >= window_start.isoformat()]
    graded = [e for e in entries if e.get("result") in ("correct", "incorrect")]

    return {
        "total": len(entries),
        "graded": len(graded),
        "days_covered": len(by_day),
        "first_day": min(by_day) if by_day else None,
        "success_rate": rate(entries),
        "success_rate_window": rate(window),
        "answers_today": len(by_day.get(today.isoformat(), [])),
        "answers_window": len(window),
        "streak": streak,
        "daily": daily,
        "window_days": days,
    }


# ─── Cartes rétives ──────────────────────────────────────────────────────────
# Une carte rétive (« leech ») est une carte qui revient sans jamais s'installer :
# on la rate, elle redescend d'une boîte, on la revoit, on la rate encore. Elle
# occupe la révision quotidienne sans rien apporter, et le remède n'est pas de la
# réviser davantage — c'est de la reformuler, de la scinder, ou de la supprimer.
#
# Deux signaux la désignent, et ils ne se recouvrent pas :
#
#   • le RETARD DE PROGRESSION, lisible dans les cartes elles-mêmes. En partant
#     de la boîte 1 sans jamais se tromper, une carte atteint la boîte n après
#     un temps connu (la somme des intervalles). Comparer la boîte qu'elle
#     devrait avoir à son âge et celle qu'elle a vraiment donne le nombre de
#     boîtes perdues en échecs. Ce signal fonctionne sur l'historique existant.
#
#   • les ÉCHECS AU JOURNAL, précis mais seulement à partir de la mise en
#     service de reviews.jsonl : nombre de « incorrect » sur la carte, et série
#     d'échecs consécutifs — celle-ci désigne une carte qui décroche maintenant,
#     bien avant que le retard n'ait eu le temps de se creuser.
LEECH_MIN_LAG = 10       # boîtes de retard sur la progression idéale
LEECH_MIN_FAILS = 5      # échecs cumulés au journal
LEECH_FAIL_STREAK = 3    # échecs consécutifs sur les dernières réponses
LEECH_MIN_AGE = 30       # jours : en deçà, une carte n'a pas eu sa chance

# Jours cumulés pour atteindre chaque boîte sans jamais se tromper.
# BOX_CUMULATIVE_DAYS[n] = temps nécessaire pour arriver en boîte n.
BOX_CUMULATIVE_DAYS = [0, 0]
for _b in range(1, BOX_MAX + 1):
    BOX_CUMULATIVE_DAYS.append(BOX_CUMULATIVE_DAYS[-1] + box_interval(_b))


def expected_box(age_days):
    """La boîte qu'une carte de cet âge aurait atteinte sans jamais être ratée."""
    b = 1
    while b < BOX_MAX and BOX_CUMULATIVE_DAYS[b + 1] <= age_days:
        b += 1
    return b


def progression_lag(card, today=None):
    """Boîtes perdues en échecs, ou None si la carte n'est pas jugeable
    (jamais révisée, trop jeune, ou date de création absente/illisible)."""
    if not card.get("last_reviewed_date"):
        return None
    try:
        born = datetime.strptime(card["creation_date"], "%Y-%m-%d").date()
    except (KeyError, TypeError, ValueError):
        return None
    age = ((today or datetime.now().date()) - born).days
    if age < LEECH_MIN_AGE:
        return None
    return expected_box(age) - card.get("box", 1)


def card_failure_counts():
    """Par carte, ce que le journal sait de ses échecs :
    {card_id: {"fails": n, "graded": n, "streak": n}} — `streak` étant le nombre
    d'échecs consécutifs les plus récents (0 si la dernière réponse est bonne)."""
    stats = {}
    for e in load_reviews():
        res = e.get("result")
        if res not in ("correct", "incorrect"):
            continue          # une carte passée ne dit rien de sa difficulté
        s = stats.setdefault(e["card"], {"fails": 0, "graded": 0, "streak": 0})
        s["graded"] += 1
        if res == "incorrect":
            s["fails"] += 1
            s["streak"] += 1
        else:
            s["streak"] = 0
    return stats


def get_leech_cards(cards=None):
    """Les cartes rétives, la plus préoccupante d'abord.

    Renvoie une liste de dicts {card, lag, fails, graded, streak, reasons}, où
    `reasons` énumère les signaux qui se sont déclenchés — pour que l'écran dise
    *pourquoi* une carte est là, et pas seulement qu'elle y est."""
    cards = load_flashcards() if cards is None else cards
    failures = card_failure_counts()
    today = datetime.now().date()
    out = []
    for c in cards:
        lag = progression_lag(c, today)
        f = failures.get(c["id"], {"fails": 0, "graded": 0, "streak": 0})
        reasons = []
        if lag is not None and lag >= LEECH_MIN_LAG:
            reasons.append(f"{lag} boîtes de retard")
        if f["fails"] >= LEECH_MIN_FAILS:
            reasons.append(f"{f['fails']} échecs")
        if f["streak"] >= LEECH_FAIL_STREAK:
            reasons.append(f"{f['streak']} échecs d'affilée")
        if not reasons:
            continue
        out.append({"card": c, "lag": lag or 0, "fails": f["fails"],
                    "graded": f["graded"], "streak": f["streak"],
                    "reasons": reasons})
    # Les échecs consécutifs passent devant : c'est le signal le plus actuel.
    out.sort(key=lambda x: (x["streak"], x["fails"], x["lag"]), reverse=True)
    return out


# ─── Données des graphiques ──────────────────────────────────────────────────

def forecast_data(days=90, cards=None):
    """Le retard accumulé, puis la charge programmée jour par jour.

    Le retard est compté à part et non fondu dans la première barre : c'est une
    dette, pas une journée de travail — et c'est la seule chose qu'un graphique
    tourné vers l'avenir ne montre jamais."""
    cards = load_flashcards() if cards is None else cards
    today = datetime.now().date()
    horizon = today + timedelta(days=days)
    overdue = 0
    per_day = {}
    for c in cards:
        raw = c.get("next_review_date")
        if not raw:
            continue
        try:
            d = datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d <= today:
            overdue += 1
        elif d <= horizon:
            per_day[d.isoformat()] = per_day.get(d.isoformat(), 0) + 1
    series = [{"date": (today + timedelta(days=i)).isoformat(),
               "count": per_day.get((today + timedelta(days=i)).isoformat(), 0)}
              for i in range(1, days + 1)]
    # Régime stable : ce que le paquet redemanderait chaque jour si les
    # échéances étaient parfaitement étalées. La ligne de référence du graphique.
    steady = sum(1.0 / box_interval(c.get("box", 1)) for c in cards)
    return {"overdue": overdue, "days": series, "steady": round(steady, 1),
            "horizon": days}


def progression_cloud(cards=None):
    """Chaque carte située par son âge et sa boîte, face à la progression idéale.

    Agrégé par semaine d'âge : 5 930 cartes tiennent en ~600 cellules, ce qui
    évite de tracer un point par carte. La courbe idéale est celle d'une carte
    jamais ratée — tout ce qui est nettement en dessous a trébuché en chemin."""
    cards = load_flashcards() if cards is None else cards
    today = datetime.now().date()
    cells = {}
    max_age = 0
    for c in cards:
        try:
            age = (today - datetime.strptime(c["creation_date"], "%Y-%m-%d").date()).days
        except (KeyError, TypeError, ValueError):
            continue
        if age < 0:
            continue
        max_age = max(max_age, age)
        key = (age // 7 * 7, c.get("box", 1))
        cells[key] = cells.get(key, 0) + 1
    cloud = [{"x": x, "y": y, "n": n} for (x, y), n in sorted(cells.items())]
    ideal = [{"x": BOX_CUMULATIVE_DAYS[b], "y": b}
             for b in range(1, BOX_MAX + 1)
             if BOX_CUMULATIVE_DAYS[b] <= max_age]
    return {"cloud": cloud, "ideal": ideal, "max_age": max_age,
            "max_n": max((c["n"] for c in cloud), default=1)}


# Tranches d'intervalle pour la courbe de rétention. Bornes en jours, incluses.
RETENTION_BUCKETS = [(1, 1), (2, 3), (4, 7), (8, 14), (15, 30),
                     (31, 60), (61, 120), (121, 10**6)]


def retention_by_interval():
    """Taux de réussite selon le temps écoulé depuis la révision précédente.

    Une carte répondue alors qu'elle était en boîte b venait de tenir
    box_interval(b) jours : c'est l'intervalle qu'elle a « survécu ». Regrouper
    les réponses par cette durée donne la courbe d'oubli réelle du paquet — la
    mesure qui dit si la loi d'intervalle est trop ambitieuse. Si le taux
    s'effondre au-delà d'une tranche, c'est là qu'il faut freiner."""
    tallies = {b: [0, 0] for b in RETENTION_BUCKETS}   # [réussites, tranchées]
    for e in load_reviews():
        if e.get("result") not in ("correct", "incorrect"):
            continue
        try:
            iv = box_interval(e.get("from", 1))
        except Exception:
            continue
        for lo, hi in RETENTION_BUCKETS:
            if lo <= iv <= hi:
                tallies[(lo, hi)][1] += 1
                if e["result"] == "correct":
                    tallies[(lo, hi)][0] += 1
                break
    out = []
    for lo, hi in RETENTION_BUCKETS:
        ok, n = tallies[(lo, hi)]
        label = f"{lo} j" if lo == hi else (f"{lo}+ j" if hi >= 10**6 else f"{lo}–{hi} j")
        out.append({"label": label, "n": n,
                    "rate": round(ok / n * 100, 1) if n else None})
    return out


def review_heatmap(days=364):
    """Nombre de réponses par jour sur l'année écoulée, pour le calendrier.

    Contrairement au calendrier de création, celui-ci compte les révisions —
    l'habitude, pas la collection."""
    counts = {}
    for e in load_reviews():
        d = e.get("ts", "")[:10]
        if d:
            counts[d] = counts.get(d, 0) + 1
    end = datetime.now().date()
    start = end - timedelta(days=days)
    return [{"date": (start + timedelta(days=i)).isoformat(),
             "count": counts.get((start + timedelta(days=i)).isoformat(), 0)}
            for i in range(days + 1)]


# ─── Palette des préfixes emoji ──────────────────────────────────────────────
# Les pastilles proposées au-dessus des champs de création / d'édition. La liste
# vit dans un fichier à part pour être modifiable depuis l'app (bouton ✏️ de la
# rangée) sans toucher au code ; si le fichier manque ou devient illisible, on
# retombe sur DEFAULT_EMOJI_PREFIXES.
#
# Une entrée = {recto, verso, short, name} :
#   recto / verso identiques  → un même marqueur posé sur les deux faces
#   recto / verso distincts   → une pastille à sens (🇬🇧 → 🇫🇷, puis l'inverse)
#   short                     → libellé court affiché sur la pastille (peut être vide)
#   name                      → texte de l'infobulle

EMOJI_FILE = "emoji_prefixes.json"
EMOJI_LOCK_FILE = EMOJI_FILE + ".lock"
EMOJI_MAX_PREFIXES = 40   # au-delà, la rangée déborde et ne se lit plus
EMOJI_MAX_LEN = 16        # un emoji composé (drapeau, famille) tient largement dedans
EMOJI_SHORT_MAX = 10
EMOJI_NAME_MAX = 80

DEFAULT_EMOJI_PREFIXES = [
    {"recto": "🇬🇧", "verso": "🇫🇷", "short": "",        "name": "une langue par face — recliquez pour inverser le sens"},
    {"recto": "📖", "verso": "📖", "short": "DÉF",     "name": "Définition"},
    {"recto": "📜", "verso": "📜", "short": "HIST",    "name": "Histoire"},
    {"recto": "👤", "verso": "👤", "short": "PERSO",   "name": "Personnage — figure historique ou importante"},
    {"recto": "🗺️", "verso": "🗺️", "short": "GÉO",     "name": "Géographie"},
    {"recto": "🎨", "verso": "🎨", "short": "TAB",     "name": "Tableau — peinture et son auteur"},
    {"recto": "💡", "verso": "💡", "short": "CONCEPT", "name": "Concept"},
]


class EmojiPrefixError(ValueError):
    """Saisie refusée — le message est montré tel quel à l'utilisateur."""


def clean_emoji_prefix(raw):
    """Normalise une entrée saisie (ou relue du fichier) en {recto, verso, short, name}.

    Le marqueur ne doit contenir aucune espace : le script client repère le
    préfixe en tête de champ puis coupe l'espace qui suit, un marqueur à trou
    casserait cette lecture.
    """
    if not isinstance(raw, dict):
        raise EmojiPrefixError("Entrée illisible.")
    recto = (raw.get("recto") or "").strip()
    verso = (raw.get("verso") or "").strip() or recto   # verso vide = même marqueur des deux côtés
    short = " ".join((raw.get("short") or "").split())
    name = " ".join((raw.get("name") or "").split())

    if not recto:
        raise EmojiPrefixError("Il faut au moins un emoji pour le recto.")
    for value in (recto, verso):
        if len(value) > EMOJI_MAX_LEN:
            raise EmojiPrefixError("Emoji trop long (%d caractères au maximum)." % EMOJI_MAX_LEN)
        if any(ch.isspace() for ch in value):
            raise EmojiPrefixError("Un emoji ne peut pas contenir d'espace.")
    if len(short) > EMOJI_SHORT_MAX:
        raise EmojiPrefixError("Libellé trop long (%d caractères au maximum)." % EMOJI_SHORT_MAX)

    return {
        "recto": recto,
        "verso": verso,
        "short": short,
        "name": (name or short or recto)[:EMOJI_NAME_MAX],
    }


def _read_emoji_prefixes():
    """Liste du fichier, nettoyée ; défauts si le fichier manque ou est cassé."""
    if not os.path.exists(EMOJI_FILE):
        return [dict(item) for item in DEFAULT_EMOJI_PREFIXES]
    try:
        with open(EMOJI_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return [dict(item) for item in DEFAULT_EMOJI_PREFIXES]
    if not isinstance(raw, list):
        return [dict(item) for item in DEFAULT_EMOJI_PREFIXES]

    items, seen = [], set()
    for entry in raw:
        try:
            item = clean_emoji_prefix(entry)
        except EmojiPrefixError:
            continue          # une entrée abîmée ne doit pas emporter toute la palette
        key = (item["recto"], item["verso"])
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items[:EMOJI_MAX_PREFIXES]


def _write_emoji_prefixes(items):
    """Écriture atomique : le fichier lu par une autre requête reste entier."""
    fd, tmp_path = tempfile.mkstemp(dir=".", prefix=EMOJI_FILE + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=4, ensure_ascii=False)
        os.replace(tmp_path, EMOJI_FILE)
    except BaseException:
        remove_quietly(tmp_path)
        raise


@contextmanager
def locked_emoji_prefixes():
    """Charge, cède, puis réécrit la palette sous verrou exclusif.

        with locked_emoji_prefixes() as items:
            items.append(...)      # modifié sur place
    """
    with open(EMOJI_LOCK_FILE, "w") as lf:
        if fcntl is not None:
            fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            items = _read_emoji_prefixes()
            yield items
            _write_emoji_prefixes(items)
        finally:
            if fcntl is not None:
                fcntl.flock(lf, fcntl.LOCK_UN)


def load_emoji_prefixes():
    return _read_emoji_prefixes()


@app.context_processor
def inject_emoji_prefixes():
    """La palette est lue à chaque rendu : les pages ouvertes ailleurs voient
    la liste à jour dès leur prochain chargement, sans redémarrage."""
    return {"emoji_prefixes": load_emoji_prefixes()}


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

def _safe_image_basename(filename):
    """Reduce an uploaded filename to a safe basename to store in IMAGE_DIR.
    Unlike save_uploaded_image() (which assigns a UUID), the bulk importer keeps
    the *original* name so a JSON path like "images/chat.png" or "chat.png" still
    resolves to it. We strip any directory part (handles folder uploads whose
    filename is "images/chat.png"), reject empty / "." / ".." and disallowed
    extensions, but preserve accents and spaces so the name matches the JSON.
    Returns the safe basename, or None if the file should be skipped."""
    if not filename:
        return None
    name = os.path.basename(filename.replace("\\", "/")).strip()
    if not name or name in (".", "..") or not allowed_file(name):
        return None
    return name

def save_bulk_images(file_list):
    """Save uploaded image files into IMAGE_DIR under their original basename.
    Returns (created, skipped): `created` is the list of paths that did not exist
    before (safe to delete on a rollback), `skipped` the filenames we refused
    (bad extension / name). Pre-existing same-named files are overwritten and are
    NOT reported as created, so a rollback never deletes images already on disk."""
    created, skipped = [], []
    for fs in file_list:
        if not fs or not fs.filename:
            continue
        name = _safe_image_basename(fs.filename)
        if not name:
            skipped.append(fs.filename)
            continue
        dest = os.path.join(IMAGE_DIR, name)
        existed = os.path.exists(dest)
        try:
            fs.save(dest)
        except OSError:
            skipped.append(fs.filename)
            continue
        if not existed:
            created.append(dest)
    return created, skipped

def delete_image_file(path):
    """Remove a local image file, but ONLY if it resolves inside IMAGE_DIR.
    Remote URLs (http/https) and any path that escapes IMAGE_DIR (e.g. a hostile
    or malformed card path like "flashcards.json" or "../secret") are ignored, so
    deleting a card can never remove arbitrary files on disk."""
    if not path or path.startswith("http"):
        return
    try:
        base = os.path.realpath(IMAGE_DIR)
        target = os.path.realpath(path)
        if target == base or not target.startswith(base + os.sep):
            return
        if os.path.exists(target):
            os.remove(target)
    except OSError:
        pass

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

def capitalize_first(text):
    """Majuscule à la première lettre du texte d'une face, en sautant un
    éventuel préfixe emoji : "🇬🇧 dog" devient "🇬🇧 Dog".

    Deux garde-fous : un texte qui commence par un chiffre est laissé tel quel
    ("1er janvier"), et un mot dont la deuxième lettre est déjà une majuscule
    aussi ("iPhone", "eBay") — sans quoi on le défigurerait.
    Le formulaire applique la même règle en direct (voir base.html) ; ceci en
    est le filet, y compris pour l'import en masse."""
    if not text:
        return text
    for i, char in enumerate(text):
        if char.isdigit():
            return text
        if char.isalpha():
            following = text[i + 1] if i + 1 < len(text) else ""
            if char.islower() and not following.isupper():
                return text[:i] + char.upper() + text[i + 1:]
            return text
    return text

def form_text(field):
    """Read a multi-line form field. Browsers submit textarea newlines as CRLF;
    normalise to LF so the stored JSON stays clean and renders identically.
    La première lettre passe en majuscule, comme dans le formulaire."""
    value = request.form.get(field, "")
    return capitalize_first(value.replace("\r\n", "\n").replace("\r", "\n").strip())

def index_by_id(cards):
    """Build a dict {card_id: (index, card)} for O(1) lookup."""
    return {c["id"]: (i, c) for i, c in enumerate(cards)}

def get_daily_review_cards(cards=None):
    today = datetime.now().strftime("%Y-%m-%d")
    return [c for c in (load_flashcards() if cards is None else cards)
            if c.get("next_review_date", "") <= today]

def get_marked_cards(cards=None):
    return [c for c in (load_flashcards() if cards is None else cards) if c.get("marked", False)]

# ─── Révision anticipée ──────────────────────────────────────────────────────
#  Permet de réviser aujourd'hui des cartes dues plus tard, avant une période
#  où l'on sait qu'on ne pourra pas réviser (vacances…). Restreint aux boîtes
#  élevées : une carte à intervalle long ne perd presque rien à être avancée
#  d'un ou deux jours, contrairement à une carte encore en apprentissage actif.

ADVANCE_DEFAULT_DAYS = 1        # horizon par défaut : demain
ADVANCE_DEFAULT_MIN_BOX = 9     # « au-delà de la boîte 8 »
ADVANCE_MAX_DAYS = 14

def get_advance_review_cards(days, min_box, cards=None):
    """Cartes pas encore dues, à échéance dans les `days` prochains jours et en
    boîte >= min_box. Exclut les cartes déjà dues : celles-là sont du ressort de
    la révision du jour."""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    horizon = (now + timedelta(days=days)).strftime("%Y-%m-%d")
    return [c for c in (load_flashcards() if cards is None else cards)
            if c.get("box", 1) >= min_box
            and today < c.get("next_review_date", "") <= horizon]

def advance_params():
    """Lit et borne les réglages d'anticipation passés en query string."""
    days = request.args.get("days", ADVANCE_DEFAULT_DAYS, type=int)
    min_box = request.args.get("min_box", ADVANCE_DEFAULT_MIN_BOX, type=int)
    return max(1, min(ADVANCE_MAX_DAYS, days)), max(1, min(60, min_box))

def cards_for_mode(mode):
    """Résout un mode de révision en (cartes, message si la liste est vide)."""
    if mode == "daily":
        return get_daily_review_cards(), "Aucune carte à réviser !"
    if mode == "marked":
        return get_marked_cards(), "Aucune carte marquée."
    if mode == "advance":
        days, min_box = advance_params()
        return (get_advance_review_cards(days, min_box),
                "Aucune carte à anticiper avec ces réglages.")
    return [], "Aucune carte à réviser !"

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
            cleanup_stale_sessions()
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
    all_cards = load_flashcards()   # chargé une fois, partagé par les 3 compteurs
    daily = get_daily_review_cards(all_cards)
    marked = get_marked_cards(all_cards)
    advance = get_advance_review_cards(ADVANCE_DEFAULT_DAYS, ADVANCE_DEFAULT_MIN_BOX, all_cards)
    return render_template("index.html", title="Réviser", active="review", body_class="",
                           daily_count=len(daily), marked_count=len(marked),
                           advance_count=len(advance),
                           advance_days=ADVANCE_DEFAULT_DAYS,
                           advance_min_box=ADVANCE_DEFAULT_MIN_BOX,
                           advance_max_days=ADVANCE_MAX_DAYS)

# ── Review session ───────────────────────────────────────────────────────────

@app.route("/review/start/<mode>")
@login_required
def review_start(mode):
    cleanup_stale_sessions()
    cards, empty_message = cards_for_mode(mode)
    random.shuffle(cards)
    if not cards:
        flash(empty_message, "info")
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
        minutes, seconds = divmod(elapsed_seconds(state), 60)
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
        show_answer=show_answer, idx=idx, total=len(cards),
        last_action=state.get("last_action"),
        elapsed=elapsed_seconds(state), paused=bool(state.get("paused_at"))
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

    # Snapshot for undo: capture counters BEFORE incrementing
    last_action = None
    # Ce qu'il faudra consigner au journal, une fois le verrou des cartes rendu.
    journal = None

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
                # Capture FULL previous state of this card for undo
                last_action = {
                    "card_id": c["id"],
                    "result": result,
                    "previous_box": c["box"],
                    "previous_last_reviewed_date": c.get("last_reviewed_date"),
                    "previous_next_review_date": c.get("next_review_date"),
                    "previous_current_face": c.get("current_face", "recto"),
                    "previous_correct": state.get("correct", 0),
                    "previous_incorrect": state.get("incorrect", 0),
                    "previous_pass_count": state.get("pass_count", 0),
                    "previous_index": idx,
                }
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
                journal = (last_action["card_id"], last_action["previous_box"],
                           all_cards[i]["box"], last_action["previous_current_face"])
    if journal:
        # La route accepte n'importe quelle chaîne et traite tout ce qui n'est ni
        # "correct" ni "incorrect" comme un passage : le journal dit la même chose,
        # plutôt que de consigner une valeur fantaisiste venue de l'URL.
        logged = result if result in ("correct", "incorrect") else "pass"
        log_review(journal[0], logged, journal[1], journal[2], "focus", face=journal[3])
    save_review_state(cards, idx + 1, False,
                      correct=correct, incorrect=incorrect, pass_count=pass_count,
                      last_action=last_action)
    return redirect(url_for("review_card"))


# ── Undo last answer ────────────────────────────────────────────────────────

@app.route("/review/undo", methods=["POST", "GET"])
@login_required
def review_undo():
    state = load_review_state()
    last = state.get("last_action")
    if not last:
        # Nothing to undo (race condition: button clicked twice, expired toast, etc.)
        return redirect(url_for("review_card"))

    # Restore the card's previous state in flashcards.json
    with locked_flashcards() as all_cards:
        card_index = index_by_id(all_cards)
        if last["card_id"] in card_index:
            i, _ = card_index[last["card_id"]]
            all_cards[i]["box"] = last["previous_box"]
            # Use direct assignment (None values are valid: never reviewed)
            all_cards[i]["last_reviewed_date"] = last["previous_last_reviewed_date"]
            all_cards[i]["next_review_date"]   = last["previous_next_review_date"]
            all_cards[i]["current_face"]       = last["previous_current_face"]

    # Le journal reste en ajout : on n'efface pas la réponse annulée, on écrit
    # son annulation. load_reviews() se charge de la faire disparaître.
    log_review(last["card_id"], "undo", last.get("previous_box"),
               last.get("previous_box"), "focus")

    # Restore session counters and rewind index by 1
    save_review_state(
        state["cards"],
        last["previous_index"],
        False,
        correct=last["previous_correct"],
        incorrect=last["previous_incorrect"],
        pass_count=last["previous_pass_count"],
        last_action=None,  # Clear: no double-undo
    )
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


# ── Minuteur : pause / reprise ───────────────────────────────────────────────

@app.route("/review/timer/<mode>/<action>", methods=["POST"])
@login_required
def review_timer(mode, action):
    """Met le minuteur en pause ou le relance, pour les deux modes de révision.

    L'état vit côté serveur : la pause survit donc aux rechargements de page
    entre deux cartes (mode focus) ou deux fournées (mode grille)."""
    if mode not in ("focus", "grid") or action not in ("pause", "resume"):
        return jsonify(error="requête invalide"), 400

    state = load_grid_state() if mode == "grid" else load_review_state()
    if not state.get("cards"):
        return jsonify(error="aucune session en cours"), 404

    now = datetime.now()
    paused_at = state.get("paused_at")
    if action == "pause":
        if not paused_at:                     # déjà en pause → sans effet
            state["paused_at"] = now.isoformat()
    elif paused_at:                           # déjà actif → sans effet
        try:
            gap = (now - datetime.fromisoformat(paused_at)).total_seconds()
        except Exception:
            gap = 0
        state["paused_total"] = (state.get("paused_total") or 0) + max(0, gap)
        state["paused_at"] = None

    if mode == "grid":
        save_grid_state(state["cards"], state["index"],
                        state.get("batch", GRID_DEFAULT_BATCH),
                        paused_total=state["paused_total"], paused_at=state["paused_at"])
    else:
        save_review_state(state["cards"], state["index"], state["show_answer"],
                          paused_total=state["paused_total"], paused_at=state["paused_at"])
    return jsonify(elapsed=elapsed_seconds(state), paused=bool(state["paused_at"]))

# ═══════════════════════════════════════════════════════════════════════════════
#  MODE GRILLE — révision multi-cartes (notation en lot)
#  ───────────────────────────────────────────────────────────────────────────────
#  À COLLER dans app2.py, par exemple juste APRÈS la route `/review/quit`
#  (la fonction review_quit), et AVANT la section "Manage cards".
#
#  ✅ Bloc 100 % additif : n'édite aucune fonction existante.
#  ✅ Réutilise tes helpers existants : get_daily_review_cards, get_marked_cards,
#     locked_flashcards, index_by_id, cleanup_stale_sessions, REVIEW_DIR, etc.
#  ✅ Utilise un fichier d'état séparé ({sid}_grid.json) pour ne pas interférer
#     avec la session de révision carte-par-carte.
#  ✅ Logique Leitner identique à /review/answer (boîte ±1, flip de current_face,
#     recalcul de next_review_date).
# ═══════════════════════════════════════════════════════════════════════════════

GRID_DEFAULT_BATCH = 10         # nombre de cartes par fournée (modifiable via ?size=)


def _grid_path():
    sid = session.get("_review_sid")
    if not sid:
        sid = str(uuid.uuid4())
        session["_review_sid"] = sid
    return os.path.join(REVIEW_DIR, f"{sid}_grid.json")


def save_grid_state(cards, index, batch, **extra):
    p = _grid_path()
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
        "batch": batch,
        "correct": extra.get("correct", existing.get("correct", 0)),
        "incorrect": extra.get("incorrect", existing.get("incorrect", 0)),
        "pass_count": extra.get("pass_count", existing.get("pass_count", 0)),
        "start_time": extra.get("start_time", existing.get("start_time", datetime.now().isoformat())),
        # Minuteur : secondes déjà passées en pause, et début de la pause en cours (None = actif).
        "paused_total": extra.get("paused_total", existing.get("paused_total", 0)),
        "paused_at": extra["paused_at"] if "paused_at" in extra else existing.get("paused_at"),
    }
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def load_grid_state():
    p = _grid_path()
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("paused_total", 0)
        data.setdefault("paused_at", None)
        return data
    return {"cards": [], "index": 0, "batch": GRID_DEFAULT_BATCH,
            "correct": 0, "incorrect": 0, "pass_count": 0,
            "start_time": datetime.now().isoformat(),
            "paused_total": 0, "paused_at": None}


def clear_grid_state():
    p = _grid_path()
    if os.path.exists(p):
        os.remove(p)


def _card_faces(card):
    """Retourne les faces question/réponse en respectant current_face
    (exactement la même logique que la route /review)."""
    is_recto = card.get("current_face", "recto") == "recto"
    if is_recto:
        q_path, q_text, q_audio = card.get("recto_path"), card.get("recto_text"), card.get("recto_audio")
        a_path, a_text, a_audio = card.get("verso_path"), card.get("verso_text"), card.get("verso_audio")
    else:
        q_path, q_text, q_audio = card.get("verso_path"), card.get("verso_text"), card.get("verso_audio")
        a_path, a_text, a_audio = card.get("recto_path"), card.get("recto_text"), card.get("recto_audio")
    return {
        "id": card["id"], "box": card.get("box"), "marked": card.get("marked", False),
        "q_path": q_path, "q_text": q_text, "q_audio": q_audio,
        "a_path": a_path, "a_text": a_text, "a_audio": a_audio,
    }


@app.route("/review/grid/start/<mode>")
@login_required
def review_grid_start(mode):
    cleanup_stale_sessions()
    batch = request.args.get("size", GRID_DEFAULT_BATCH, type=int)
    batch = max(2, min(24, batch))
    cards, empty_message = cards_for_mode(mode)
    random.shuffle(cards)
    if not cards:
        flash(empty_message, "info")
        return redirect(url_for("index"))
    save_grid_state(cards, 0, batch, correct=0, incorrect=0, pass_count=0,
                    start_time=datetime.now().isoformat())
    return redirect(url_for("review_grid"))


@app.route("/review/grid")
@login_required
def review_grid():
    state = load_grid_state()
    cards = state["cards"]
    idx = state["index"]
    batch = state.get("batch", GRID_DEFAULT_BATCH)

    # Fin de session → écran de bilan (réutilise review_done.html)
    if not cards or idx >= len(cards):
        minutes, seconds = divmod(elapsed_seconds(state), 60)
        summary = {
            "correct": state.get("correct", 0),
            "incorrect": state.get("incorrect", 0),
            "pass_count": state.get("pass_count", 0),
            "total": len(cards),
            "duration": f"{minutes}m {seconds:02d}s",
        }
        clear_grid_state()
        return render_template("review_done.html", title="Terminé !", active="review",
                               body_class="", **summary)

    batch_cards = [_card_faces(c) for c in cards[idx: idx + batch]]
    cur_batch = idx // batch + 1
    total_batches = (len(cards) + batch - 1) // batch
    return render_template(
        "review_grid.html", title="Révision — Grille", active="review",
        body_class="review-mode", cards=batch_cards,
        idx=idx, total=len(cards), batch=batch,
        cur_batch=cur_batch, total_batches=total_batches,
        elapsed=elapsed_seconds(state), paused=bool(state.get("paused_at")),
    )


@app.route("/review/grid/answer", methods=["POST"])
@login_required
def review_grid_answer():
    state = load_grid_state()
    cards = state["cards"]
    idx = state["index"]
    batch = state.get("batch", GRID_DEFAULT_BATCH)
    correct = state.get("correct", 0)
    incorrect = state.get("incorrect", 0)
    pass_count = state.get("pass_count", 0)

    batch_ids = [c["id"] for c in cards[idx: idx + batch]]
    # Champs du formulaire : grade_<id> = "ok" | "no" | "" (vide → passée)
    grades = {cid: request.form.get(f"grade_{cid}", "") for cid in batch_ids}

    journal = []          # consigné après la remise du verrou des cartes
    with locked_flashcards() as all_cards:
        card_index = index_by_id(all_cards)
        now = datetime.now()
        for cid, g in grades.items():
            if g == "ok":
                correct += 1
            elif g == "no":
                incorrect += 1
            else:
                pass_count += 1           # non notée = passée (aucun changement de boîte)
            if cid not in card_index:
                continue
            i, c = card_index[cid]
            box_before = c["box"]
            face_shown = c.get("current_face", "recto")
            if g in ("ok", "no"):
                if g == "ok":
                    all_cards[i]["box"] = min(60, c["box"] + 1)
                else:
                    all_cards[i]["box"] = max(1, c["box"] - 1)
                all_cards[i]["last_reviewed_date"] = now.strftime("%Y-%m-%d")
                all_cards[i]["next_review_date"] = (now + timedelta(days=box_interval(all_cards[i]["box"]))).strftime("%Y-%m-%d")
                all_cards[i]["current_face"] = "verso" if c.get("current_face", "recto") == "recto" else "recto"
            journal.append((cid, {"ok": "correct", "no": "incorrect"}.get(g, "pass"),
                            box_before, all_cards[i]["box"], face_shown))

    for cid, res, box_from, box_to, face in journal:
        log_review(cid, res, box_from, box_to, "grid", face=face)

    save_grid_state(cards, idx + batch, batch,
                    correct=correct, incorrect=incorrect, pass_count=pass_count)
    return redirect(url_for("review_grid"))


@app.route("/review/grid/quit", methods=["POST", "GET"])
@login_required
def review_grid_quit():
    clear_grid_state()
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

    # La liste détaillée n'est calculée que si on l'affiche ; le compteur, lui,
    # est nécessaire à chaque rendu pour la pastille du filtre.
    leeches = get_leech_cards(all_cards)
    never_count = sum(1 for c in all_cards if not c.get("last_reviewed_date"))
    return render_template("manage.html", title="Gérer", active="manage", body_class="",
                           boxes=boxes, selected_box=selected_box,
                           cards=cards_in_box, filter_mode=filter_mode,
                           never_count=never_count,
                           leeches=leeches if filter_mode == "leeches" else [],
                           leech_count=len(leeches))


@app.route("/manage/mark_leeches", methods=["POST"])
@login_required
def mark_leeches():
    """Marque toutes les cartes rétives d'un coup, pour les reprendre ensuite
    dans le mode de révision « cartes marquées » qui existe déjà."""
    with locked_flashcards() as all_cards:
        ids = {x["card"]["id"] for x in get_leech_cards(all_cards)}
        deja = 0
        for c in all_cards:
            if c["id"] in ids:
                if c.get("marked"):
                    deja += 1
                c["marked"] = True
    nouvelles = len(ids) - deja
    if not ids:
        flash("Aucune carte rétive à marquer.", "info")
    elif nouvelles:
        flash(f"🔖 {nouvelles} carte(s) marquée(s)"
              + (f" ({deja} l'étaient déjà)." if deja else "."), "success")
    else:
        flash(f"Ces {deja} carte(s) étaient déjà marquées.", "info")
    return redirect(url_for("manage", filter="leeches"))

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

def _resolve_face_image(current, upload, url, remove):
    """Résout la nouvelle image d'une face lors d'une modification de carte.

    L'image doit survivre à une modification qui ne la concerne pas (corriger le
    texte de l'autre face, changer la boîte…), exactement comme le texte et
    l'audio. Elle ne change donc que sur un geste explicite : un nouvel upload,
    une URL différente, la case « supprimer », ou — pour une image distante,
    dont le formulaire affiche l'URL — le vidage du champ URL.
    Renvoie le nouveau chemin, après suppression du fichier local remplacé."""
    if upload and upload.filename:
        delete_image_file(current)
        return save_uploaded_image(upload)
    if remove:
        delete_image_file(current)
        return None
    if url:
        if url != current:
            delete_image_file(current)  # no-op si l'ancienne valeur est une URL
        return url
    if current and current.startswith("http"):
        # Le champ URL était pré-rempli avec cette valeur : le vider est le
        # geste de suppression d'une image distante.
        return None
    return current  # image locale : conservée telle quelle

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
        # On ne recalcule next_review_date que si la boîte a effectivement changé,
        # afin de préserver le calendrier de révision lors d'une simple correction
        # de contenu (texte, image, audio).
        if new_box != all_cards[idx]["box"]:
            all_cards[idx]["box"] = new_box
            base = all_cards[idx].get("last_reviewed_date") or all_cards[idx].get("creation_date")
            base_dt = datetime.strptime(base, "%Y-%m-%d") if base else datetime.now()
            all_cards[idx]["next_review_date"] = (base_dt + timedelta(days=box_interval(new_box))).strftime("%Y-%m-%d")

        # Recto / Verso — une image n'est touchée que sur un geste explicite ;
        # une nouvelle image (upload ou URL) remplace le texte de sa face.
        for face in ("recto", "verso"):
            old_path = all_cards[idx].get(f"{face}_path")
            new_path = _resolve_face_image(
                old_path,
                request.files.get(f"{face}_upload"),
                request.form.get(f"{face}_url", "").strip(),
                request.form.get(f"{face}_remove_image"),
            )
            all_cards[idx][f"{face}_path"] = new_path
            if new_path and new_path != old_path:
                all_cards[idx][f"{face}_text"] = None
            else:
                all_cards[idx][f"{face}_text"] = form_text(f"{face}_text") or None

            audio_upload = request.files.get(f"{face}_audio_upload")
            if audio_upload and audio_upload.filename:
                all_cards[idx][f"{face}_audio"] = save_uploaded_audio(audio_upload)

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
        recto_text = form_text("recto_text")

        verso_upload = request.files.get("verso_upload")
        verso_text = form_text("verso_text")
        recto_audio_upload = request.files.get("recto_audio_upload")
        verso_audio_upload = request.files.get("verso_audio_upload")

        recto_path = recto_text_val = verso_path = verso_text_val = None
        recto_audio = verso_audio = None

        if recto_upload and recto_upload.filename:
            recto_path = save_uploaded_image(recto_upload)
        else:
            recto_text_val = recto_text

        if verso_upload and verso_upload.filename:
            verso_path = save_uploaded_image(verso_upload)
        else:
            verso_text_val = verso_text

        if recto_audio_upload and recto_audio_upload.filename:
            recto_audio = save_uploaded_audio(recto_audio_upload)
        if verso_audio_upload and verso_audio_upload.filename:
            verso_audio = save_uploaded_audio(verso_audio_upload)

        if (recto_path or recto_text_val or recto_audio) and (verso_path or verso_text_val or verso_audio):
            with locked_flashcards() as all_cards:
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
            flash("Carte ajoutée !", "success")
            return redirect(url_for("create"))
        else:
            flash("Le recto et le verso doivent avoir un contenu.", "error")

    return render_template("create.html", title="Créer", active="create", body_class="")

# ── Bulk create cards (paste JSON) ───────────────────────────────────────────

def _text_field(entry, key):
    """Validate + strip a text face value. Must be a string (or absent).
    Returns the stripped string, None if empty/absent. Raises ValueError on a
    non-string value so the all-or-nothing import reports it instead of silently
    coercing e.g. {"a": 1} into the literal text "{'a': 1}"."""
    val = entry.get(key)
    if val is None:
        return None
    if not isinstance(val, str):
        raise ValueError(f"{key} doit être une chaîne de caractères.")
    return capitalize_first(val.strip()) or None

def _local_image_path(key, raw):
    """Resolve a user-supplied local image path to a stored "images/…" value.
    Accepts both "images/foo.png" and a bare "foo.png"; rejects anything that
    escapes IMAGE_DIR (absolute paths, "..", a path pointing elsewhere) so a
    hostile path can never be stored and later handed to delete_image_file().
    Requires an allowed image extension and that the file actually exists in the
    folder. Raises ValueError on any problem; otherwise returns the normalised
    "images/…" path."""
    rel = raw.replace("\\", "/").strip().lstrip("/")
    # Tolerate an explicit "<folder>/" prefix (the folder NAME, e.g. "images/")
    # as well as a bare filename. Match on the basename so it still works if
    # IMAGE_DIR is configured to an absolute or nested path.
    folder = os.path.basename(os.path.normpath(IMAGE_DIR)) or IMAGE_DIR
    if rel.lower().startswith(folder.lower() + "/"):
        rel = rel[len(folder) + 1:]
    if not rel:
        raise ValueError(f"{key} : chemin d'image vide.")
    ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise ValueError(f"{key} doit être une URL http(s) ou une image ({allowed}).")
    base = os.path.realpath(IMAGE_DIR)
    target = os.path.realpath(os.path.join(IMAGE_DIR, rel))
    if target == base or not target.startswith(base + os.sep):
        raise ValueError(f"{key} doit pointer vers le dossier « {IMAGE_DIR} ».")
    if not os.path.isfile(target):
        raise ValueError(f"{key} : fichier introuvable dans « {IMAGE_DIR} » ({rel}).")
    # Store the same forward-slash "images/…" form that create() produces.
    return f"{IMAGE_DIR}/{rel}"

def _image_path_field(entry, *keys):
    """Validate + strip an image-face value across alias keys.
    Accepts either an http(s) URL or a local path inside IMAGE_DIR (e.g.
    "images/foo.png" or "foo.png") — together these are the value domain the
    single-card create() route produces (a remote URL, or an uploaded file
    stored under IMAGE_DIR). Restricting to those two forms keeps a hostile or
    relative path (e.g. "flashcards.json" or "../secret") from ever being stored
    and later handed to delete_image_file(). Returns the first non-empty value
    (local paths normalised to "images/…"), or None."""
    for key in keys:
        val = entry.get(key)
        if val is None:
            continue
        if not isinstance(val, str):
            raise ValueError(f"{key} doit être une URL ou un chemin (chaîne de caractères).")
        s = val.strip()
        if not s:
            continue
        if s.lower().startswith(("http://", "https://")):
            return s
        return _local_image_path(key, s)
    return None

def _build_card(entry, creation_date, next_review_date):
    """Turn one import entry (dict) into a full card, or raise ValueError.

    Accepts recto_text/verso_text and, optionally, recto_path/verso_path
    (image URLs — recto_url/verso_url are accepted as aliases). When a face has
    both a path and text, the path wins and the text is dropped (mirrors create()).
    """
    if not isinstance(entry, dict):
        raise ValueError("ce n'est pas un objet JSON.")
    recto_text = _text_field(entry, "recto_text")
    verso_text = _text_field(entry, "verso_text")
    recto_path = _image_path_field(entry, "recto_path", "recto_url")
    verso_path = _image_path_field(entry, "verso_path", "verso_url")
    if recto_path:
        recto_text = None
    if verso_path:
        verso_text = None
    if not (recto_text or recto_path):
        raise ValueError("recto vide (recto_text ou recto_path requis).")
    if not (verso_text or verso_path):
        raise ValueError("verso vide (verso_text ou verso_path requis).")
    return {
        "box": 1,
        "creation_date": creation_date,
        "current_face": "recto",
        "id": str(uuid.uuid4()),
        "last_reviewed_date": None,
        "marked": False,
        "next_review_date": next_review_date,
        "recto_path": recto_path,
        "recto_text": recto_text,
        "recto_audio": None,
        "verso_path": verso_path,
        "verso_text": verso_text,
        "verso_audio": None,
    }

BULK_MAX_PER_DAY = 20   # cartes importées planifiées par jour (étalement du next_review_date)

@app.route("/create/bulk", methods=["GET", "POST"])
@login_required
def create_bulk():
    # Per-day spread cap (configurable via the form/query; falsy or <1 → default).
    per_day = request.values.get("max_per_day", BULK_MAX_PER_DAY, type=int) or BULK_MAX_PER_DAY
    per_day = max(1, per_day)

    def render(payload="", errors=None):
        return render_template("create_bulk.html", title="Import en masse",
                               active="create", body_class="",
                               payload=payload, errors=errors, max_per_day=per_day)

    if request.method == "GET":
        return render()

    # Strip surrounding whitespace and a UTF-8 BOM (str.strip() doesn't treat
    # as whitespace) so a .json saved by a Windows editor still parses instead of
    # failing json.loads. The extra .strip() handles a BOM-then-whitespace order.
    raw = request.form.get("payload", "").strip().lstrip("﻿").strip()
    if not raw:
        flash("Le champ est vide — collez votre JSON.", "error")
        return render(payload=raw)

    # Parse JSON, tolerating a double-encoded payload ("[ ... ]" pasted as a string).
    try:
        data = json.loads(raw)
        if isinstance(data, str):
            data = json.loads(data)
    except json.JSONDecodeError as e:
        flash(f"JSON invalide : {e}", "error")
        return render(payload=raw)

    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        flash("Le JSON doit être une liste d'objets (ou un objet unique).", "error")
        return render(payload=raw)
    if not data:
        flash("La liste est vide — aucune carte à importer.", "error")
        return render(payload=raw)

    # Save any dropped images first, under their original name, so local JSON
    # paths ("images/chat.png" or "chat.png") resolve during validation below.
    # `created` tracks files new to this request so a failed (all-or-nothing)
    # import can roll them back without touching images already on disk.
    created, skipped = save_bulk_images(request.files.getlist("images"))

    # All-or-nothing: validate everything first so nothing is silently dropped.
    now = datetime.now()
    creation_date = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    new_cards = []
    errors = []
    for i, entry in enumerate(data, start=1):
        try:
            new_cards.append(_build_card(entry, creation_date, tomorrow))
        except ValueError as e:
            errors.append(f"Entrée {i} : {e}")

    if errors:
        # Roll back images this request created so a rejected import leaves no trace.
        for p in created:
            try:
                os.remove(p)
            except OSError:
                pass
        flash(f"❌ Aucune carte importée — {len(errors)} entrée(s) invalide(s). Corrigez puis réessayez.", "error")
        if skipped:
            flash(f"⚠️ {len(skipped)} fichier(s) ignoré(s) (format non supporté).", "warning")
        return render(payload=raw, errors=errors)

    # Spread the first review: at most `per_day` imported cards land on the same
    # day, starting tomorrow, keeping the pasted order. Avoids dumping a whole
    # batch onto a single review day.
    for idx, card in enumerate(new_cards):
        day_offset = 1 + idx // per_day
        card["next_review_date"] = (now + timedelta(days=day_offset)).strftime("%Y-%m-%d")

    with locked_flashcards() as all_cards:
        all_cards.extend(new_cards)

    days = (len(new_cards) - 1) // per_day + 1
    img_note = f" {len(created)} image(s) enregistrée(s)." if created else ""
    if days > 1:
        flash(f"✅ {len(new_cards)} carte(s) ajoutée(s), étalées sur {days} jours "
              f"(max {per_day}/jour, à partir de demain).{img_note}", "success")
    else:
        flash(f"✅ {len(new_cards)} carte(s) ajoutée(s) !{img_note}", "success")
    if skipped:
        flash(f"⚠️ {len(skipped)} fichier(s) ignoré(s) (format non supporté).", "warning")
    return redirect(url_for("create_bulk"))

# ── Dashboard ────────────────────────────────────────────────────────────────

@app.route("/dashboard")
@login_required
def dashboard():
    cards = load_flashcards()
    total = len(cards)
    if total == 0:
        return render_template("dashboard.html", title="Dashboard", active="dashboard", body_class="",
                               total=0, median_interval=0, long_term_ratio=0,
                               box_data=[], timeline_data=[], workload_data=[],
                               activity_data=[], stage_data=[],
                               creation_heatmap=[], rs={"total": 0}, leech_count=0,
                               forecast={"overdue": 0, "days": [], "steady": 0, "horizon": 0},
                               progression={"cloud": [], "ideal": [], "max_age": 0, "max_n": 1},
                               retention=[], review_calendar=[],
                               box_threshold=BOX_LINEAR_UNTIL)

    intervals = sorted(box_interval(c.get("box", 1)) for c in cards)
    median_interval = intervals[len(intervals) // 2]
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

    # Répartition par intervalle plutôt que par numéro de boîte : depuis que la
    # loi accélère au-delà du seuil, une boîte ne dit plus à elle seule combien
    # de temps une carte tient. Les anciennes tranches étaient d'ailleurs calées
    # sur une échelle de 60 boîtes dont la dernière ne se remplissait jamais.
    STAGE_BANDS = [("Moins d'une semaine", 0, 6), ("1 à 4 semaines", 7, 29),
                   ("1 à 2 mois", 30, 59), ("2 mois et plus", 60, 10**9)]
    card_intervals = [box_interval(c.get("box", 1)) for c in cards]
    # Une LISTE de paires, pas un dict : le filtre tojson de Flask trie les clés
    # d'un dictionnaire, ce qui rendait les tranches dans l'ordre alphabétique
    # au lieu de l'ordre croissant des intervalles.
    stage_data = [[label, sum(1 for iv in card_intervals if lo <= iv <= hi)]
                  for label, lo, hi in STAGE_BANDS]

    return render_template(
        "dashboard.html", title="Dashboard", active="dashboard", body_class="",
        total=total, median_interval=median_interval, long_term_ratio=long_term_ratio,
        box_data=box_data, timeline_data=cumulative, workload_data=workload,
        activity_data=activity_data, stage_data=stage_data,
        creation_heatmap=creation_heatmap,
        rs=review_stats(), leech_count=len(get_leech_cards(cards)),
        forecast=forecast_data(90, cards),
        progression=progression_cloud(cards),
        retention=retention_by_interval(),
        review_calendar=review_heatmap(),
        box_threshold=BOX_LINEAR_UNTIL,
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
    truncated = len(cards) > 100
    return jsonify({"cards": cards[:100], "truncated": truncated, "total": len(cards)})

@app.route("/api/advance_count")
@login_required
def api_advance_count():
    """Compteur live pour les réglages d'anticipation de la page d'accueil.
    `upcoming` = tout ce qui arrive à échéance dans la fenêtre, toutes boîtes
    confondues, pour montrer ce que le filtre laisse de côté."""
    days, min_box = advance_params()
    all_cards = load_flashcards()
    return jsonify({
        "count": len(get_advance_review_cards(days, min_box, all_cards)),
        "upcoming": len(get_advance_review_cards(days, 1, all_cards)),
        "days": days,
        "min_box": min_box,
    })

# ── Palette des préfixes emoji ───────────────────────────────────────────────
# L'éditeur vit dans le formulaire de création : il parle en JSON pour ne pas
# soumettre la carte en cours de saisie. Chaque réponse renvoie la palette
# complète, que le client redessine — inutile de deviner l'état côté navigateur.

def _emoji_payload(items, message=None):
    payload = {"prefixes": items, "max": EMOJI_MAX_PREFIXES}
    if message:
        payload["message"] = message
    return jsonify(payload)


@app.route("/api/emoji_prefixes")
@login_required
def api_emoji_prefixes():
    return _emoji_payload(load_emoji_prefixes())


@app.route("/api/emoji_prefixes", methods=["POST"])
@login_required
def api_emoji_prefixes_update():
    data = request.get_json(silent=True) or {}
    action = data.get("action")

    if action == "reset":
        with locked_emoji_prefixes() as items:
            items[:] = [dict(item) for item in DEFAULT_EMOJI_PREFIXES]
            saved = list(items)
        return _emoji_payload(saved, "Palette réinitialisée.")

    if action == "add":
        try:
            new_item = clean_emoji_prefix(data)
        except EmojiPrefixError as exc:
            return jsonify({"error": str(exc)}), 400
        # Le refus se décide sous verrou mais se renvoie après : sortir du bloc
        # par un return réécrirait le fichier pour rien.
        error = None
        with locked_emoji_prefixes() as items:
            if len(items) >= EMOJI_MAX_PREFIXES:
                error = "Palette pleine (%d pastilles)." % EMOJI_MAX_PREFIXES
            elif any(i["recto"] == new_item["recto"] and i["verso"] == new_item["verso"] for i in items):
                error = "Cette pastille existe déjà."
            else:
                items.append(new_item)
            saved = list(items)
        if error:
            return jsonify({"error": error}), 400
        return _emoji_payload(saved, "Pastille ajoutée.")

    if action == "delete":
        recto = (data.get("recto") or "").strip()
        verso = (data.get("verso") or "").strip() or recto
        found = False
        with locked_emoji_prefixes() as items:
            kept = [i for i in items if not (i["recto"] == recto and i["verso"] == verso)]
            found = len(kept) != len(items)
            items[:] = kept
            saved = list(items)
        if not found:
            return jsonify({"error": "Pastille introuvable."}), 404
        return _emoji_payload(saved, "Pastille supprimée.")

    return jsonify({"error": "Action inconnue."}), 400


# ── Backups ──────────────────────────────────────────────────────────────────

@app.route("/backups")
@login_required
def backups():
    current = None
    if os.path.exists(CARDS_FILE):
        current = {"count": len(load_flashcards()),
                   "size_kb": round(os.path.getsize(CARDS_FILE) / 1024, 1)}
    return render_template("backups.html", title="Sauvegardes", active="backups", body_class="",
                           backups=list_backups(), max_backups=MAX_BACKUPS, current=current,
                           media=media_stats())

MEDIA_DIRS = (IMAGE_DIR, AUDIO_DIR)

def human_size(num_bytes):
    """Taille lisible : « 812 Ko », « 4,3 Mo »."""
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f}".replace(".", ",") + " Mo"
    return f"{max(num_bytes / 1024, 0.1):.1f}".replace(".", ",") + " Ko"

def media_stats():
    """Nombre de fichiers et octets cumulés dans images/ et audios/."""
    files = total = 0
    for folder in MEDIA_DIRS:
        for root, _dirs, names in os.walk(folder):
            for name in names:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    continue
                files += 1
    return {"files": files, "size_label": human_size(total)}

def add_dir_to_zip(zf, folder):
    """Ajoute un dossier au ZIP en conservant son nom (« images/photo.png »).
    Les médias sont déjà compressés (JPEG, PNG, MP3) : on les stocke tels quels
    plutôt que de payer un deflate qui ne gagnerait presque rien."""
    if not os.path.isdir(folder):
        return
    parent = os.path.dirname(os.path.abspath(folder))
    for root, _dirs, names in os.walk(folder):
        for name in sorted(names):
            full = os.path.join(root, name)
            arcname = os.path.relpath(full, parent)
            try:
                zf.write(full, arcname, compress_type=zipfile.ZIP_STORED)
            except OSError:
                continue  # fichier disparu ou illisible entre-temps

def remove_quietly(path):
    """Supprime un fichier sans lever ; renvoie True si c'est fait."""
    try:
        os.remove(path)
        return True
    except OSError:
        return False

@app.route("/export")
@login_required
def export_cards():
    """Télécharge flashcards.json tel quel, sous un nom horodaté."""
    path = os.path.abspath(CARDS_FILE)
    if not os.path.exists(path):
        flash("Aucun fichier de cartes à exporter.", "error")
        return redirect(url_for("backups"))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(path, mimetype="application/json", as_attachment=True,
                     download_name=f"flashcards_{ts}.json", max_age=0)

@app.route("/export/zip")
@login_required
def export_archive():
    """Archive autonome : les cartes plus toutes les images et tous les audios."""
    if not os.path.exists(CARDS_FILE):
        flash("Aucun fichier de cartes à exporter.", "error")
        return redirect(url_for("backups"))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Sur disque plutôt qu'en mémoire : l'archive peut peser plusieurs dizaines
    # de Mo une fois les médias inclus.
    fd, tmp_path = tempfile.mkstemp(prefix="flashcards_export_", suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(os.path.abspath(CARDS_FILE), os.path.basename(CARDS_FILE))
            for folder in MEDIA_DIRS:
                add_dir_to_zip(zf, folder)
        stream = open(tmp_path, "rb")
    except Exception as e:
        remove_quietly(tmp_path)
        flash(f"Erreur lors de la création de l'archive : {e}", "error")
        return redirect(url_for("backups"))
    # Délié aussitôt : sous Unix le flux reste lisible et l'espace est rendu à
    # la fermeture, donc aucune archive orpheline même si la requête échoue en
    # cours de route. Sous Windows la suppression n'est possible qu'après coup.
    deleted = remove_quietly(tmp_path)
    response = send_file(stream, mimetype="application/zip", as_attachment=True,
                         download_name=f"flashcards_{ts}.zip", max_age=0)
    if not deleted:
        response.call_on_close(lambda: remove_quietly(tmp_path))
    return response

@app.route("/backups/download/<filename>")
@login_required
def backup_download(filename):
    if not valid_backup_name(filename):
        flash("Fichier invalide.", "error")
        return redirect(url_for("backups"))
    path = os.path.join(BACKUP_DIR, filename)
    if not os.path.exists(path):
        flash("Sauvegarde introuvable.", "error")
        return redirect(url_for("backups"))
    return send_file(os.path.abspath(path), mimetype="application/json",
                     as_attachment=True, download_name=filename, max_age=0)

@app.route("/backups/restore/<filename>", methods=["POST"])
@login_required
def backup_restore(filename):
    if not valid_backup_name(filename):
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
    if not valid_backup_name(filename):
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

# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)