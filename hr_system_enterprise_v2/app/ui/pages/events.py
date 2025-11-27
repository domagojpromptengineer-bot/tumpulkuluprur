import streamlit as st
import pandas as pd
from datetime import datetime, time, date
from typing import List, Optional, Dict, Any, Tuple

# Uvoz zajedničkih servisa (pretpostavljena struktura)
from ...common.utils import get_conn, query_df, log_action, now_iso, send_notification

# --- KONSTANTE I ENUMI ---
EVENT_TYPES = ["Vjenčanje", "Konferencija", "Banket", "Team Building", "Ostalo"]
STATUS_ICONS = {"planirano": "🟢", "završeno": "🏁", "otkazano": "🔴"}
STATUS_COLORS = {"planirano": "green", "završeno": "gray", "otkazano": "red"}

# --- DATA ACCESS LAYER (DAL) ---

def get_user_sector_id(radnik_id: int) -> Optional[int]:
    """Dohvaća ID sektora za trenutnog korisnika na siguran način."""
    try:
        df = query_df("SELECT sektor_id FROM radnici WHERE id = ?", (radnik_id,))
        if not df.empty:
            return int(df.iloc[0]['sektor_id'])
    except Exception as e:
        st.error(f"Greška pri dohvatu sektora korisnika: {e}")
    return None

def fetch_all_sectors() -> Dict[str, int]:
    """Vraća mapu {naziv_sektora: id_sektora} za UI selektore."""
    df = query_df("SELECT id, naziv FROM sektor")
    return {row['naziv']: row['id'] for _, row in df.iterrows()}

def fetch_sector_names_map() -> Dict[int, str]:
    """Vraća mapu {id_sektora: naziv_sektora} za brzi lookup prikaza."""
    df = query_df("SELECT id, naziv FROM sektor")
    return {row['id']: row['naziv'] for _, row in df.iterrows()}

def create_event(
    naziv: str, 
    tip: str, 
    start_iso: str, 
    end_iso: str, 
    opis: str, 
    sektori_ids: List[int],
    creator_id: int
) -> bool:
    """Transakcijski unos novog eventa u bazu."""
    ids_str = ",".join(map(str, sektori_ids)) if sektori_ids else ""
    
    try:
        with get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO events (naziv, tip_eventa, pocetak, kraj, opis, sektori_ids, status)
                VALUES (?, ?, ?, ?, ?, ?, 'planirano')
            """, (naziv, tip, start_iso, end_iso, opis, ids_str))
            conn.commit()
            
            # Audit log
            log_action(creator_id, "CREATE_EVENT", f"Kreiran event: {naziv}")
            return True
    except Exception as e:
        st.error(f"Database Error: {e}")
        return False

def update_event_status(event_id: int, new_status: str, user_id: int) -> bool:
    """Ažurira status eventa."""
    try:
        with get_conn() as conn:
            conn.execute("UPDATE events SET status=? WHERE id=?", (new_status, event_id))
            conn.commit()
            log_action(user_id, "UPDATE_EVENT_STATUS", f"Event {event_id} -> {new_status}")
        return True
    except Exception as e:
        st.error(f"Greška pri ažuriranju statusa: {e}")
        return False

# --- BUSINESS LOGIC LAYER ---

def notify_sectors(naziv: str, tip: str, sektori_map: Dict[str, int], odabrani_sektori: List[str]):
    """Šalje notifikacije managerima i zaposlenicima."""
    for s_name in odabrani_sektori:
        sid = sektori_map.get(s_name)
        if sid:
            # Notifikacija Managerima
            send_notification(
                poruka=f"📅 Novi Event: {naziv} ({tip}) zahtijeva pažnju vašeg sektora.", 
                target_role="manager", 
                target_sektor_id=sid,
                link="events"
            )
            # Notifikacija Zaposlenicima
            send_notification(
                poruka=f"📅 Novi Event: {naziv} ({tip})", 
                target_role="employee", 
                target_sektor_id=sid,
                link="events"
            )

def check_visibility(event: pd.Series, role: str, user_sektor_id: Optional[int]) -> bool:
    """Određuje vidi li korisnik određeni event na temelju role i sektora."""
    if role == 'admin':
        return True
    
    # Parsiranje sektora iz CSV stringa u bazi
    raw_ids = event.get('sektori_ids')
    event_sector_ids = []
    if raw_ids and isinstance(raw_ids, str):
        event_sector_ids = [s.strip() for s in raw_ids.split(',') if s.strip()]
    
    # Ako event nije vezan ni za jedan sektor, vide ga svi (ili nitko, ovisno o politici - ovdje pretpostavljamo svi)
    if not event_sector_ids:
        return True

    # Ako je korisnik vezan za sektor koji je u listi sektora eventa
    if user_sektor_id and str(user_sektor_id) in event_sector_ids:
        return True
        
    return False

def format_sector_display(raw_ids: str, sector_names_map: Dict[int, str]) -> str:
    """Pretvara CSV ID-eva u čitljivu listu imena sektora."""
    if not raw_ids or not isinstance(raw_ids, str):
        return "Svi sektori"
    
    ids = [int(s) for s in raw_ids.split(',') if s.strip().isdigit()]
    names = [sector_names_map.get(i, f"Sektor {i}") for i in ids]
    return ", ".join(names) if names else "Svi sektori"

# --- UI COMPONENTS ---

def render_create_event_form(role: str, sektori_map: Dict[str, int], user_id: int):
    """Renderira formu za kreiranje eventa unutar expandera."""
    with st.expander("➕ Dodaj Novi Event", expanded=False):
        with st.form("new_event_form", clear_on_submit=True):
            st.subheader("Detalji Eventa")
            c1, c2 = st.columns(2)
            naziv = c1.text_input("Naziv Eventa", placeholder="npr. Godišnja konferencija")
            tip = c2.selectbox("Tip Eventa", EVENT_TYPES)
            
            c3, c4 = st.columns(2)
            start_d = c3.date_input("Datum Početka", value=datetime.now())
            start_t = c3.time_input("Vrijeme Početka", value=time(9, 0))
            end_d = c4.date_input("Datum Kraja", value=datetime.now())
            end_t = c4.time_input("Vrijeme Kraja", value=time(17, 0))
            
            odabrani_sektori = st.multiselect(
                "Vezani Sektori (Notifikacije & Vidljivost)", 
                options=list(sektori_map.keys()),
                help="Odaberite sektore koji moraju biti obaviješteni o ovom događaju."
            )
            
            opis = st.text_area("Opis / Napomene", height=100)
            
            submitted = st.form_submit_button("🚀 Kreiraj Event", use_container_width=True)
            
            if submitted:
                if not naziv:
                    st.warning("Naziv eventa je obavezan.")
                    return

                start_dt = datetime.combine(start_d, start_t)
                end_dt = datetime.combine(end_d, end_t)

                if end_dt <= start_dt:
                    st.error("Vrijeme kraja mora biti nakon vremena početka.")
                    return

                sektori_ids = [sektori_map[s] for s in odabrani_sektori]
                
                success = create_event(
                    naziv, tip, start_dt.isoformat(), end_dt.isoformat(), 
                    opis, sektori_ids, user_id
                )
                
                if success:
                    notify_sectors(naziv, tip, sektori_map, odabrani_sektori)
                    st.toast(f"Event '{naziv}' uspješno kreiran!", icon="✅")
                    st.rerun()

def render_event_card(event: pd.Series, role: str, sector_names_map: Dict[int, str], user_id: int):
    """Prikazuje pojedinačnu karticu eventa s akcijama."""
    start_dt = datetime.fromisoformat(event['pocetak'])
    end_dt = datetime.fromisoformat(event['kraj'])
    status = event['status']
    
    # Vizualni stil kartice
    card_border = True
    
    with st.container(border=card_border):
        # Header red: Ikona, Naslov, Badge
        col_h1, col_h2 = st.columns([3, 1])
        with col_h1:
            st.markdown(f"### {STATUS_ICONS.get(status, '⚪')} {event['naziv']}")
            st.caption(f"**Tip:** {event['tip_eventa']} | **ID:** {event['id']}")
        with col_h2:
            # Status badge (simuliran bojom teksta ili st.status ako je prikladno, ovdje koristimo markdown)
            st.markdown(f"<div style='text-align:right; color:{STATUS_COLORS.get(status, 'black')}; font-weight:bold;'>{status.upper()}</div>", unsafe_allow_html=True)

        st.divider()
        
        # Body red: Detalji
        bc1, bc2 = st.columns([2, 1])
        with bc1:
            st.markdown(f"**🕒 Vrijeme:**")
            st.text(f"{start_dt.strftime('%d.%m.%Y %H:%M')} - {end_dt.strftime('%H:%M')}")
            
            st.markdown(f"**🏢 Uključeni Sektori:**")
            sector_display = format_sector_display(event['sektori_ids'], sector_names_map)
            st.info(sector_display)
            
        with bc2:
            st.markdown("**📝 Opis:**")
            st.write(event['opis'] if event['opis'] else "Nema opisa.")

        # Footer red: Akcije (Samo Admin/Manager)
        if role in ['admin', 'manager']:
            st.divider()
            ac1, ac2, ac3 = st.columns([1, 1, 2])
            
            # Logika gumba za status
            if status == 'planirano':
                if ac1.button("✅ Završi", key=f"finish_{event['id']}", use_container_width=True):
                    if update_event_status(event['id'], 'završeno', user_id):
                        st.rerun()
                if ac2.button("🗑️ Otkaži", key=f"cancel_{event['id']}", use_container_width=True):
                    if update_event_status(event['id'], 'otkazano', user_id):
                        st.rerun()
            
            elif status == 'završeno':
                if ac1.button("🔄 Reaktiviraj", key=f"reactivate_{event['id']}", use_container_width=True):
                    if update_event_status(event['id'], 'planirano', user_id):
                        st.rerun()

# --- MAIN RENDER FUNCTION ---

def render(role: str):
    """Glavna funkcija za prikaz Event Dashboarda."""
    st.header("📅 Event Dashboard")
    
    # 1. Inicijalizacija podataka o korisniku
    user_id = st.session_state.user.get('radnik_id')
    user_sektor_id = get_user_sector_id(user_id) if user_id else None
    
    # Dohvat pomoćnih mapa (cache-friendly)
    sektori_map = fetch_all_sectors()       # {Naziv: ID}
    sector_names_map = fetch_sector_names_map() # {ID: Naziv}

    # 2. Sekcija za kreiranje (Admin/Manager)
    if role in ['admin', 'manager']:
        render_create_event_form(role, sektori_map, user_id)
        st.markdown("---")

    # 3. Filteri i Prikaz
    st.subheader("Pregled Događaja")
    
    col_f1, col_f2 = st.columns([3, 1])
    with col_f1:
        filter_tip = st.multiselect("Filtriraj po tipu", EVENT_TYPES)
    with col_f2:
        show_finished = st.checkbox("Prikaži povijest", value=False, help="Uključuje završene i otkazane evente")

    # 4. Dohvat podataka
    # Base query
    query = "SELECT * FROM events WHERE 1=1"
    params = []
    
    if not show_finished:
        query += " AND status = 'planirano'"
    else:
        # Ako prikazujemo povijest, i dalje ne želimo otkazane osim ako eksplicitno ne tražimo (ovdje logika: prikazi sve osim otkazanih ako nije specificirano drugacije, ali originalni kod je micao otkazane. Prilagodba: Prikazi sve statuse ako je show_finished True, ali mozda zelimo sakriti otkazane defaultno? Original: status != 'otkazano'. Zadržavam originalnu logiku ali proširujem.)
        pass 
        
    # Uvijek sortiraj po datumu
    query += " ORDER BY pocetak ASC"
    
    events_df = query_df(query, params)

    # 5. Renderiranje liste
    if events_df.empty:
        st.info("Nema evenata u bazi.")
    else:
        visible_count = 0
        
        for _, event in events_df.iterrows():
            # Globalni filter: Sakrij otkazane osim ako nismo admin (ili ako želimo vidjeti povijest)
            if event['status'] == 'otkazano' and not show_finished:
                continue

            # 1. Filter vidljivosti (Security)
            if not check_visibility(event, role, user_sektor_id):
                continue
            
            # 2. UI Filter (Tip eventa)
            if filter_tip and event['tip_eventa'] not in filter_tip:
                continue
            
            visible_count += 1
            render_event_card(event, role, sector_names_map, user_id)
        
        if visible_count == 0:
            st.warning("Nema evenata koji odgovaraju vašim filterima.")