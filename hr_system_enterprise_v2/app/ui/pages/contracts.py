import streamlit as st
from datetime import date
from ...common.utils import get_conn, query_df, log_action, now_iso, is_valid_oib, is_valid_email, df_to_xlsx
from ...services.documents.contract_generator import get_contract_template, generate_contract_docx

def render(role):
    st.header("Ugovori")
    if role != "admin":
        st.error("Pristup dozvoljen samo za ulogu 'admin'.")
        return

    conn = get_conn(); cur = conn.cursor()
    with st.expander("Kreiraj Novi Ugovor (i Novog Zaposlenika)"):
        with st.form("form_contract"):
            st.subheader("1. Podaci o Zaposleniku")
            ime = st.text_input("Ime *")
            prezime = st.text_input("Prezime *")
            oib = st.text_input("OIB (11 znamenki) *")
            adresa = st.text_input("Adresa")
            tel = st.text_input("Kontakt tel")
            email = st.text_input("Email *")
            
            st.subheader("2. Podaci o Radnom Mjestu")
            sektori_df = query_df("SELECT id, naziv FROM sektor")
            sektori_options = {r['naziv']: r['id'] for _, r in sektori_df.iterrows()}
            sektor_naziv = st.selectbox("Sektor *", options=[""] + list(sektori_options.keys()), key="add_sektor")
            sektor_id = sektori_options.get(sektor_naziv)
            
            pozicija_id = None
            if sektor_id:
                pozicije_df = query_df("SELECT id, naziv_pozicije FROM pozicije WHERE sektor_id = ?", (sektor_id,))
                pozicije_options = {r['naziv_pozicije']: r['id'] for _, r in pozicije_df.iterrows()}
                if pozicije_options:
                    pozicija_naziv = st.selectbox("Pozicija *", options=[""] + list(pozicije_options.keys()), key="add_pozicija")
                    pozicija_id = pozicije_options.get(pozicija_naziv)
                else:
                    st.warning(f"Nema definiranih pozicija za sektor '{sektor_naziv}'.")
            
            st.subheader("3. Detalji Ugovora")
            tip = st.selectbox("Tip ugovora *", ["na neodređeno","na određeno","honorarno"])
            poc = st.date_input("Datum početka (Datum zaposlenja) *", date.today())
            kraj = None
            if tip != "na neodređeno":
                kraj = st.date_input("Datum kraja", date.today())
            bruto = st.number_input("Bruto Plaća *", value=1000.0, step=50.0, min_value=0.0)
            neto = st.number_input("Neto Plaća *", value=800.0, step=50.0, min_value=0.0)
            
            if st.form_submit_button("Kreiraj Ugovor i Zaposlenika"):
                if not (ime and prezime and oib and email and sektor_id and poc and bruto > 0 and neto > 0):
                    st.error("Molimo ispunite sva obavezna polja.")
                elif not pozicija_id:
                    st.error("Molimo odaberite poziciju.")
                elif not is_valid_oib(oib):
                    st.error("OIB mora imati točno 11 znamenki.")
                elif not is_valid_email(email):
                    st.error("Format e-maila nije ispravan.")
                else:
                    existing = conn.execute("SELECT id FROM radnici WHERE oib = ?", (oib,)).fetchone()
                    if existing:
                        st.error(f"Zaposlenik s OIB-om {oib} već postoji.")
                    else:
                        try:
                            cur.execute("""INSERT INTO radnici (ime,prezime,oib,adresa,kontakt_tel,email,sektor_id,pozicija_id,datum_zaposlenja,status_zaposlenja)
                                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                                    (ime, prezime, oib, adresa, tel, email, sektor_id, pozicija_id, poc.isoformat(), "aktivan"))
                            radnik_id = cur.lastrowid
                            kraj_iso = kraj.isoformat() if kraj else None
                            cur.execute("INSERT INTO ugovori (radnik_id,tip_ugovora,pocetak,kraj,bruto,neto,created_at) VALUES (?,?,?,?,?,?,?)",
                                    (radnik_id, tip, poc.isoformat(), kraj_iso, float(bruto), float(neto), now_iso()))
                            conn.commit()
                            st.success(f"Zaposlenik (ID: {radnik_id}) i ugovor su uspješno kreirani.")
                            log_action(st.session_state.user["username"], "create_employee_contract", {"radnik_id": radnik_id, "oib": oib})
                        except Exception as e:
                            conn.rollback()
                            st.error(f"Greška: {e}")

    st.subheader("Popis svih ugovora")
    search_term_ug = st.text_input("Pretraži ugovore (ime, prezime, tip...)")
    df_ug = query_df("SELECT u.*, r.ime||' '||r.prezime as radnik FROM ugovori u LEFT JOIN radnici r ON u.radnik_id=r.id")
    if search_term_ug:
        df_ug = df_ug[df_ug.apply(lambda row: search_term_ug.lower() in str(row).lower(), axis=1)]
    st.dataframe(df_ug, use_container_width=True)
    
    xlsx_data_ug = df_to_xlsx(df_ug, sheet_name="Ugovori")
    st.download_button("Preuzmi kao Excel (.xlsx)", data=xlsx_data_ug, file_name="ugovori.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.markdown("---")
    st.subheader("Generiranje Dokumenta Ugovora (Predložak)")
    contracts_df_gen = query_df("""
        SELECT u.id, r.ime, r.prezime, r.id as radnik_id
        FROM ugovori u JOIN radnici r ON u.radnik_id = r.id 
        ORDER BY r.prezime, r.ime, u.pocetak DESC
    """)
    
    if not contracts_df_gen.empty:
        contract_options_gen = {f"ID: {r['id']} ({r['prezime']} {r['ime']})": (r['id'], r['radnik_id']) for _, r in contracts_df_gen.iterrows()}
        sel_label_gen = st.selectbox("Odaberite ugovor za generiranje", options=[""] + list(contract_options_gen.keys()), key="gen_contract_select")
        
        if sel_label_gen:
            ugovor_id, radnik_id = contract_options_gen[sel_label_gen]
            
            try:
                # 1. Dohvati podatke o tvrtki (Globalni Config)
                from ...common.utils import get_company_info
                company_data = get_company_info()
                
                # 2. Dohvati podatke o radniku i poziciji
                radnik_data = conn.execute("""
                    SELECT r.*, s.naziv as sektor, p.naziv_pozicije as pozicija 
                    FROM radnici r 
                    LEFT JOIN sektor s ON r.sektor_id = s.id 
                    LEFT JOIN pozicije p ON r.pozicija_id = p.id
                    WHERE r.id = ?
                """, (radnik_id,)).fetchone()
                
                # 3. Dohvati podatke o ugovoru
                ugovor_data = conn.execute("SELECT * FROM ugovori WHERE id = ?", (ugovor_id,)).fetchone()
                
                # 4. Pripremi Dictionary za Template
                # Koristimo .get() s default vrijednostima da izbjegnemo greške ako nešto fali
                template_data = {
                    # Podaci o tvrtki
                    "company_name": company_data.get('company_name', '[NAZIV TVRTKE - Postavi u Adminu]'),
                    "company_oib": company_data.get('company_oib', '[OIB TVRTKE]'),
                    "company_address": company_data.get('company_address', '[ADRESA TVRTKE]'),
                    "company_director": "Uprava", # Može se dodati u config ako treba
                    
                    # Podaci o radniku
                    "emp_name": f"{radnik_data['ime']} {radnik_data['prezime']}",
                    "emp_oib": radnik_data['oib'],
                    "emp_address": radnik_data['adresa'],
                    "emp_position": radnik_data['pozicija'] or 'Radnik',
                    
                    # Podaci o ugovoru
                    "pocetak": date.fromisoformat(ugovor_data['pocetak']).strftime('%d.%m.%Y.'),
                    "tip_ugovora": ugovor_data['tip_ugovora'],
                    "kraj": date.fromisoformat(ugovor_data['kraj']).strftime('%d.%m.%Y.') if ugovor_data['kraj'] else None,
                    "bruto": ugovor_data['bruto'],
                    "neto": ugovor_data['neto'],
                }
                
                # 5. Generiraj Tekst
                ugovor_text = get_contract_template(template_data)
                
                # Prikaz i Download
                st.subheader(f"Pregled Ugovora: {radnik_data['ime']} {radnik_data['prezime']}")
                st.text_area("Sadržaj Ugovora", value=ugovor_text, height=500)
                
                col_d1, col_d2 = st.columns(2)
                
                # Download TXT
                col_d1.download_button(
                    label="📄 Preuzmi kao Tekst (.txt)",
                    data=ugovor_text.encode('utf-8'),
                    file_name=f"Ugovor_{radnik_data['prezime']}.txt",
                    mime="text/plain"
                )
                
                # Download DOCX (Pravi format)
                docx_buffer = generate_contract_docx(ugovor_text)
                col_d2.download_button(
                    label="🟦 Preuzmi kao Word (.docx)",
                    data=docx_buffer,
                    file_name=f"Ugovor_{radnik_data['prezime']}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                )
                
            except Exception as e:
                st.error(f"Greška pri generiranju ugovora: {e}")
                st.info("Savjet: Provjerite jeste li unijeli podatke o tvrtki u Admin panelu.")
    conn.close()