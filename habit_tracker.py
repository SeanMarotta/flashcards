import streamlit as st
import calendar
import datetime
import json
from pathlib import Path
import pandas as pd
import altair as alt

# --- Configuration (Habit Tracker) ---
HABITS_TRACKER_FILE = Path("habits_data.json")
HABITS_LIST = ["💼 Compétence professionnelle", "📚 Connaissance générales", "🎨 Créativité", "🏃 Activité sportive"]
DAILY_METRICS_KEY = "_daily_metrics"

# --- Fonctions de gestion des données (Habit Tracker) ---
def load_habits_data():
    """Charge les données des habitudes depuis le fichier JSON."""
    if HABITS_TRACKER_FILE.exists():
        with open(HABITS_TRACKER_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_habits_data(data):
    """Sauvegarde les données des habitudes dans le fichier JSON."""
    with open(HABITS_TRACKER_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

# --- Fonction principale d'affichage (Habit Tracker) ---
def display_habit_tracker():
    """
    Fonction principale qui affiche toute la page du Habit Tracker.
    Elle est appelée depuis app.py.
    """
    st.header("📅 Mon Suivi d'Habitudes & Bilan Journalier")
    if 'habits_data' not in st.session_state:
        st.session_state.habits_data = load_habits_data()

    col1, col2, _ = st.columns([2, 2, 8])
    current_year = datetime.datetime.today().year
    year_options = list(range(current_year - 2, current_year + 3))
    selected_year = col1.selectbox("Année", options=year_options, index=year_options.index(current_year), key="habits_year")
    months_fr = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
    default_month_index = datetime.datetime.today().month - 1
    selected_month_name = col2.selectbox("Mois", options=months_fr, index=default_month_index, key="habits_month")
    selected_month = months_fr.index(selected_month_name) + 1
    
    st.divider()
    st.header("📝 Bilan Journalier")
    selected_date = st.date_input("Choisissez une date pour enregistrer votre bilan", value=datetime.date.today(), min_value=datetime.date(year_options[0], 1, 1), max_value=datetime.date.today(), format="DD/MM/YYYY")
    selected_date_str = selected_date.isoformat()
    selected_day_metrics = st.session_state.habits_data.get(DAILY_METRICS_KEY, {}).get(selected_date_str, {})
    sommeil = selected_day_metrics.get("sommeil", 5)
    reveil = selected_day_metrics.get("reveil", 5)
    motivation = selected_day_metrics.get("motivation", 5)
    attention = selected_day_metrics.get("attention", 5)
    productivite = selected_day_metrics.get("productivite", 5)
    
    m_col1, m_col2, m_col3 = st.columns(3)
    new_sommeil = m_col1.slider(f"😴 Sommeil du {selected_date.strftime('%d/%m')}", 1, 10, sommeil, key=f"sommeil_{selected_date_str}")
    new_reveil = m_col2.slider(f"⏰ Réveil du {selected_date.strftime('%d/%m')}", 1, 10, reveil, key=f"reveil_{selected_date_str}")
    new_motivation = m_col3.slider(f"⚡ Motivation du {selected_date.strftime('%d/%m')}", 1, 10, motivation, key=f"motivation_{selected_date_str}")
    m_col4, m_col5, _ = st.columns([1, 1, 1])
    new_attention = m_col4.slider(f"🎯 Attention du {selected_date.strftime('%d/%m')}", 1, 10, attention, key=f"attention_{selected_date_str}")
    new_productivite = m_col5.slider(f"🚀 Productivité du {selected_date.strftime('%d/%m')}", 1, 10, productivite, key=f"productivite_{selected_date_str}")
    
    if st.button(f"Sauvegarder le bilan pour le {selected_date.strftime('%d %B %Y')}"):
        if DAILY_METRICS_KEY not in st.session_state.habits_data: st.session_state.habits_data[DAILY_METRICS_KEY] = {}
        st.session_state.habits_data[DAILY_METRICS_KEY][selected_date_str] = {"sommeil": new_sommeil, "reveil": new_reveil, "motivation": new_motivation, "attention": new_attention, "productivite": new_productivite}
        save_habits_data(st.session_state.habits_data)
        st.success(f"Bilan pour le {selected_date.strftime('%d/%m/%Y')} enregistré !"); st.rerun()
    
    st.divider()
    st.header("🎯 Suivi des Habitudes")
    for habit in HABITS_LIST:
        st.subheader(habit)
        cal = calendar.monthcalendar(selected_year, selected_month)
        days_of_week = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        cols_h = st.columns(7)
        for i, day_name in enumerate(days_of_week): cols_h[i].write(f"**{day_name}**")
        for week in cal:
            cols_h = st.columns(7)
            for i, day in enumerate(week):
                if day != 0:
                    date_key = f"{selected_year}-{selected_month:02d}-{day:02d}"
                    checkbox_key = f"{habit}-{date_key}"
                    is_checked = st.session_state.habits_data.get(habit, {}).get(date_key, False)
                    with cols_h[i]: new_status = st.checkbox(str(day), value=is_checked, key=checkbox_key)
                    if new_status != is_checked:
                        if habit not in st.session_state.habits_data: st.session_state.habits_data[habit] = {}
                        st.session_state.habits_data[habit][date_key] = new_status
                        save_habits_data(st.session_state.habits_data)
                        st.rerun()
    
    st.divider()
    st.header("📊 Statistiques du mois")
    num_days_in_month = calendar.monthrange(selected_year, selected_month)[1]
    for habit in HABITS_LIST:
        completed_days = 0
        habit_data = st.session_state.habits_data.get(habit, {})
        for day in range(1, num_days_in_month + 1):
            date_key = f"{selected_year}-{selected_month:02d}-{day:02d}"
            if habit_data.get(date_key, False): completed_days += 1
        completion_rate = (completed_days / num_days_in_month) * 100
        st.write(f"**{habit}**"); st.progress(int(completion_rate), text=f"{completed_days} / {num_days_in_month} jours ({completion_rate:.0f}%)")
    
    st.divider()
    st.header("📈 Graphique du Bilan Mensuel")
    monthly_metrics_data = st.session_state.habits_data.get(DAILY_METRICS_KEY, {})
    data_for_chart = []
    for date_str, metrics in monthly_metrics_data.items():
        if date_str.startswith(f"{selected_year}-{selected_month:02d}"):
            for metric_name, value in metrics.items():
                data_for_chart.append({"Date": pd.to_datetime(date_str), "Métrique": metric_name.capitalize(), "Note": value})
    if not data_for_chart:
        st.info("Aucune donnée de bilan journalier n'a été enregistrée pour ce mois.")
    else:
        df = pd.DataFrame(data_for_chart)
        chart = alt.Chart(df).mark_line(point=True).encode(x=alt.X('Date:T', title='Jour du mois'), y=alt.Y('Note:Q', title='Note', scale=alt.Scale(domain=[0, 10])), color=alt.Color('Métrique:N', title='Métrique'), tooltip=['Date', 'Métrique', 'Note'])
        st.altair_chart(chart, use_container_width=True)
