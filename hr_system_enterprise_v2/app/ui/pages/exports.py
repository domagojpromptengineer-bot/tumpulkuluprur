import streamlit as st
from datetime import date
import json
from ...common.utils import get_conn, query_df, df_to_xlsx, log_action, get_company_info

def render(role):
    st.header("Izvoz Podataka & Državni Obrasci")
    
    if role != "admin":
        st.error("Pristup dozvoljen samo za ulogu 'admin'.")
        return

    conn = get_conn()
    company_info = get_company_info() # Dohvati podatke o tvrtki
    
    # --- EXCEL IZVOZ ---
    st.subheader("Izvoz tablica (Excel)")
    c1, c2 = st.columns(2)
    
    df_emp = query_df("SELECT * FROM radnici")
    xlsx_data_emp = df_to_xlsx(df_emp, sheet_name="Zaposlenici")
    c1.download_button("📥 Preuzmi Zaposlenike (.xlsx)", data=xlsx_data_emp, file_name="zaposlenici.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    
    df_ug = query_df("SELECT * FROM ugovori")
    xlsx_data_ug = df_to_xlsx(df_ug, sheet_name="Ugovori")
    c2.download_button("📥 Preuzmi Ugovore (.xlsx)", data=xlsx_data_ug, file_name="ugovori.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.markdown("---")
    
    # --- JOPPD OBRAZAC ---
    st.subheader("JOPPD Obrazac (XML)")
    st.caption("Generiranje XML-a sukladno shemi Porezne uprave (Strana A i B).")
    
    col_j1, col_j2 = st.columns(2)
    oznaka_izvjesca = col_j1.text_input("Oznaka izvješća (npr. 24051)", value=f"{date.today().strftime('%y%j')}")
    vrsta_izvjesca = col_j2.selectbox("Vrsta izvješća", ["1 - Izvorni", "2 - Ispravak", "3 - Dopuna"])
    
    employees = query_df("SELECT id, ime, prezime, oib FROM radnici")
    selected = st.multiselect("Odaberi zaposlenike za obračun", options=employees["id"].tolist(), format_func=lambda x: f"{employees[employees['id']==x].iloc[0]['ime']} {employees[employees['id']==x].iloc[0]['prezime']}")
    
    if st.button("Generiraj JOPPD XML"):
        if not company_info.get('company_oib'):
            st.error("Nedostaje OIB tvrtke u Admin panelu!")
        else:
            # Simulacija JOPPD XML strukture
            xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<ObrazacJOPPD xmlns="http://e-porezna.porezna-uprava.hr/sheme/zahtjevi/ObrazacJOPPD/v2-0">
    <Zaglavlje>
        <DatumIzvjesca>{date.today().isoformat()}</DatumIzvjesca>
        <OznakaIzvjesca>{oznaka_izvjesca}</OznakaIzvjesca>
        <VrstaIzvjesca>{vrsta_izvjesca[0]}</VrstaIzvjesca>
        <Podnositelj>
            <Naziv>{company_info.get('company_name')}</Naziv>
            <OIB>{company_info.get('company_oib')}</OIB>
            <Adresa>{company_info.get('company_address')}</Adresa>
        </Podnositelj>
    </Zaglavlje>
    <StranaB>
"""
            count = 0
            for sid in selected:
                r = conn.execute("SELECT * FROM radnici WHERE id=?", (sid,)).fetchone()
                u = conn.execute("SELECT * FROM ugovori WHERE radnik_id=? ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
                bruto = u['bruto'] if u else 0.00
                
                xml_content += f"""        <Primatelj>
            <OIB>{r['oib']}</OIB>
            <ImePrezime>{r['ime']} {r['prezime']}</ImePrezime>
            <SifraOpcine>00000</SifraOpcine>
            <OznakaPrimitka>0001</OznakaPrimitka>
            <IznosPrimitka>{bruto:.2f}</IznosPrimitka>
            <IznosDoprinosa>{bruto*0.2:.2f}</IznosDoprinosa>
        </Primatelj>
"""
                count += 1
            
            xml_content += """    </StranaB>
</ObrazacJOPPD>"""
            
            st.download_button("📥 Preuzmi JOPPD XML", data=xml_content.encode("utf-8"), file_name=f"JOPPD_{oznaka_izvjesca}.xml", mime="application/xml")
            log_action(st.session_state.user["username"], "gen_joppd", {"count": count})

    st.markdown("---")
    
    # --- HZMO PRIJAVA ---
    st.subheader("HZMO e-Prijava (JSON)")
    st.caption("Format za automatsku razmjenu podataka s HZMO sustavom.")
    
    hzmo_radnik_id = st.selectbox("Odaberi radnika za prijavu/odjavu", options=employees["id"].tolist(), format_func=lambda x: f"{employees[employees['id']==x].iloc[0]['ime']} {employees[employees['id']==x].iloc[0]['prezime']}")
    tip_akcije = st.radio("Vrsta akcije", ["Prijava (M-1P)", "Odjava (M-2P)", "Promjena (M-3P)"])
    
    if st.button("Generiraj HZMO JSON"):
        r = conn.execute("SELECT * FROM radnici WHERE id=?", (hzmo_radnik_id,)).fetchone()
        u = conn.execute("SELECT * FROM ugovori WHERE radnik_id=? ORDER BY id DESC LIMIT 1", (hzmo_radnik_id,)).fetchone()
        
        payload = {
            "header": {
                "sender_oib": company_info.get('company_oib'),
                "timestamp": date.today().isoformat(),
                "message_type": tip_akcije.split(" ")[1].replace("(", "").replace(")", "")
            },
            "body": {
                "osiguranik": {
                    "oib": r['oib'],
                    "ime": r['ime'],
                    "prezime": r['prezime'],
                    "datum_rodjenja": "1990-01-01" # Placeholder, trebao bi biti u bazi
                },
                "osiguranje": {
                    "datum_pocetka": u['pocetak'] if u else date.today().isoformat(),
                    "osnova_osiguranja": "11 - Radni odnos",
                    "sati_rada": 40,
                    "zanimanje": "Radnik" # Trebalo bi povući naziv pozicije
                }
            }
        }
        
        json_str = json.dumps(payload, indent=4, ensure_ascii=False)
        st.code(json_str, language="json")
        st.download_button("📥 Preuzmi HZMO JSON", data=json_str.encode("utf-8"), file_name=f"HZMO_{r['oib']}.json", mime="application/json")
    
    conn.close()