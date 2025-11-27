import sqlite3
import os
import json
import secrets
import hashlib
import re
from datetime import datetime
import pandas as pd
from io import BytesIO
import streamlit as st

# ---------- Configuration ----------
APP_DIR = os.path.join(os.getcwd(), "hr_demo_data")
os.makedirs(APP_DIR, exist_ok=True)
DB_PATH = os.path.join(APP_DIR, "hr_demo.sqlite")
INTEGRATIONS_DIR = os.path.join(APP_DIR, "integrations")
os.makedirs(INTEGRATIONS_DIR, exist_ok=True)

# PBKDF2 parameters
HASH_NAME = "sha256"
ITERATIONS = 200_000
SALT_SIZE = 16

def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def pbkdf2_hash(password: str, salt: bytes = None):
    if salt is None:
        salt = secrets.token_bytes(SALT_SIZE)
    key = hashlib.pbkdf2_hmac(HASH_NAME, password.encode("utf-8"), salt, ITERATIONS)
    return salt.hex() + "$" + key.hex()

def pbkdf2_verify(password: str, stored: str) -> bool:
    try:
        salt_hex, key_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
        new_key = hashlib.pbkdf2_hmac(HASH_NAME, password.encode("utf-8"), salt, ITERATIONS)
        return secrets.compare_digest(new_key.hex(), key_hex)
    except Exception:
        return False

def now_iso():
    return datetime.utcnow().isoformat()

def log_action(user, action, details=None):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO audit_log (user, action, details, created_at) VALUES (?, ?, ?, ?)",
            (user or "anon", action, json.dumps(details, ensure_ascii=False) if details is not None else None, now_iso())
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Audit logging failed: {e}")

def validate_password(password: str) -> bool:
    if len(password) < 8:
        return False
    return True

def is_valid_oib(oib: str) -> bool:
    return bool(re.fullmatch(r'\d{11}', oib))

def is_valid_email(email: str) -> bool:
    return bool(re.fullmatch(r'[^@]+@[^@]+\.[^@]+', email))

def query_df(sql, params=()):
    conn = get_conn()
    try:
        df = pd.read_sql_query(sql, conn, params=params)
        return df
    except Exception as e:
        print(f"Query Error: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

def df_to_xlsx(df: pd.DataFrame, sheet_name="Sheet1") -> BytesIO:
    output = BytesIO()
    try:
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name=sheet_name)
            workbook = writer.book
            worksheet = writer.sheets[sheet_name]
            for i, col in enumerate(df.columns):
                column_len = df[col].astype(str).map(len).max()
                header_len = len(str(col))
                final_len = max(column_len, header_len)
                worksheet.set_column(i, i, final_len + 2)
    except ImportError:
        if 'xlsxwriter_warning_shown' not in st.session_state:
            st.error("Molimo instalirajte 'xlsxwriter' za punu funkcionalnost Excel izvoza: pip install xlsxwriter")
            st.session_state.xlsxwriter_warning_shown = True
        df.to_excel(output, index=False)
    output.seek(0)
    return output

def get_company_info():
    """Dohvaća podatke o tvrtki iz ai_config tablice kao rječnik."""
    conn = get_conn()
    try:
        conf_data = pd.read_sql_query("SELECT key, prompt_template FROM ai_config WHERE key LIKE 'company_%'", conn)
        return {row['key']: row['prompt_template'] for _, row in conf_data.iterrows()}
    except Exception:
        return {}
    finally:
        conn.close()

def get_position_rank(position_name):
    """Vraća numerički rang za sortiranje (Manji broj = Viša pozicija)."""
    name = str(position_name).lower()
    if "direktor" in name or "manager" in name or "voditelj" in name or "chef" in name or "maître" in name:
        return 1
    elif "recepcioner" in name or "kuhar" in name or "konobar" in name or "terapeut" in name:
        return 2
    elif "pomoćni" in name or "student" in name:
        return 3
    else:
        return 4

def send_notification(poruka, tip="info", user_id=None, target_role=None, target_sektor_id=None, link=None):
    """Šalje notifikaciju ciljanoj grupi ili korisniku s opcionalnim linkom."""
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO notifikacije (user_id, target_role, target_sektor_id, tip, poruka, link, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, target_role, target_sektor_id, tip, poruka, link, now_iso()))
        conn.commit()
    except Exception as e:
        print(f"Notification Error: {e}")
    finally:
        conn.close()

def init_db():
    """Inicijalizira SQLite bazu sa svim tablicama i seed podacima."""
    conn = get_conn()
    c = conn.cursor()
    
    c.executescript("""
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
    
    CREATE TABLE IF NOT EXISTS zahtjevi_go (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        radnik_id INTEGER,
        pocetak TEXT,
        kraj TEXT,
        dana INTEGER,
        status TEXT DEFAULT 'na čekanju',
        created_at TEXT
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
        target_role TEXT,
        target_sektor_id INTEGER,
        tip TEXT,
        poruka TEXT,
        link TEXT,
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
    
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        naziv TEXT,
        tip_eventa TEXT,
        pocetak TEXT,
        kraj TEXT,
        opis TEXT,
        sektori_ids TEXT,
        sektor_id INTEGER,
        status TEXT DEFAULT 'planirano'
    );
    """)
    
    # --- AUTOMATSKA MIGRACIJA (Popravak postojećih baza) ---
    try:
        c.execute("SELECT link FROM notifikacije LIMIT 1")
    except:
        try:
            c.execute("ALTER TABLE notifikacije ADD COLUMN link TEXT")
        except: pass

    try:
        c.execute("SELECT target_role FROM notifikacije LIMIT 1")
    except:
        try:
            c.execute("ALTER TABLE notifikacije ADD COLUMN target_role TEXT")
            c.execute("ALTER TABLE notifikacije ADD COLUMN target_sektor_id INTEGER")
        except: pass

    try:
        c.execute("SELECT sektori_ids FROM events LIMIT 1")
    except:
        try:
            c.execute("ALTER TABLE events ADD COLUMN sektori_ids TEXT")
        except: pass

    # Seed Admin
    cur = c.execute("SELECT COUNT(*) as cnt FROM users")
    if cur.fetchone()["cnt"] == 0:
        ph = pbkdf2_hash("Admin123!")
        c.execute("INSERT INTO users (username,password_hash,role,created_at) VALUES (?, ?, ?, ?)", ("admin", ph, "admin", now_iso()))
        
    # Seed AI Config
    cur = c.execute("SELECT COUNT(*) as cnt FROM ai_config")
    if cur.fetchone()["cnt"] == 0:
        c.execute("INSERT OR IGNORE INTO ai_config (key, prompt_template) VALUES (?, ?)", ("schedule_generation", "Ti si AI planer..."))
        c.execute("INSERT OR IGNORE INTO ai_config (key, prompt_template) VALUES (?, ?)", ("company_name", "Grand Hotel Demo"))
        
    conn.commit()
    conn.close()

# --- HOTEL SEED DATA GENERATOR ---
import random

def seed_hotel_data():
    """
    Briše postojeće podatke i puni bazu za VELIKI HOTEL:
    - 7 Sektora
    - 20+ Pozicija
    - 50+ Radnika
    - Realistične smjene i ugovori
    """
    conn = get_conn()
    c = conn.cursor()

    print("--- POČETAK GENERIRANJA HOTELSKIH PODATAKA ---")

    # 1. ČIŠĆENJE POSTOJEĆIH PODATAKA (Oprez!)
    tables = ["radnici", "ugovori", "sektor", "pozicije", "smjene", "radno_vrijeme", "prekovremeni", "bolovanja", "godisnji_odmori", "rasporedi", "events", "zahtjevi_go", "notifikacije"]
    for t in tables:
        try:
            c.execute(f"DELETE FROM {t}")
            c.execute(f"DELETE FROM sqlite_sequence WHERE name='{t}'") # Reset ID countera
        except: pass
    print("Stari podaci obrisani.")

    # 2. DEFINICIJA SEKTORA I SMJENA
    hotel_structure = [
        ("Recepcija", [("Jutarnja", "07:00", "15:00"), ("Popodnevna", "15:00", "23:00"), ("Noćna", "23:00", "07:00")]),
        ("Domaćinstvo", [("Jutarnja", "06:00", "14:00"), ("Dnevna", "08:00", "16:00"), ("Popodnevna", "14:00", "22:00")]),
        ("Kuhinja", [("Doručak", "05:00", "13:00"), ("Priprema", "09:00", "17:00"), ("Večera", "15:00", "23:00")]),
        ("Restoran i Bar", [("Jutarnja", "06:30", "14:30"), ("Međusmjena", "11:00", "19:00"), ("Večernja", "16:00", "24:00")]),
        ("Održavanje", [("Prva", "07:00", "15:00"), ("Druga", "14:00", "22:00")]),
        ("Wellness & Spa", [("Cijeli dan", "09:00", "17:00"), ("Kasna", "13:00", "21:00")]),
        ("Uprava", [("Uredsko", "08:00", "16:00")])
    ]

    # 3. DEFINICIJA POZICIJA I BROJA RADNIKA
    staff_plan = {
        "Recepcija": [("Voditelj Recepcije", 1, 2200), ("Recepcioner", 6, 1400), ("Nosač prtljage (Bellboy)", 3, 1100)],
        "Domaćinstvo": [("Voditeljica Domaćinstva", 1, 1800), ("Sobarica", 12, 1200), ("Čistačica", 4, 1100)],
        "Kuhinja": [("Executive Chef", 1, 3500), ("Sous Chef", 2, 2400), ("Kuhar", 6, 1600), ("Pomoćni kuhar", 4, 1300), ("Perač suđa", 5, 1100)],
        "Restoran i Bar": [("Voditelj Sale (Maître d')", 1, 2000), ("Konobar", 10, 1300), ("Barmen", 4, 1400), ("Servir", 2, 1100)],
        "Održavanje": [("Voditelj Održavanja", 1, 2100), ("Domar", 4, 1350)],
        "Wellness & Spa": [("Fizioterapeut / Maser", 4, 1500), ("Recepcioner Wellnessa", 2, 1250)],
        "Uprava": [("Generalni Direktor", 1, 4500), ("HR Manager", 1, 2500), ("Voditelj Prodaje", 1, 2400)]
    }

    imena = ["Ivan", "Marko", "Ana", "Marija", "Petar", "Josip", "Ivana", "Tomislav", "Katarina", "Luka", "Ante", "Željka", "Davor", "Maja", "Filip", "Stjepan", "Nikola", "Marina", "Kristina", "Zoran", "Goran", "Sanja", "Robert", "Damir", "Igor", "Vlatka", "Branko", "Snježana", "Mario", "Dario"]
    prezimena = ["Horvat", "Kovač", "Babić", "Marić", "Jurić", "Novak", "Kovačić", "Vuković", "Knežević", "Marković", "Petrović", "Matić", "Božić", "Pavlović", "Rukavina", "Blažević", "Grgić", "Pavić", "Radić", "Šarić", "Lovrić", "Vidović", "Perić", "Tokić", "Jukić"]
    used_oibs = set()

    def gen_oib():
        while True:
            oib = "".join([str(random.randint(0, 9)) for _ in range(11)])
            if oib not in used_oibs:
                used_oibs.add(oib)
                return oib

    for sektor_naziv, smjene_list in hotel_structure:
        c.execute("INSERT INTO sektor (naziv) VALUES (?)", (sektor_naziv,))
        sektor_id = c.lastrowid
        for naziv_smjene, start, end in smjene_list:
            c.execute("INSERT INTO smjene (sektor_id, naziv_smjene, pocetak, kraj) VALUES (?, ?, ?, ?)", (sektor_id, naziv_smjene, f"{start}:00", f"{end}:00"))

        if sektor_naziv in staff_plan:
            for pozicija_naziv, count, bruto in staff_plan[sektor_naziv]:
                c.execute("INSERT INTO pozicije (sektor_id, naziv_pozicije) VALUES (?, ?)", (sektor_id, pozicija_naziv))
                pozicija_id = c.lastrowid
                for _ in range(count):
                    ime = random.choice(imena)
                    prezime = random.choice(prezimena)
                    oib = gen_oib()
                    email = f"{ime.lower()}.{prezime.lower()}@hotel-demo.hr"
                    c.execute("""INSERT INTO radnici (ime, prezime, oib, adresa, kontakt_tel, email, status_zaposlenja, sektor_id, pozicija_id, datum_zaposlenja) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (ime, prezime, oib, "Ulica Hotela 1, Zagreb", "091/123-4567", email, "aktivan", sektor_id, pozicija_id, "2023-01-01"))
                    radnik_id = c.lastrowid
                    neto = bruto * 0.72
                    c.execute("""INSERT INTO ugovori (radnik_id, tip_ugovora, pocetak, bruto, neto, created_at) VALUES (?, ?, ?, ?, ?, ?)""", (radnik_id, "na neodređeno", "2023-01-01", bruto, neto, now_iso()))
                    c.execute("INSERT INTO godisnji_odmori (radnik_id, godina, dostupni_dani, iskorišteni_dani) VALUES (?, ?, ?, ?)", (radnik_id, 2024, 24, random.randint(0, 10)))

    conn.commit()
    conn.close()
    print("--- USPJEŠNO GENERIRANO: Veliki Hotel Database ---")