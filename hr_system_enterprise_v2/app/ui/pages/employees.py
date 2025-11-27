import streamlit as st
import sqlite3
from datetime import date
from ...common.utils import get_conn, query_df, log_action, is_valid_oib, is_valid_email, df_to_xlsx

def render(role):
    st.header("Zaposlenici")
    if role not in ["admin", "manager"]:
        st.error("Pristup dozvoljen samo za uloge 'admin' i 'manager'.")
        return

    conn = get_conn(); cur = conn.cursor()
    st.info("Za dodavanje novog zaposlenika, molimo kreirajte 'Novi Ugovor' na stranici 'Ugovori'.")
    
    st.subheader("Popis svih zaposlenika")
    search_term_emp = st.text_input("Pretraži zaposlenike (ime, prezime, OIB, sektor...)")
    
    df_svi = query_df("""
        SELECT r.id, r.ime, r.prezime, r.oib, r.email, s.naziv as sektor, p.naziv_pozicije as pozicija, r.status_zaposlenja, r.datum_zaposlenja 
        FROM radnici r 
        LEFT JOIN sektor s ON r.sektor_id=s.id
        LEFT JOIN pozicije p ON r.pozicija_id = p.id
    """)
    
    if search_term_emp:
        df_svi = df_svi[df_svi.apply(lambda row: search_term_emp.lower() in str(row).lower(), axis=1)]
    
    st.dataframe(df_svi, use_container_width=True)
    
    xlsx_data = df_to_xlsx(df_svi, sheet_name="Zaposlenici")
    st.download_button("Preuzmi kao Excel (.xlsx)", data=xlsx_data, file_name="zaposlenici.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    if role == 'admin':
        st.markdown("---")
        st.subheader("Admin: Uredi / Obriši Zaposlenika")
        
        all_radnici_df = query_df("SELECT id, ime, prezime FROM radnici ORDER BY prezime, ime")
        radnik_options = {f"ID: {r['id']} ({r['prezime']} {r['ime']})": r['id'] for _, r in all_radnici_df.iterrows()}
        selected_radnik_label = st.selectbox("Odaberi zaposlenika za Uređivanje/Brisanje", options=[""] + list(radnik_options.keys()))
        
        if selected_radnik_label:
            radnik_id = radnik_options[selected_radnik_label]
            radnik_data = conn.execute("SELECT * FROM radnici WHERE id=?", (radnik_id,)).fetchone()
            
            with st.form("form_edit_emp"):
                st.write(f"Uređivanje: {radnik_data['ime']} {radnik_data['prezime']}")
                ime = st.text_input("Ime", value=radnik_data['ime'])
                prezime = st.text_input("Prezime", value=radnik_data['prezime'])
                oib = st.text_input("OIB", value=radnik_data['oib'])
                adresa = st.text_input("Adresa", value=radnik_data['adresa'])
                tel = st.text_input("Kontakt tel", value=radnik_data['kontakt_tel'])
                email = st.text_input("Email", value=radnik_data['email'])
                
                sektori_df = query_df("SELECT id, naziv FROM sektor")
                sektori_options = {r['naziv']: r['id'] for _, r in sektori_df.iterrows()}
                sektori_nazivi = list(sektori_options.keys())
                try:
                    current_sektor_index = sektori_nazivi.index(conn.execute("SELECT naziv FROM sektor WHERE id=?", (radnik_data['sektor_id'],)).fetchone()['naziv'])
                except Exception:
                    current_sektor_index = 0
                sektor_naziv = st.selectbox("Sektor", options=sektori_nazivi, index=current_sektor_index, key="edit_sektor")
                sektor_id = sektori_options.get(sektor_naziv)
                
                pozicija_id = None
                if sektor_id:
                    pozicije_df = query_df("SELECT id, naziv_pozicije FROM pozicije WHERE sektor_id = ?", (sektor_id,))
                    pozicije_options = {r['naziv_pozicije']: r['id'] for _, r in pozicije_df.iterrows()}
                    if pozicije_options:
                        try:
                            current_poz_idx = list(pozicije_options.values()).index(radnik_data['pozicija_id'])
                        except:
                            current_poz_idx = 0
                        pozicija_id = st.selectbox("Pozicija", options=pozicije_options.values(), index=current_poz_idx, format_func=lambda x: [k for k,v in pozicije_options.items() if v == x][0])
                
                status = st.selectbox("Status", ["aktivan", "neaktivan"], index=["aktivan", "neaktivan"].index(radnik_data['status_zaposlenja']))
                datum_z = st.date_input("Datum zaposlenja", value=date.fromisoformat(radnik_data['datum_zaposlenja']))
                
                col1, col2 = st.columns(2)
                if col1.form_submit_button("Spremi Promjene"):
                    if not is_valid_oib(oib):
                        st.error("OIB mora imati točno 11 znamenki.")
                    elif not is_valid_email(email):
                        st.error("Format e-maila nije ispravan.")
                    else:
                        try:
                            cur.execute("""UPDATE radnici SET 
                                ime=?, prezime=?, oib=?, adresa=?, kontakt_tel=?, email=?, sektor_id=?, pozicija_id=?, datum_zaposlenja=?, status_zaposlenja=?
                                WHERE id=?""",
                                (ime, prezime, oib, adresa, tel, email, sektor_id, pozicija_id, datum_z.isoformat(), status, radnik_id))
                            conn.commit()
                            st.success("Zaposlenik ažuriran.")
                            log_action(st.session_state.user["username"], "edit_employee", {"id": radnik_id})
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error(f"Greška: OIB '{oib}' već postoji.")
                        except Exception as e:
                            st.error(f"Greška: {e}")
                
                if col2.form_submit_button("OBRIŠI ZAPOSLENIKA", type="primary"):
                    try:
                        cur.execute("DELETE FROM radnici WHERE id=?", (radnik_id,))
                        cur.execute("DELETE FROM ugovori WHERE radnik_id=?", (radnik_id,))
                        cur.execute("DELETE FROM users WHERE radnik_id=?", (radnik_id,))
                        conn.commit()
                        st.success("Zaposlenik obrisan.")
                        log_action(st.session_state.user["username"], "delete_employee", {"id": radnik_id})
                        st.rerun()
                    except Exception as e:
                        st.error(f"Greška: {e}")
    conn.close()