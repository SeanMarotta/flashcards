import streamlit as st
import json
import os

# La classe Carte et les fonctions de sauvegarde/chargement ne changent pas.
class Carte:
    def __init__(self, recto: str, verso: str, index: int):
        self.recto = recto
        self.verso = verso
        self.index = index
        self.is_recto_visible = True

    def __repr__(self):
        face = "Recto" if self.is_recto_visible else "Verso"
        return f"Carte('{self.recto}', index={self.index}, face='{face}')"

    def flip(self):
        self.is_recto_visible = not self.is_recto_visible

    def forward(self, main_list: list):
        if self.index < 60:
            main_list[self.index].remove(self)
            self.index += 1
            main_list[self.index].append(self)
            self.flip()

    def backward(self, main_list: list):
        if self.index > 1:
            main_list[self.index].remove(self)
            self.index -= 1
            main_list[self.index].append(self)
            self.flip()

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
                    carte = Carte(recto=card_dict.get('recto'), verso=card_dict.get('verso'), index=card_dict.get('index'))
                    carte.is_recto_visible = card_dict.get('is_recto_visible', True)
                    main_list_loaded[i].append(carte)
        return main_list_loaded

st.title("Mon Système de Flashcards")
if 'main_list' not in st.session_state:
    st.session_state.main_list = load_data()
    if not any(st.session_state.main_list):
         st.session_state.main_list[1].append(Carte("Capitale de la France ?", "Paris", 1))
         save_data(st.session_state.main_list)

# Les sections de création de carte et de révision ne changent pas.
with st.expander("➡️ Ajouter une nouvelle carte"):
    # ... (code du formulaire inchangé) ...
    with st.form("new_card_form", clear_on_submit=True):
        recto_content = st.text_area("Recto (la question)")
        verso_content = st.text_area("Verso (la réponse)")
        box_number = st.number_input("Dans quelle boîte la placer ?", min_value=1, max_value=60, step=1)
        submitted = st.form_submit_button("Créer la carte")
    if submitted and recto_content and verso_content:
        nouvelle_carte = Carte(recto_content, verso_content, box_number)
        st.session_state.main_list[box_number].append(nouvelle_carte)
        save_data(st.session_state.main_list)
        st.success(f"Carte ajoutée dans la boîte n°{box_number} !")

st.header("🧠 Session de Révision")
# ... (code de la session de révision inchangé) ...
boites_non_vides_revision = [i for i, box in enumerate(st.session_state.main_list) if i > 0 and box]
if not boites_non_vides_revision:
    st.info("Aucune carte à réviser. Ajoutez-en une dans le menu ci-dessus !")
else:
    boites_a_reviser = st.multiselect("Choisissez les boîtes que vous voulez réviser aujourd'hui :", options=boites_non_vides_revision)
    if boites_a_reviser:
        # ... (logique de révision inchangée) ...
        for box_num in boites_a_reviser:
            st.subheader(f"--- Boîte n°{box_num} ---")
            for carte in list(st.session_state.main_list[box_num]):
                with st.container(border=True):
                    if carte.is_recto_visible:
                        question, reponse = carte.recto, carte.verso
                    else:
                        question, reponse = carte.verso, carte.recto
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

# --- AJOUT : Section de gestion des cartes ---
st.header("⚙️ Gérer les Cartes")
boites_non_vides_gestion = [i for i, box in enumerate(st.session_state.main_list) if i > 0 and box]

if not boites_non_vides_gestion:
    st.info("Aucune carte à gérer.")
else:
    for box_index, box_content in enumerate(st.session_state.main_list):
        if box_index > 0 and box_content:
            st.subheader(f"--------- Boîte n°{box_index} ---------")
            # On parcourt chaque carte pour l'afficher avec ses boutons de gestion
            for card_index, carte in enumerate(box_content):
                col1, col2, col3 = st.columns([0.6, 0.2, 0.2])
                with col1:
                    st.markdown(f"**{carte.recto}** *({carte.verso})*")
                
                # --- AJOUT : Bouton de modification ---
                with col2:
                    # Le popover est une petite fenêtre qui s'ouvre au clic
                    with st.popover("Modifier"):
                        # On utilise un formulaire pour l'édition
                        with st.form(f"edit_form_{box_index}_{card_index}"):
                            st.write(f"Modification de la carte : {carte.recto}")
                            new_recto = st.text_input("Recto", value=carte.recto)
                            new_verso = st.text_area("Verso", value=carte.verso)
                            new_box = st.number_input("Boîte", min_value=1, max_value=60, value=carte.index)
                            
                            if st.form_submit_button("Enregistrer"):
                                # Mettre à jour la carte
                                carte.recto = new_recto
                                carte.verso = new_verso
                                
                                # Si la boîte a changé, déplacer la carte
                                if new_box != carte.index:
                                    st.session_state.main_list[carte.index].remove(carte)
                                    st.session_state.main_list[new_box].append(carte)
                                    carte.index = new_box
                                
                                save_data(st.session_state.main_list)
                                st.success("Carte modifiée !")
                                st.rerun()

                # --- AJOUT : Bouton de suppression ---
                with col3:
                    if st.button("🗑️ Supprimer", key=f"delete_{box_index}_{card_index}", type="primary"):
                        # On supprime la carte de la liste
                        st.session_state.main_list[box_index].pop(card_index)
                        save_data(st.session_state.main_list)
                        st.warning(f"Carte '{carte.recto}' supprimée.")
                        st.rerun()