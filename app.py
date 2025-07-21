import streamlit as st
import json
import os

# --- Définition de la classe Carte (avec la logique de retournement) ---
class Carte:
    def __init__(self, recto: str, verso: str, index: int):
        self.recto = recto
        self.verso = verso
        self.index = index
        self.is_recto_visible = True # CHANGEMENT: La carte commence toujours côté recto

    # CHANGEMENT: Affiche la carte de manière plus détaillée pour le débogage
    def __repr__(self):
        face = "Recto" if self.is_recto_visible else "Verso"
        return f"Carte('{self.recto}', index={self.index}, face='{face}')"

    # CHANGEMENT: Nouvelle méthode pour retourner la carte
    def flip(self):
        """Retourne la carte en changeant le côté visible."""
        self.is_recto_visible = not self.is_recto_visible

    def forward(self, main_list: list):
        """Déplace la carte et la retourne."""
        if self.index < 60:
            main_list[self.index].remove(self)
            self.index += 1
            main_list[self.index].append(self)
            self.flip() # CHANGEMENT: On retourne la carte

    def backward(self, main_list: list):
        """Renvoie la carte à la boîte n°1 et la retourne."""
        if self.index > 1:
            main_list[self.index].remove(self)
        
        self.index = 1
        if self not in main_list[1]:
            main_list[1].append(self)
        
        self.flip() # CHANGEMENT: On retourne la carte

# (Le reste du code pour save_data et load_data ne change pas)
SAVE_FILE = "flashcards.json"

def save_data(main_list):
    data_to_save = []
    for box in main_list:
        data_to_save.append([vars(carte) for carte in box])
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump(data_to_save, f, indent=4)

def load_data():
    if not os.path.exists(SAVE_FILE):
        return [[] for _ in range(61)]
    with open(SAVE_FILE, "r", encoding="utf-8") as f:
        data_from_file = json.load(f)
        main_list_loaded = [[] for _ in range(61)]
        for i, box in enumerate(data_from_file):
            if i > 0:
                for card_dict in box:
                    # On crée la carte et on ajuste son état si nécessaire
                    carte = Carte(recto=card_dict.get('recto'), verso=card_dict.get('verso'), index=card_dict.get('index'))
                    carte.is_recto_visible = card_dict.get('is_recto_visible', True) # Assure la compatibilité
                    main_list_loaded[i].append(carte)
        return main_list_loaded

# --- Initialisation de l'application ---
st.title("Mon Système de Flashcards")
if 'main_list' not in st.session_state:
    st.session_state.main_list = load_data()
    if not any(st.session_state.main_list):
         st.session_state.main_list[1].append(Carte("Capitale de la France ?", "Paris", 1))
         st.session_state.main_list[1].append(Carte("2 + 2 ?", "4", 1))
         save_data(st.session_state.main_list)

# --- Section 1: Création de carte ---
# (Aucun changement dans cette section)
with st.expander("➡️ Ajouter une nouvelle carte"):
    # ... (code du formulaire inchangé) ...
    with st.form("new_card_form", clear_on_submit=True):
        recto_content = st.text_input("Recto (la question)")
        verso_content = st.text_area("Verso (la réponse)")
        box_number = st.number_input("Dans quelle boîte la placer ?", min_value=1, max_value=60, step=1)
        submitted = st.form_submit_button("Créer la carte")

    if submitted and recto_content and verso_content:
        nouvelle_carte = Carte(recto_content, verso_content, box_number)
        st.session_state.main_list[box_number].append(nouvelle_carte)
        save_data(st.session_state.main_list)
        st.success(f"Carte ajoutée dans la boîte n°{box_number} !")


# --- Section 2: Sélection et Révision ---
st.header("🧠 Session de Révision")
boites_non_vides = [i for i, box in enumerate(st.session_state.main_list) if i > 0 and box]

if not boites_non_vides:
    st.info("Aucune carte à réviser. Ajoutez-en une dans le menu ci-dessus !")
else:
    boites_a_reviser = st.multiselect("Choisissez les boîtes que vous voulez réviser aujourd'hui :", options=boites_non_vides)
    if boites_a_reviser:
        for box_num in boites_a_reviser:
            st.subheader(f"--- Boîte n°{box_num} ---")
            for carte in list(st.session_state.main_list[box_num]):
                with st.container(border=True):
                    # CHANGEMENT: On affiche la question ou la réponse en fonction du côté visible
                    if carte.is_recto_visible:
                        question = carte.recto
                        reponse = carte.verso
                    else:
                        question = carte.verso
                        reponse = carte.recto

                    st.markdown(f"**Question :** {question}")
                    carte_id = id(carte)
                    if st.button("Révéler la réponse", key=f"reveal_{carte_id}"):
                        st.session_state[f"answer_visible_{carte_id}"] = True
                    if st.session_state.get(f"answer_visible_{carte_id}", False):
                        st.markdown(f"**Réponse :** *{reponse}*")
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button("✅ Correct", key=f"correct_{carte_id}", use_container_width=True):
                                carte.forward(st.session_state.main_list)
                                save_data(st.session_state.main_list)
                                st.session_state[f"answer_visible_{carte_id}"] = False
                                st.rerun()
                        with col2:
                            if st.button("❌ Incorrect", key=f"incorrect_{carte_id}", use_container_width=True):
                                carte.backward(st.session_state.main_list)
                                save_data(st.session_state.main_list)
                                st.session_state[f"answer_visible_{carte_id}"] = False
                                st.rerun()

# --- Section 3: Vue d'ensemble ---
# (Aucun changement ici)
with st.expander("📦 Voir le contenu de toutes les boîtes"):
    st.json(st.session_state.main_list)