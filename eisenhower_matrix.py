import streamlit as st
import json
import os

# Nom du fichier pour sauvegarder les tâches
EISENHOWER_FILE = "eisenhower_tasks.json"

def load_tasks():
    """Charge les tâches depuis le fichier JSON."""
    if not os.path.exists(EISENHOWER_FILE):
        # Si le fichier n'existe pas, retourne une structure par défaut
        return {
            "urgent_important": "",
            "important_not_urgent": "",
            "urgent_not_important": "",
            "not_urgent_not_important": ""
        }
    try:
        with open(EISENHOWER_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_tasks(tasks):
    """Sauvegarde les tâches dans le fichier JSON."""
    with open(EISENHOWER_FILE, 'w', encoding='utf-8') as f:
        json.dump(tasks, f, indent=4, ensure_ascii=False)

def display_eisenhower_matrix():
    """Affiche l'interface de la Matrice d'Eisenhower."""
    st.header("⌚ Matrice d'Eisenhower")
    st.markdown("Organisez vos tâches en fonction de leur urgence et de leur importance.")
    
    # Charger les tâches existantes
    tasks = load_tasks()

    # Créer les quatre quadrants
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("✅ Urgent et Important")
        tasks["urgent_important"] = st.text_area(
            "Tâches à faire immédiatement :", 
            value=tasks.get("urgent_important", ""), 
            height=200,
            key="q1"
        )
        
        st.subheader("❤️ Urgent mais pas important")
        tasks["urgent_not_important"] = st.text_area(
            "Tâches à déléguer :", 
            value=tasks.get("urgent_not_important", ""), 
            height=200,
            key="q3"
        )

    with col2:
        st.subheader("🙏 Important mais non urgent")
        tasks["important_not_urgent"] = st.text_area(
            "Tâches à planifier :", 
            value=tasks.get("important_not_urgent", ""), 
            height=200,
            key="q2"
        )
        
        st.subheader("🗑️ Ni urgent, ni important")
        tasks["not_urgent_not_important"] = st.text_area(
            "Tâches à abandonner :", 
            value=tasks.get("not_urgent_not_important", ""), 
            height=200,
            key="q4"
        )
    
    st.markdown("---")
    
    # Bouton pour sauvegarder les modifications
    if st.button("Sauvegarder les tâches", use_container_width=True, type="primary"):
        save_tasks(tasks)
        st.toast("Matrice sauvegardée avec succès !", icon="✅")

