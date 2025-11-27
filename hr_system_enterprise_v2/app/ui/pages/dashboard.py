import streamlit as st
from datetime import date, datetime, time, timedelta
from ...common.utils import get_conn, query_df

def render(role):
    st.header(f"Dobrodošli, {st.session_state.user['username']}!")
    
    conn = get_conn()
    cur = conn.cursor()
    
    # Dohvati podatke o korisniku (radnik_id, sektor_id)
    radnik_id = st.session_state.user.get('radnik_id')
    user_sektor_id = None
    radnik_ime = ""
    
    if radnik_id:
        r_data = conn.execute("SELECT ime, prezime, sektor_id FROM radnici WHERE id=?", (radnik_id,)).fetchone()
        if r_data:
            user_sektor_id = r_data['sektor_id']
            radnik_ime = f"{r_data['ime']} {r_data['prezime']}"

    # ---------------------------------------------------------
    # EMPLOYEE DASHBOARD (Personalizirano)
    # ---------------------------------------------------------
    if role == 'employee':
        if not radnik_id:
            st.warning("Vaš korisnički račun nije povezan s profilom radnika.")
            return

        st.subheader(f"👤 Moj Pregled ({radnik_ime})")
        
        # 1. SLJEDEĆA SMJENA
        today_iso = date.today().isoformat()
        next_shift = conn.execute("""
            SELECT datum, opis_smjene FROM rasporedi 
            WHERE radnik_id = ? AND datum >= ? 
            ORDER BY datum ASC LIMIT 1
        """, (radnik_id, today_iso)).fetchone()
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("### 🕒 Sljedeća Smjena")
            if next_shift:
                d = date.fromisoformat(next_shift['datum'])
                dan_u_tjednu = ["Pon", "Uto", "Sri", "Čet", "Pet", "Sub", "Ned"][d.weekday()]
                st.metric(label=f"{dan_u_tjednu}, {d.strftime('%d.%m.')}", value=next_shift['opis_smjene'])
            else:
                st.info("Nema rasporeda.")

        # 2. GODIŠNJI ODMOR
        go_data = conn.execute("SELECT dostupni_dani, iskorišteni_dani FROM godisnji_odmori WHERE radnik_id=? AND godina=?", (radnik_id, date.today().year)).fetchone()
        with col2:
            st.markdown("### 🏖️ Godišnji Odmor")
            if go_data:
                preostalo = go_data['dostupni_dani'] - go_data['iskorišteni_dani']
                st.metric("Preostalo dana", f"{preostalo}", delta=f"Ukupno: {go_data['dostupni_dani']}")
            else:
                st.metric("Preostalo", "N/A")

        # 3. PREKOVREMENI (Ovaj mjesec)
        first_day = date.today().replace(day=1).isoformat()
        ot_data = conn.execute("SELECT SUM(sati) as s FROM prekovremeni WHERE radnik_id=? AND datum >= ?", (radnik_id, first_day)).fetchone()
        with col3:
            st.markdown("### 💰 Prekovremeni (Mj.)")
            st.metric("Sati", f"{ot_data['s'] or 0} h")

        st.markdown("---")
        st.subheader("📅 Moji Eventi (Sektor)")
        
        # Prikaz evenata samo za moj sektor
        if user_sektor_id:
            # Dohvati sve planirane evente
            events = query_df("SELECT naziv, pocetak, opis, sektori_ids FROM events WHERE status='planirano' ORDER BY pocetak LIMIT 5")
            
            found_any = False
            if not events.empty:
                for _, e in events.iterrows():
                    # Robusna provjera sektora
                    raw_ids = e.get('sektori_ids')
                    event_sectors = []
                    if raw_ids and isinstance(raw_ids, str):
                        event_sectors = [s.strip() for s in raw_ids.split(',') if s.strip()]
                    
                    if str(user_sektor_id) in event_sectors:
                        found_any = True
                        dt = datetime.fromisoformat(e['pocetak'])
                        st.info(f"**{dt.strftime('%d.%m. %H:%M')}** - {e['naziv']}: {e['opis']}")
            
            if not found_any:
                st.caption("Nema nadolazećih evenata za vaš sektor.")

    # ---------------------------------------------------------
    # MANAGER DASHBOARD (Sektorski)
    # ---------------------------------------------------------
    elif role == 'manager':
        if not user_sektor_id:
            st.warning("Niste dodijeljeni nijednom sektoru.")
            return
            
        sektor_naziv = conn.execute("SELECT naziv FROM sektor WHERE id=?", (user_sektor_id,)).fetchone()['naziv']
        st.subheader(f"📊 Pregled Sektora: {sektor_naziv}")
        
        c1, c2, c3 = st.columns(3)
        
        # Broj radnika
        cnt = conn.execute("SELECT COUNT(*) as c FROM radnici WHERE sektor_id=? AND status_zaposlenja='aktivan'", (user_sektor_id,)).fetchone()['c']
        c1.metric("Broj Radnika", cnt)
        
        # Trošak plaća (Sektor)
        cost = conn.execute("""
            SELECT SUM(u.bruto) as b FROM ugovori u 
            JOIN radnici r ON u.radnik_id = r.id 
            WHERE r.sektor_id=? AND u.kraj IS NULL
        """, (user_sektor_id,)).fetchone()['b']
        c2.metric("Mjesečni Trošak Plaća (Bruto)", f"{cost or 0:,.2f} €")
        
        # Bolovanja danas
        sick = conn.execute("""
            SELECT COUNT(*) as c FROM bolovanja b 
            JOIN radnici r ON b.radnik_id = r.id 
            WHERE r.sektor_id=? AND ? BETWEEN b.pocetak AND b.kraj
        """, (user_sektor_id, date.today().isoformat())).fetchone()['c']
        c3.metric("Na bolovanju danas", sick, delta_color="inverse")

    # ---------------------------------------------------------
    # ADMIN DASHBOARD (Globalni)
    # ---------------------------------------------------------
    elif role == 'admin':
        st.subheader("🏢 Globalni Pregled Hotela")
        
        # Financije
        fin = conn.execute("SELECT SUM(bruto) as b FROM ugovori WHERE kraj IS NULL").fetchone()['b']
        
        ac1, ac2, ac3 = st.columns(3)
        ac1.metric("Ukupno Zaposlenih", conn.execute("SELECT COUNT(*) as c FROM radnici").fetchone()['c'])
        ac2.metric("Ukupni Trošak Plaća", f"{fin or 0:,.2f} €")
        ac3.metric("Aktivni Eventi", conn.execute("SELECT COUNT(*) as c FROM events WHERE status='planirano'").fetchone()['c'])

    conn.close()