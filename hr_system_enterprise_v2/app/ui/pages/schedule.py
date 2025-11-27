import streamlit as st
import pandas as pd
from datetime import date, datetime, time, timedelta
from ...common.utils import get_conn, query_df, log_action, now_iso, get_position_rank, send_notification

def render(role):
    st.header("Evidencija i Raspored")
    
    # 1. Dohvati podatke o trenutnom korisniku
    user_sektor_id = None
    if st.session_state.user.get('radnik_id'):
        try:
            conn = get_conn()
            user_sektor_id = conn.execute("SELECT sektor_id FROM radnici WHERE id = ?", (st.session_state.user['radnik_id'],)).fetchone()['sektor_id']
            conn.close()
        except:
            pass

    # 2. Definiraj Tabove
    tab_keys = ["Raspored"]
    if role in ['admin', 'manager']:
        tab_keys.extend(["Evidencija Sati", "Prekovremeni"])
    tab_keys.extend(["Godišnji Odmori", "Bolovanja"])

    tabs = st.tabs(tab_keys)
    tab_map = dict(zip(tab_keys, tabs))
    
    conn = get_conn()
    cur = conn.cursor()

    # ---------------------------------------------------------
    # TAB 1: RASPORED (GRID EDITOR - ROBUSNA VERZIJA)
    # ---------------------------------------------------------
    with tab_map["Raspored"]:
        st.subheader("Tjedni Raspored")
        
        # A) Odabir Sektora
        sektori_df = query_df("SELECT id, naziv FROM sektor")
        sektori_options = {r['naziv']: r['id'] for _, r in sektori_df.iterrows()}
        
        selected_sektor_id = None
        if role == 'admin':
            sektor_naziv = st.selectbox("Odaberite Sektor", options=[""] + list(sektori_options.keys()))
            selected_sektor_id = sektori_options.get(sektor_naziv)
        elif user_sektor_id:
            selected_sektor_id = user_sektor_id
            try:
                s_name = [k for k,v in sektori_options.items() if v == user_sektor_id][0]
                st.info(f"Prikaz za vaš sektor: {s_name}")
            except: pass
        
        # B) Odabir Tjedna
        today = date.today()
        start_of_week = today - timedelta(days=today.weekday())
        week_start_date = st.date_input("Početak tjedna (Ponedjeljak)", value=start_of_week)
        
        if selected_sektor_id:
            # C) Dohvati Smjene (Format: 07:00-15:00)
            # Koristimo substr da maknemo sekunde ako postoje u bazi
            smjene_df = query_df(f"""
                SELECT naziv_smjene, substr(pocetak, 1, 5) as p, substr(kraj, 1, 5) as k 
                FROM smjene WHERE sektor_id = {selected_sektor_id} ORDER BY pocetak
            """)
            # Opcije za dropdown (Numerički format za sinkronizaciju s AI)
            smjene_options = [""] + [f"{row['p']}-{row['k']}" for _, row in smjene_df.iterrows()]
            
            # D) Dohvati Radnike (Hijerarhija + Pozicija)
            radnici_sektor_df = query_df(f"""
                SELECT r.id, r.ime, r.prezime, p.naziv_pozicije 
                FROM radnici r 
                LEFT JOIN pozicije p ON r.pozicija_id = p.id
                WHERE r.sektor_id = {selected_sektor_id} AND r.status_zaposlenja = 'aktivan'
            """)
            
            if not radnici_sektor_df.empty:
                # Sortiranje po rangu (Voditelj -> Radnik -> Pomoćni)
                radnici_sektor_df['rank'] = radnici_sektor_df['naziv_pozicije'].apply(get_position_rank)
                radnici_sektor_df = radnici_sektor_df.sort_values(by=['rank', 'prezime'])
                
                # Display Name: "Prezime Ime (Pozicija)"
                radnici_sektor_df['display_name'] = radnici_sektor_df.apply(
                    lambda x: f"{x['prezime']} {x['ime']} ({x['naziv_pozicije'] or 'N/A'})", axis=1
                )
                
                # Priprema Grid-a
                week_dates = [(week_start_date + timedelta(days=i)) for i in range(7)]
                # Mapiranje "Naslov Stupca" -> "ISO Datum"
                col_to_iso = {d.strftime("%A (%d.%m)"): d.isoformat() for d in week_dates}
                date_columns = list(col_to_iso.keys())
                
                grid_df = pd.DataFrame(index=radnici_sektor_df['display_name'], columns=date_columns)
                
                # Mapiranje Display Name -> ID Radnika
                radnik_id_map = dict(zip(radnici_sektor_df['display_name'], radnici_sektor_df['id']))
                
                # E) Učitaj Postojeće Podatke iz Baze
                start_iso = week_start_date.isoformat()
                end_iso = (week_start_date + timedelta(days=6)).isoformat()
                
                existing = query_df("""
                    SELECT r.radnik_id, r.datum, r.opis_smjene FROM rasporedi r
                    JOIN radnici rad ON r.radnik_id = rad.id
                    WHERE rad.sektor_id = ? AND r.datum BETWEEN ? AND ?
                """, (selected_sektor_id, start_iso, end_iso))
                
                # Popuni Grid podacima
                id_to_display = {v: k for k, v in radnik_id_map.items()}
                
                for _, shift in existing.iterrows():
                    r_display = id_to_display.get(shift['radnik_id'])
                    s_date_iso = shift['datum'] # YYYY-MM-DD
                    
                    # Nađi koji stupac odgovara ovom datumu
                    col_name = None
                    for name, iso in col_to_iso.items():
                        if iso == s_date_iso:
                            col_name = name
                            break
                    
                    if r_display in grid_df.index and col_name:
                        val = shift['opis_smjene']
                        grid_df.at[r_display, col_name] = val

                # F) Prikaz Editora
                is_editor = role in ['admin', 'manager']
                column_config = {col: st.column_config.SelectboxColumn(
                    f"{col}", 
                    options=smjene_options,
                    required=False
                ) for col in date_columns}
                
                edited_df = st.data_editor(
                    grid_df, 
                    use_container_width=True, 
                    disabled=not is_editor, 
                    column_config=column_config,
                    key="schedule_editor_grid"
                )
                
                # G) Spremanje (Robusna logika)
                if is_editor and st.button("💾 Spremi Raspored"):
                    saved_count = 0
                    try:
                        for r_display, row in edited_df.iterrows():
                            rid = radnik_id_map.get(r_display)
                            if rid:
                                for col_name, val in row.items():
                                    # Konvertiraj naslov stupca natrag u ISO datum
                                    d_smjene = col_to_iso.get(col_name)
                                    
                                    # Čišćenje vrijednosti (None, NaN, prazno, string "None")
                                    clean_val = None
                                    if val and pd.notna(val):
                                        s_val = str(val).strip()
                                        if s_val.lower() not in ['none', 'nan', '', 'slobodan']:
                                            clean_val = s_val
                                    
                                    # Provjeri postoji li zapis
                                    cur.execute("SELECT id FROM rasporedi WHERE radnik_id=? AND datum=?", (rid, d_smjene))
                                    entry = cur.fetchone()
                                    
                                    if entry:
                                        if clean_val:
                                            # Update
                                            cur.execute("UPDATE rasporedi SET opis_smjene=?, sektor_id=? WHERE id=?", (clean_val, selected_sektor_id, entry['id']))
                                        else:
                                            # Delete (ako je polje prazno, brišemo smjenu)
                                            cur.execute("DELETE FROM rasporedi WHERE id=?", (entry['id'],))
                                    elif clean_val:
                                        # Insert
                                        cur.execute("INSERT INTO rasporedi (sektor_id, radnik_id, datum, opis_smjene) VALUES (?,?,?,?)", (selected_sektor_id, rid, d_smjene, clean_val))
                                    
                                    saved_count += 1
                        conn.commit()
                        st.success(f"Raspored uspješno spremljen! Obrađeno {saved_count} ćelija.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Greška pri spremanju: {e}")
            else:
                st.warning("Nema radnika u ovom sektoru.")

    # ---------------------------------------------------------
    # TAB 2: EVIDENCIJA SATI
    # ---------------------------------------------------------
    if "Evidencija Sati" in tab_map:
        with tab_map["Evidencija Sati"]:
            st.subheader("Evidencija Radnog Vremena")
            with st.expander("Dodaj novi zapis"):
                with st.form("form_time"):
                    radnici_df = query_df("SELECT id, ime, prezime FROM radnici ORDER BY prezime, ime")
                    radnici_options = {f"{r['prezime']} {r['ime']} (ID: {r['id']})": r['id'] for _, r in radnici_df.iterrows()}
                    radnik_label = st.selectbox("Odaberi zaposlenika", options=radnici_options.keys())
                    rid = radnici_options.get(radnik_label)
                    datum = st.date_input("Datum", value=date.today())
                    dol = st.time_input("Dolazak", value=time(8,0))
                    odl = st.time_input("Odlazak", value=time(16,0))
                    
                    if st.form_submit_button("Spremi zapis"):
                        cur.execute("INSERT INTO radno_vrijeme (radnik_id,datum,dolazak,odlazak,created_at) VALUES (?,?,?,?,?)",
                                  (rid, datum.isoformat(), dol.isoformat(), odl.isoformat(), now_iso()))
                        conn.commit(); st.success("Zapis spremljen."); st.rerun()
            
            df_time = query_df("SELECT t.*, r.ime||' '||r.prezime as radnik FROM radno_vrijeme t LEFT JOIN radnici r ON t.radnik_id=r.id ORDER BY t.id DESC LIMIT 50")
            st.dataframe(df_time, use_container_width=True)

    # ---------------------------------------------------------
    # TAB 3: PREKOVREMENI
    # ---------------------------------------------------------
    if "Prekovremeni" in tab_map:
        with tab_map["Prekovremeni"]:
            st.subheader("Prekovremeni")
            sql_ot = "SELECT p.*, r.ime||' '||r.prezime as radnik FROM prekovremeni p LEFT JOIN radnici r ON p.radnik_id=r.id"
            if role == 'manager' and user_sektor_id:
                sql_ot += f" WHERE r.sektor_id = {user_sektor_id}"
            df_ot = query_df(sql_ot)
            st.dataframe(df_ot, use_container_width=True)
            
            sel_approve = st.number_input("ID za odobrenje", min_value=0)
            if sel_approve > 0 and st.button("Odobri"):
                cur.execute("UPDATE prekovremeni SET odobreno=1, odobrio=? WHERE id=?", (st.session_state.user['id'], sel_approve))
                conn.commit(); st.success("Odobreno!"); st.rerun()

    # ---------------------------------------------------------
    # TAB 4: GODIŠNJI ODMORI (ZAHTJEVI + NOTIFIKACIJE)
    # ---------------------------------------------------------
    with tab_map["Godišnji Odmori"]:
        st.subheader("Godišnji Odmori")
        
        # A) FORMA ZA ZAHTJEV (Samo Employee)
        if role == 'employee' and st.session_state.user.get('radnik_id'):
            with st.form("req_go_form"):
                st.write("Podnesi novi zahtjev")
                d_start = st.date_input("Od")
                d_end = st.date_input("Do")
                dana = st.number_input("Broj radnih dana", min_value=1)
                
                if st.form_submit_button("Pošalji Zahtjev"):
                    rid = st.session_state.user['radnik_id']
                    # Spremi zahtjev
                    cur.execute("""
                        INSERT INTO zahtjevi_go (radnik_id, pocetak, kraj, dana, status, created_at)
                        VALUES (?, ?, ?, ?, 'na čekanju', ?)
                    """, (rid, d_start.isoformat(), d_end.isoformat(), dana, now_iso()))
                    conn.commit()
                    
                    # Notifikacija Manageru i Adminu
                    r_info = conn.execute("SELECT ime, prezime, sektor_id FROM radnici WHERE id=?", (rid,)).fetchone()
                    msg = f"Zahtjev za GO: {r_info['ime']} {r_info['prezime']} ({dana} dana)"
                    
                    # Manageru sektora
                    send_notification(msg, target_role="manager", target_sektor_id=r_info['sektor_id'])
                    # Adminu
                    send_notification(msg, target_role="admin")
                    
                    st.success("Zahtjev poslan!")
                    st.rerun()

        # B) PRIKAZ ZAHTJEVA (Manager/Admin odobrava)
        if role in ['admin', 'manager']:
            st.markdown("### Zahtjevi na čekanju")
            
            query_req = """
                SELECT z.*, r.ime, r.prezime, r.sektor_id 
                FROM zahtjevi_go z JOIN radnici r ON z.radnik_id = r.id 
                WHERE z.status = 'na čekanju'
            """
            if role == 'manager' and user_sektor_id:
                query_req += f" AND r.sektor_id = {user_sektor_id}"
                
            reqs = query_df(query_req)
            
            if reqs.empty:
                st.info("Nema zahtjeva na čekanju.")
            else:
                for _, req in reqs.iterrows():
                    c1, c2, c3 = st.columns([3, 1, 1])
                    c1.write(f"**{req['ime']} {req['prezime']}**: {req['pocetak']} - {req['kraj']} ({req['dana']} dana)")
                    
                    if c2.button("✅ Odobri", key=f"app_{req['id']}"):
                        # 1. Ažuriraj status zahtjeva
                        cur.execute("UPDATE zahtjevi_go SET status='odobreno' WHERE id=?", (req['id'],))
                        
                        # 2. Skini dane s bilance
                        cur.execute("UPDATE godisnji_odmori SET iskorišteni_dani = iskorišteni_dani + ? WHERE radnik_id=? AND godina=?", 
                                  (req['dana'], req['radnik_id'], date.today().year))
                        
                        # 3. AUTOMATSKI UPIS U RASPORED
                        start_date = date.fromisoformat(req['pocetak'])
                        end_date = date.fromisoformat(req['kraj'])
                        delta = end_date - start_date
                        
                        for i in range(delta.days + 1):
                            day = start_date + timedelta(days=i)
                            # Preskoči vikende ako treba (ovdje pretpostavljamo da se GO piše svaki dan)
                            day_iso = day.isoformat()
                            
                            # Provjeri postoji li već smjena
                            cur.execute("SELECT id FROM rasporedi WHERE radnik_id=? AND datum=?", (req['radnik_id'], day_iso))
                            exists = cur.fetchone()
                            
                            if exists:
                                cur.execute("UPDATE rasporedi SET opis_smjene='GODIŠNJI' WHERE id=?", (exists['id'],))
                            else:
                                cur.execute("INSERT INTO rasporedi (sektor_id, radnik_id, datum, opis_smjene) VALUES (?, ?, ?, 'GODIŠNJI')", 
                                          (req['sektor_id'], req['radnik_id'], day_iso))
                        
                        conn.commit()
                        
                        # 4. Javi radniku
                        u_res = conn.execute("SELECT id FROM users WHERE radnik_id=?", (req['radnik_id'],)).fetchone()
                        if u_res:
                            send_notification("Vaš zahtjev za GO je ODOBREN! ✅", user_id=u_res['id'], link="schedule")
                        
                        st.success("Odobreno i upisano u raspored.")
                        st.rerun()
        
        st.markdown("---")
        st.subheader("Stanje Godišnjih Odmora")
        df_go = query_df("SELECT g.*, r.ime||' '||r.prezime as radnik FROM godisnji_odmori g LEFT JOIN radnici r ON g.radnik_id=r.id")
        st.dataframe(df_go, use_container_width=True)

    # ---------------------------------------------------------
    # TAB 5: BOLOVANJA
    # ---------------------------------------------------------
    with tab_map["Bolovanja"]:
        st.subheader("Bolovanja")
        with st.form("form_sick"):
            radnici_df = query_df("SELECT id, ime, prezime FROM radnici")
            radnici_options = {f"{r['prezime']} {r['ime']}": r['id'] for _, r in radnici_df.iterrows()}
            r_label = st.selectbox("Zaposlenik", options=radnici_options.keys())
            rid = radnici_options.get(r_label)
            poc = st.date_input("Početak")
            kraj = st.date_input("Kraj")
            
            if st.form_submit_button("Unesi bolovanje"):
                cur.execute("INSERT INTO bolovanja (radnik_id,pocetak,kraj,status,created_at) VALUES (?,?,?,?,?)", 
                          (rid, poc.isoformat(), kraj.isoformat(), "submitted", now_iso()))
                conn.commit(); st.success("Bolovanje uneseno."); st.rerun()
        
        df_sick = query_df("SELECT b.*, r.ime||' '||r.prezime as radnik FROM bolovanja b LEFT JOIN radnici r ON b.radnik_id=r.id")
        st.dataframe(df_sick, use_container_width=True)

    conn.close()