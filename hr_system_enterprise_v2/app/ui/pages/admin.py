import streamlit as st
from datetime import date, time
from ...common.utils import get_conn, query_df, log_action, now_iso, pbkdf2_hash, validate_password

def render(role):
    st.header("Admin Panel")
    # --- PRIVREMENI GUMB ZA GENERIRANJE ---
    from ...common.utils import seed_hotel_data # Importaj funkciju
    if st.button("⚠️ GENERIRAJ HOTEL DEMO PODATKE (Za prikaz)", type="primary"):
        seed_hotel_data()
        st.success("Baza je napunjena podacima za Veliki Hotel!")
        st.rerun()
    # ---------------------------------------
    
    if role != "admin":
        st.error("Pristup dozvoljen samo za ulogu 'admin'.")
        return

    admin_tabs = st.tabs([
        "Podaci o Tvrtki", 
        "Upravljanje Korisnicima", 
        "Upravljanje Sektorima", 
        "Upravljanje Pozicijama", 
        "Upravljanje Smjenama"
    ])
    
    conn = get_conn()
    cur = conn.cursor()
    
    
    # --- TAB 1: Podaci o Tvrtki ---
    with admin_tabs[0]:
        st.subheader("Podaci o Tvrtki")
        st.info("Ovi podaci se koriste globalno, npr. kod generiranja ugovora.")
        
        conf_data = query_df("SELECT key, prompt_template FROM ai_config WHERE key LIKE 'company_%'")
        company_info = {row['key']: row['prompt_template'] for _, row in conf_data.iterrows()}

        with st.form("form_company_info"):
            comp_name = st.text_input("Puni naziv tvrtke", value=company_info.get('company_name', ''))
            comp_oib = st.text_input("OIB tvrtke", value=company_info.get('company_oib', ''))
            comp_address = st.text_input("Adresa tvrtke", value=company_info.get('company_address', ''))
            
            if st.form_submit_button("Spremi Podatke o Tvrtki"):
                try:
                    cur.execute("INSERT OR REPLACE INTO ai_config (key, prompt_template, updated_at) VALUES (?, ?, ?)", ('company_name', comp_name, now_iso()))
                    cur.execute("INSERT OR REPLACE INTO ai_config (key, prompt_template, updated_at) VALUES (?, ?, ?)", ('company_oib', comp_oib, now_iso()))
                    cur.execute("INSERT OR REPLACE INTO ai_config (key, prompt_template, updated_at) VALUES (?, ?, ?)", ('company_address', comp_address, now_iso()))
                    conn.commit()
                    st.success("Podaci o tvrtki spremljeni.")
                    log_action(st.session_state.user["username"], "update_company_info")
                except Exception as e:
                    st.error(f"Greška: {e}")

    # --- TAB 2: Korisnici ---
    with admin_tabs[1]:
        st.subheader("Upravljanje Korisnicima")
        df_users = query_df("SELECT id, username, role, radnik_id, created_at FROM users")
        st.dataframe(df_users, use_container_width=True)
        
        with st.expander("Kreiraj novog korisnika"):
            with st.form("form_create_user"):
                uname = st.text_input("Korisničko ime")
                pwd = st.text_input("Lozinka (min. 8 znakova)", type="password")
                role_user = st.selectbox("Uloga", ["admin","manager","employee"], key="create_user_role")
                
                radnici_df = query_df("""
                    SELECT r.id, r.ime, r.prezime, s.naziv as sektor 
                    FROM radnici r 
                    LEFT JOIN sektor s ON r.sektor_id = s.id
                    WHERE r.id NOT IN (SELECT radnik_id FROM users WHERE radnik_id IS NOT NULL)
                """)
                
                radnici_options = {f"{r['prezime']} {r['ime']} ({r['sektor'] or 'Nema sektora'})": r['id'] for _, r in radnici_df.iterrows()}
                radnik_selection = st.selectbox("Poveži s Radnikom (Obavezno)", options=[""] + list(radnici_options.keys()), key="admin_reg_radnik")
                
                if st.form_submit_button("Kreiraj"):
                    radnik_id_to_insert = radnici_options.get(radnik_selection)
                    if not radnik_id_to_insert:
                        st.error("Povezivanje s radnikom je obavezno.")
                    elif not validate_password(pwd):
                        st.error("Lozinka mora imati barem 8 znakova.")
                    elif not uname:
                        st.error("Korisničko ime je obavezno.")
                    else:
                        cur.execute("SELECT id FROM users WHERE username=?", (uname,))
                        if cur.fetchone():
                            st.error("Korisničko ime već postoji.")
                        else:
                            cur.execute("INSERT INTO users (username,password_hash,role,created_at,radnik_id) VALUES (?,?,?,?,?)", 
                                      (uname, pbkdf2_hash(pwd), role_user, now_iso(), radnik_id_to_insert))
                            conn.commit()
                            st.success("Korisnik kreiran.")
                            log_action(st.session_state.user["username"], "admin_create_user", {"username": uname})
                            st.rerun()

        st.markdown("---")
        st.subheader("Uredi / Obriši Korisnika")
        user_options = {f"ID: {r['id']} ({r['username']} | {r['role']})": r['id'] for _, r in df_users.iterrows()}
        sel_id_user = st.selectbox("Odaberi korisnika", options=[""] + list(user_options.keys()), key="edit_user_select")
        
        if sel_id_user:
            sel_id_num_user = user_options[sel_id_user]
            user_data = conn.execute("SELECT * FROM users WHERE id=?", (sel_id_num_user,)).fetchone()
            
            with st.form("form_edit_user"):
                username = st.text_input("Korisničko ime", value=user_data['username'])
                role_edit = st.selectbox("Uloga", ["admin","manager","employee"], index=["admin","manager","employee"].index(user_data['role']))
                new_password = st.text_input("Nova Lozinka (ostavi prazno za bez promjene)", type="password")
                
                col1, col2 = st.columns(2)
                if col1.form_submit_button("Spremi Promjene"):
                    if new_password and not validate_password(new_password):
                        st.error("Nova lozinka mora imati barem 8 znakova.")
                    else:
                        if new_password:
                            ph = pbkdf2_hash(new_password)
                            cur.execute("UPDATE users SET username=?, role=?, password_hash=? WHERE id=?", (username, role_edit, ph, sel_id_num_user))
                        else:
                            cur.execute("UPDATE users SET username=?, role=? WHERE id=?", (username, role_edit, sel_id_num_user))
                        conn.commit(); st.success("Korisnik ažuriran."); st.rerun()
                
                if col2.form_submit_button("OBRIŠI KORISNIKA", type="primary"):
                    if user_data['id'] == st.session_state.user['id']:
                        st.error("Ne možete obrisati sami sebe.")
                    else:
                        cur.execute("DELETE FROM users WHERE id=?", (sel_id_num_user,))
                        conn.commit(); st.success("Korisnik obrisan."); st.rerun()

    # --- TAB 3: Sektori ---
    with admin_tabs[2]:
        st.subheader("Upravljanje Sektorima")
        df_sektori = query_df("SELECT * FROM sektor")
        st.dataframe(df_sektori, use_container_width=True)
        
        with st.form("form_add_sector"):
            name = st.text_input("Naziv novog sektora")
            if st.form_submit_button("Dodaj sektor"):
                try:
                    cur.execute("INSERT INTO sektor (naziv) VALUES (?)", (name,))
                    conn.commit(); st.success("Sektor dodan."); st.rerun()
                except Exception as e:
                    st.error(e)
        
        st.markdown("---")
        sektor_options = {f"ID: {r['id']} ({r['naziv']})": r['id'] for _, r in df_sektori.iterrows()}
        sel_id_sektor = st.selectbox("Odaberi sektor za brisanje", options=[""] + list(sektor_options.keys()), key="del_sektor_select")
        if sel_id_sektor:
            sid = sektor_options[sel_id_sektor]
            if st.button("OBRIŠI SEKTOR", type="primary"):
                cur.execute("DELETE FROM sektor WHERE id=?", (sid,))
                cur.execute("DELETE FROM pozicije WHERE sektor_id=?", (sid,))
                cur.execute("DELETE FROM smjene WHERE sektor_id=?", (sid,))
                cur.execute("UPDATE radnici SET sektor_id=NULL WHERE sektor_id=?", (sid,))
                conn.commit(); st.success("Sektor obrisan."); st.rerun()

    # --- TAB 4: Pozicije ---
    with admin_tabs[3]:
        st.subheader("Upravljanje Pozicijama")
        df_pozicije = query_df("SELECT p.id, p.naziv_pozicije, s.naziv as sektor FROM pozicije p LEFT JOIN sektor s ON p.sektor_id = s.id")
        st.dataframe(df_pozicije, use_container_width=True)
        
        with st.form("form_add_pozicija"):
            sektori_df = query_df("SELECT id, naziv FROM sektor")
            sektori_options = {r['naziv']: r['id'] for _, r in sektori_df.iterrows()}
            sektor_naziv = st.selectbox("Odaberi Sektor", options=[""]+list(sektori_options.keys()), key="add_poz_sektor")
            naziv_pozicije = st.text_input("Naziv nove pozicije")
            
            if st.form_submit_button("Dodaj poziciju"):
                if sektor_naziv and naziv_pozicije:
                    cur.execute("INSERT INTO pozicije (sektor_id, naziv_pozicije) VALUES (?, ?)", (sektori_options[sektor_naziv], naziv_pozicije))
                    conn.commit(); st.success("Pozicija dodana."); st.rerun()
                else:
                    st.error("Odaberite sektor i naziv.")

    # --- TAB 5: Smjene ---
    with admin_tabs[4]:
        st.subheader("Upravljanje Smjenama")
        df_smjene = query_df("SELECT sm.*, s.naziv as sektor FROM smjene sm LEFT JOIN sektor s ON sm.sektor_id = s.id")
        st.dataframe(df_smjene, use_container_width=True)
        
        with st.form("form_add_smjena"):
            sektori_df = query_df("SELECT id, naziv FROM sektor")
            sektori_options = {r['naziv']: r['id'] for _, r in sektori_df.iterrows()}
            sektor_naziv_smjena = st.selectbox("Odaberi Sektor", options=[""]+list(sektori_options.keys()), key="add_smjena_sektor")
            naziv_smjene = st.text_input("Naziv smjene")
            pocetak_smjene = st.time_input("Početak", value=time(8,0))
            kraj_smjene = st.time_input("Kraj", value=time(16,0))
            
            if st.form_submit_button("Dodaj smjenu"):
                if sektor_naziv_smjena and naziv_smjene:
                    cur.execute("INSERT INTO smjene (sektor_id, naziv_smjene, pocetak, kraj) VALUES (?, ?, ?, ?)", 
                              (sektori_options[sektor_naziv_smjena], naziv_smjene, pocetak_smjene.isoformat(), kraj_smjene.isoformat()))
                    conn.commit(); st.success("Smjena dodana."); st.rerun()
                else:
                    st.error("Odaberite sektor i naziv.")

    conn.close()