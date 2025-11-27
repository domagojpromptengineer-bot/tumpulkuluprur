import pandas as pd
from datetime import date
from app.common.utils import get_conn

class HRRepository:
    @staticmethod
    def get_employee_details(radnik_id):
        conn = get_conn()
        query = "SELECT ime, prezime, sektor_id FROM radnici WHERE id=?"
        return conn.execute(query, (radnik_id,)).fetchone()

    @staticmethod
    def get_next_shift(radnik_id):
        conn = get_conn()
        today = date.today().isoformat()
        query = """
            SELECT datum, opis_smjene FROM rasporedi 
            WHERE radnik_id = ? AND datum >= ? 
            ORDER BY datum ASC LIMIT 1
        """
        return conn.execute(query, (radnik_id, today)).fetchone()

    @staticmethod
    def get_leave_status(radnik_id, year):
        conn = get_conn()
        query = "SELECT dostupni_dani, iskorišteni_dani FROM godisnji_odmori WHERE radnik_id=? AND godina=?"
        return conn.execute(query, (radnik_id, year)).fetchone()

    @staticmethod
    def get_monthly_overtime(radnik_id):
        conn = get_conn()
        first_day = date.today().replace(day=1).isoformat()
        query = "SELECT SUM(sati) as s FROM prekovremeni WHERE radnik_id=? AND datum >= ?"
        return conn.execute(query, (radnik_id, first_day)).fetchone()

    @staticmethod
    def get_sector_events(sector_id):
        # Vraća DataFrame za lakšu manipulaciju
        conn = get_conn()
        query = "SELECT naziv, pocetak, opis, sektori_ids FROM events WHERE status='planirano' ORDER BY pocetak LIMIT 10"
        return pd.read_sql_query(query, conn)

    @staticmethod
    def get_sector_stats(sector_id):
        conn = get_conn()
        stats = {}
        
        # Broj radnika
        stats['count'] = conn.execute("SELECT COUNT(*) as c FROM radnici WHERE sektor_id=? AND status_zaposlenja='aktivan'", (sector_id,)).fetchone()['c']
        
        # Trošak
        stats['cost'] = conn.execute("""
            SELECT SUM(u.bruto) as b FROM ugovori u 
            JOIN radnici r ON u.radnik_id = r.id 
            WHERE r.sektor_id=? AND u.kraj IS NULL
        """, (sector_id,)).fetchone()['b'] or 0
        
        # Bolovanja
        today = date.today().isoformat()
        stats['sick'] = conn.execute("""
            SELECT COUNT(*) as c FROM bolovanja b 
            JOIN radnici r ON b.radnik_id = r.id 
            WHERE r.sektor_id=? AND ? BETWEEN b.pocetak AND b.kraj
        """, (sector_id, today)).fetchone()['c']
        
        return stats

    @staticmethod
    def get_global_stats():
        conn = get_conn()
        stats = {}
        stats['total_cost'] = conn.execute("SELECT SUM(bruto) as b FROM ugovori WHERE kraj IS NULL").fetchone()['b'] or 0
        stats['total_employees'] = conn.execute("SELECT COUNT(*) as c FROM radnici").fetchone()['c']
        stats['active_events'] = conn.execute("SELECT COUNT(*) as c FROM events WHERE status='planirano'").fetchone()['c']
        return stats