import streamlit as st
import google.generativeai as genai
import json
from datetime import date, timedelta
from ..common.utils import get_conn, query_df

def get_google_ai_model():
    api_key = st.session_state.get("api_key")
    if not api_key:
        return None
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        return model
    except Exception as e:
        raise e

def predict_turnover_with_google_ai(features: dict):
    try:
        model = get_google_ai_model()
        if not model:
            st.error("Google AI model nije dostupan. Provjerite API ključ.")
            return {"error": "AI model nije dostupan."}
    except Exception as e:
        st.error(f"Greška pri konfiguraciji Google AI: {e}")
        return {"error": f"Greška pri konfiguraciji: {e}"}

    conn = get_conn()
    prompt_template = conn.execute("SELECT prompt_template FROM ai_config WHERE key='turnover_prediction'").fetchone()['prompt_template']
    conn.close()
    
    prompt = prompt_template.format(
        months_in_company=features.get("months_in_company", 12),
        avg_overtime_per_month=features.get("avg_overtime_per_month", 2.0),
        sick_days_last_6m=features.get("sick_days_last_6m", 0),
        late_rate=features.get("late_rate", 0.05)
    )
    
    try:
        response = model.generate_content(prompt)
        cleaned_response = response.text.strip().replace("```json\n", "").replace("\n```", "")
        result = json.loads(cleaned_response)
        return result
    except Exception as e:
        if "401" in str(e) or "API_KEY_INVALID" in str(e):
            st.error("Greška: 401 - Neispravan API ključ.")
        elif "404" in str(e):
            st.error("Greška: 404 - Model nije pronađen.")
        else:
            st.error(f"Greška pri komunikaciji s AI: {e}")
        return {"error": str(e)}

def generate_schedule_with_google_ai(sektor_id, sektor_naziv, start_date_iso, additional_constraints):
    try:
        model = get_google_ai_model()
        if not model:
            st.error("Google AI model nije dostupan.")
            return "AI model nije dostupan."
    except Exception as e:
        st.error(f"Greška: {e}")
        return f"Greška: {e}"

    conn = get_conn()
    prompt_template = conn.execute("SELECT prompt_template FROM ai_config WHERE key='schedule_generation'").fetchone()['prompt_template']
    
    employees_df = query_df("""
        SELECT r.id, r.ime, r.prezime, p.naziv_pozicije 
        FROM radnici r 
        LEFT JOIN pozicije p ON r.pozicija_id = p.id
        WHERE r.sektor_id = ?
    """, (sektor_id,))
    employees_list = "\n".join([f"- ID {row['id']}: {row['ime']} {row['prezime']} ({row['naziv_pozicije'] or 'N/A'})" for _, row in employees_df.iterrows()])
    
    start_date = date.fromisoformat(start_date_iso)
    end_date = start_date + timedelta(days=6)
    
    leaves_sql = """
        SELECT r.ime, r.prezime, b.pocetak, b.kraj, 'Bolovanje' as tip
        FROM bolovanja b JOIN radnici r ON b.radnik_id = r.id
        WHERE b.radnik_id IN (SELECT id FROM radnici WHERE sektor_id = ?) 
         AND b.kraj >= ? AND b.pocetak <= ?
    """
    leaves_params = (sektor_id, start_date_iso, end_date.isoformat())
    leaves_df = query_df(leaves_sql, leaves_params)
    
    leaves_list = "Nema zabilježenih odsustava."
    if not leaves_df.empty:
        leaves_list = "\n".join(
            [f"- {row['ime']} {row['prezime']} ({row['tip']}): {row['pocetak']} do {row['kraj']}" 
             for _, row in leaves_df.iterrows()]
        )
    conn.close()

    prompt = prompt_template.format(
        start_date=start_date.strftime("%d.%m.%Y."),
        sektor_naziv=sektor_naziv,
        employees_list=employees_list if not employees_df.empty else "Nema zaposlenika.",
        leaves_list=leaves_list,
        additional_constraints=additional_constraints if additional_constraints else "Nema."
    )
    
    try:
        st.info("Generiram AI raspored...")
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        st.error(f"Greška: {e}")
        return f"Greška: {e}"