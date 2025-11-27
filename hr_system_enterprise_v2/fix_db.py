# fix_db.py
import sqlite3
import os

# Putanja do baze
DB_PATH = os.path.join(os.getcwd(), "hr_demo_data", "hr_demo.sqlite")

def fix_database():
    print(f"Provjeravam bazu na: {DB_PATH}")
    
    if not os.path.exists(DB_PATH):
        print("Baza ne postoji! Pokrenite aplikaciju da se kreira.")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 1. KREIRANJE EVENTS TABLICE
    try:
        c.execute("SELECT count(*) FROM events")
        print("Tablica 'events' već postoji.")
    except sqlite3.OperationalError:
        print("Tablica 'events' nedostaje. Kreiram je...")
        c.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            naziv TEXT,
            tip_eventa TEXT,
            pocetak TEXT,
            kraj TEXT,
            opis TEXT,
            potrebno_osoblje TEXT,
            status TEXT DEFAULT 'planirano'
        );
        """)
        print("Tablica 'events' uspješno kreirana.")

    # 2. PROVJERA AI CONFIGA (Za podatke o tvrtki)
    keys = ['company_name', 'company_oib', 'company_address', 'company_director']
    for k in keys:
        c.execute("INSERT OR IGNORE INTO ai_config (key, prompt_template, updated_at) VALUES (?, ?, ?)", 
                  (k, "", "2024-01-01"))
    
    conn.commit()
    conn.close()
    print("✅ Baza je popravljena. Sada možete pokrenuti aplikaciju.")

if __name__ == "__main__":
    fix_database()