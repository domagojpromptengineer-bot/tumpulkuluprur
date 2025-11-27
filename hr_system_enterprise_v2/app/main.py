import streamlit as st
import os
import sys
import sqlite3

# --- KONFIGURACIJA SUSTAVA ---
st.set_page_config(
    page_title="HR Jetset",
    page_icon="✈️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Dodavanje direktorija aplikacije u path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- IMPORTS ---
from app.common.utils import init_db, get_conn, pbkdf2_verify, log_action, now_iso, pbkdf2_hash
from app.ui.pages import dashboard, employees, contracts, schedule, ai_assistant, admin, exports, audit, events

# ---------------------------------------------------------
# 1. INŽENJERSKA MIGRACIJA I INICIJALIZACIJA BAZE
# ---------------------------------------------------------
def check_column_exists(cursor, table_name, column_name):
    """Pomoćna funkcija za provjeru postojanja stupca u SQLite tablici."""
    try:
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [info[1] for info in cursor.fetchall()]
        return column_name in columns
    except Exception:
        return False

def run_robust_migration():
    """
    Izvodi strukturne promjene na bazi podataka na siguran (idempotent) način.
    Provjerava metapodatke prije izmjene sheme.
    """
    conn = get_conn()
    c = conn.cursor()
    
    try:
        # 1. Tablica NOTIFIKACIJE - Provjera i dodavanje stupaca
        if not check_column_exists(c, "notifikacije", "target_role"):
            c.execute("ALTER TABLE notifikacije ADD COLUMN target_role TEXT")
        
        if not check_column_exists(c, "notifikacije", "target_sektor_id"):
            c.execute("ALTER TABLE notifikacije ADD COLUMN target_sektor_id INTEGER")
            
        if not check_column_exists(c, "notifikacije", "link"):
            c.execute("ALTER TABLE notifikacije ADD COLUMN link TEXT")

        # 2. Tablica EVENTS - Provjera i dodavanje stupaca
        if not check_column_exists(c, "events", "sektori_ids"):
            c.execute("ALTER TABLE events ADD COLUMN sektori_ids TEXT")
            
        if not check_column_exists(c, "events", "sektor_id"):
            c.execute("ALTER TABLE events ADD COLUMN sektor_id INTEGER")

        # 3. Tablica ZAHTJEVI_GO - Kreiranje ako ne postoji
        c.execute("""
        CREATE TABLE IF NOT EXISTS zahtjevi_go (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            radnik_id INTEGER,
            pocetak TEXT,
            kraj TEXT,
            dana INTEGER,
            status TEXT DEFAULT 'na čekanju',
            created_at TEXT,
            FOREIGN KEY(radnik_id) REFERENCES radnici(id)
        );
        """)

        conn.commit()
    except sqlite3.Error as e:
        st.error(f"Critical Database Migration Error: {e}")
    finally:
        conn.close()

def init_db_schema():
    """Inicijalizira osnovnu shemu baze podataka i seeda defaultne vrijednosti."""
    conn = get_conn()
    c = conn.cursor()
    
    # Definicija tablica (Schema Definition)
    schema_script = """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password_hash TEXT,
        role TEXT,
        radnik_id INTEGER,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS sektor (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naziv TEXT UNIQUE
    );
    CREATE TABLE IF NOT EXISTS pozicije (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sektor_id INTEGER,
        naziv_pozicije TEXT
    );
    CREATE TABLE IF NOT EXISTS smjene (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sektor_id INTEGER,
        naziv_smjene TEXT,
        pocetak TEXT,
        kraj TEXT
    );
    CREATE TABLE IF NOT EXISTS radnici (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ime TEXT,
        prezime TEXT,
        oib TEXT UNIQUE,
        adresa TEXT,
        kontakt_tel TEXT,
        email TEXT,
        status_zaposlenja TEXT,
        sektor_id INTEGER,
        pozicija_id INTEGER,
        datum_zaposlenja TEXT,
        datum_raskida TEXT,
        pseudonimiziran INTEGER DEFAULT 0,
        deleted_at TEXT
    );
    CREATE TABLE IF NOT EXISTS ugovori (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        radnik_id INTEGER,
        tip_ugovora TEXT,
        pocetak TEXT,
        kraj TEXT,
        bruto REAL,
        neto REAL,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS radno_vrijeme (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        radnik_id INTEGER,
        datum TEXT,
        dolazak TEXT,
        odlazak TEXT,
        source TEXT DEFAULT 'kiosk',
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS prekovremeni (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        radnik_id INTEGER,
        datum TEXT,
        sati REAL,
        razlog TEXT,
        nadoknada REAL,
        odobreno INTEGER DEFAULT 0,
        odobrio INTEGER,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS godisnji_odmori (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        radnik_id INTEGER,
        godina INTEGER,
        dostupni_dani INTEGER DEFAULT 0,
        iskorišteni_dani INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS bolovanja (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        radnik_id INTEGER,
        pocetak TEXT,
        kraj TEXT,
        potvrda TEXT,
        status TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS rasporedi (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sektor_id INTEGER,
        radnik_id INTEGER,
        datum TEXT,
        opis_smjene TEXT,
        ai_recommended INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS notifikacije (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        tip TEXT,
        poruka TEXT,
        procitano INTEGER DEFAULT 0,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user TEXT,
        action TEXT,
        details TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS ai_config (
        key TEXT PRIMARY KEY,
        prompt_template TEXT,
        updated_at TEXT
    );
    """
    c.executescript(schema_script)
    conn.commit()
    
    # Seed Admin (Idempotent)
    cur = c.execute("SELECT COUNT(*) as cnt FROM users")
    if cur.fetchone()["cnt"] == 0:
        ph = pbkdf2_hash("Admin123!")
        c.execute("INSERT INTO users (username,password_hash,role,created_at) VALUES (?, ?, ?, ?)",
                  ("admin", ph, "admin", now_iso()))
        conn.commit()
        print("System: Admin user seeded.")
        
    # Seed AI Config (Idempotent)
    c.execute("INSERT OR IGNORE INTO ai_config (key, prompt_template) VALUES (?, ?)", ("turnover_prediction", "Analiziraj podatke o zaposleniku...",))
    c.execute("INSERT OR IGNORE INTO ai_config (key, prompt_template) VALUES (?, ?)", ("schedule_generation", "Generiraj raspored uzimajući u obzir...",))
    c.execute("INSERT OR IGNORE INTO ai_config (key, prompt_template) VALUES (?, ?)", ("company_name", "Moja Tvrtka d.o.o."))
    conn.commit()
    conn.close()

# Pokretanje inicijalizacije i migracija pri startu
init_db_schema()
run_robust_migration()

# ---------------------------------------------------------
# 2. SESSION STATE MANAGEMENT
# ---------------------------------------------------------
if "user" not in st.session_state:
    st.session_state.user = None
if "api_key" not in st.session_state:
    st.session_state.api_key = None
if "redirect_to" not in st.session_state:
    st.session_state.redirect_to = None

# ---------------------------------------------------------
# 3. AUTHENTICATION & SIDEBAR
# ---------------------------------------------------------
with st.sidebar:
    st.header("HR Jetset ✈️")
    
    if st.session_state.user is None:
        st.subheader("Prijava")
        with st.form("login_form"):
            username = st.text_input("Korisničko ime")
            password = st.text_input("Lozinka", type="password")
            submit_login = st.form_submit_button("Prijava")
            
            if submit_login:
                conn = get_conn()
                cur = conn.cursor()
                cur.execute("SELECT * FROM users WHERE username=?", (username,))
                row = cur.fetchone()
                conn.close()
                
                if row and pbkdf2_verify(password, row["password_hash"]):
                    st.session_state.user = {
                        "id": row["id"], 
                        "username": row["username"], 
                        "role": row["role"], 
                        "radnik_id": row["radnik_id"]
                    }
                    log_action(row["username"], "login", "Uspješna prijava")
                    st.success(f"Dobrodošli, {row['username']}!")
                    st.rerun()
                else:
                    st.error("Neispravni podaci.")
                    log_action(username, "login_failed", "Neuspješan pokušaj prijave")
    else:
        # User Info Panel
        st.info(f"👤 **{st.session_state.user['username']}**\n\n🏷️ {st.session_state.user['role'].upper()}")
        
        if st.button("Odjava", type="primary"):
            log_action(st.session_state.user['username'], "logout", "Odjava korisnika")
            st.session_state.user = None
            st.rerun()

    st.markdown("---")
    
    # AI Config Section (Secure)
    with st.expander("⚙️ AI Konfiguracija"):
        api_key_input = st.text_input("Google AI API Ključ", type="password", value=st.session_state.api_key if st.session_state.api_key else "")
        if api_key_input:
            st.session_state.api_key = api_key_input
            st.caption("✅ API ključ je postavljen")

# ---------------------------------------------------------
# 4. ROUTING & NAVIGATION
# ---------------------------------------------------------
choice = None

if st.session_state.user:
    role = st.session_state.user['role']
    
    # RBAC Menu Map
    menu_map = {
        "dash": "📊 Nadzorna ploča",
        "events": "📅 Eventi & Staffing",
        "emp": "👥 Zaposlenici",
        "contract": "📄 Ugovori",
        "schedule": "🕒 Evidencija i Raspored",
        "ai": "🤖 AI Asistent",
        "export": "📥 Izvoz",
        "audit": "🛡 Audit Log",
        "admin": "⚙️ Admin"
    }
    
    # Definiranje vidljivosti modula po rolama
    visible_keys = ["dash"] # Default
    if role == 'admin':
        visible_keys = list(menu_map.keys())
    elif role == 'manager':
        visible_keys = ["dash", "events", "emp", "schedule", "ai"]
    elif role == 'employee':
        visible_keys = ["dash", "schedule"]
        
    visible_labels = [menu_map[key] for key in visible_keys]
    
    # Logika redirekcije (Deep linking)
    default_index = 0
    if st.session_state.redirect_to:
        target = st.session_state.redirect_to
        st.session_state.redirect_to = None # Reset nakon čitanja
        target_label = menu_map.get(target)
        if target_label and target_label in visible_labels:
            default_index = visible_labels.index(target_label)

    # Top Navigation Bar
    st.markdown("<br>", unsafe_allow_html=True)
    col_nav1, col_nav2, col_nav3 = st.columns([1, 6, 1])
    
    with col_nav2:
        choice_label = st.selectbox(
            "Navigacija", 
            options=visible_labels, 
            index=default_index, 
            label_visibility="collapsed"
        )
    
    # Mapiranje odabira natrag u interni ključ
    if choice_label:
        choice = [key for key, label in menu_map.items() if label == choice_label][0]

else:
    st.warning("Molimo, prijavite se za pristup sustavu.")
    st.stop() # Prekini izvršavanje ako nema usera

# ---------------------------------------------------------
# 5. MODULE RENDERING
# ---------------------------------------------------------
# Dinamičko učitavanje modula
modules = {
    "dash": dashboard,
    "events": events,
    "emp": employees,
    "contract": contracts,
    "schedule": schedule,
    "ai": ai_assistant,
    "export": exports,
    "audit": audit,
    "admin": admin
}

if choice in modules:
    try:
        modules[choice].render(st.session_state.user['role'])
    except Exception as e:
        st.error(f"Greška pri učitavanju modula {choice}: {str(e)}")
        # Opcionalno: logirati grešku u audit log

# ---------------------------------------------------------
# 6. NOTIFICATION SYSTEM (POPOVER)
# ---------------------------------------------------------
def show_notifications_popover():
    conn = get_conn()
    user_id = st.session_state.user['id']
    role = st.session_state.user['role']
    
    user_sektor_id = None
    if st.session_state.user.get('radnik_id'):
        try:
            res = conn.execute("SELECT sektor_id FROM radnici WHERE id=?", (st.session_state.user['radnik_id'],)).fetchone()
            if res: user_sektor_id = res['sektor_id']
        except Exception: pass

    # Optimizirani Query
    if role == 'admin':
        query = """
            SELECT * FROM notifikacije 
            WHERE (user_id = ?) 
               OR (target_role = 'admin')
               OR (target_role IS NULL)
            ORDER BY created_at DESC LIMIT 50
        """
        params = (user_id,)
    else:
        query = """
            SELECT * FROM notifikacije 
            WHERE (user_id = ?) 
               OR (target_role = ? AND target_sektor_id IS NULL)
               OR (target_role = ? AND target_sektor_id = ?)
            ORDER BY created_at DESC LIMIT 20
        """
        params = (user_id, role, role, user_sektor_id)
    
    try:
        notifs = conn.execute(query, params).fetchall()
        unread_count = sum(1 for n in notifs if n['procitano'] == 0)
        label = f"🔔 {unread_count}" if unread_count > 0 else "🔔"
        
        with st.sidebar.popover(label):
            st.markdown("### Obavijesti")
            if not notifs:
                st.caption("Nema novih obavijesti.")
            else:
                with st.container(height=400):
                    for n in notifs:
                        # Vizualni indikator
                        is_unread = n['procitano'] == 0
                        icon = "🟡" if is_unread else "⚪"
                        
                        c1, c2 = st.columns([0.85, 0.15])
                        with c1:
                            st.markdown(f"{icon} **{n['tip']}**")
                            st.caption(f"{n['poruka']}")
                            st.caption(f"_{n['created_at'][:16]}_")
                        
                        with c2:
                            if n['link']:
                                if st.button("↗️", key=f"go_{n['id']}", help="Otvori"):
                                    conn.execute("UPDATE notifikacije SET procitano=1 WHERE id=?", (n['id'],))
                                    conn.commit()
                                    st.session_state.redirect_to = n['link']
                                    st.rerun()
                            elif is_unread:
                                if st.button("✔️", key=f"ok_{n['id']}", help="Označi kao pročitano"):
                                    conn.execute("UPDATE notifikacije SET procitano=1 WHERE id=?", (n['id'],))
                                    conn.commit()
                                    st.rerun()
                        
                        st.divider()
                
                if st.button("Očisti sve pročitano", use_container_width=True):
                    conn.execute("DELETE FROM notifikacije WHERE procitano=1 AND (user_id=? OR target_role=?)", (user_id, role))
                    conn.commit()
                    st.rerun()

    except Exception as e:
        st.error(f"Notification Error: {e}")
    finally:
        conn.close()

# Prikaz notifikacija samo ako je korisnik prijavljen
if st.session_state.user:
    show_notifications_popover()