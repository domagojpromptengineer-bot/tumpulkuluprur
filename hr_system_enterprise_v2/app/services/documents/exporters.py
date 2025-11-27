import json

def generate_joppd_xml(employer_oib, year, month, items):
    header = f"<zaglavlje><poslodavac_oib>{employer_oib}</poslodavac_oib><godina>{year}</godina><mjesec>{month}</mjesec></zaglavlje>"
    body = ""
    for it in items:
        body += f"<zaposlenik><oib>{it['oib']}</oib><joppd_sifra>{it.get('sifra','')}</joppd_sifra><iznos>{it.get('amount','0.00')}</iznos><opis>{it.get('description','')}</opis></zaposlenik>"
    xml = f"<?xml version='1.0' encoding='UTF-8'?><joppd>{header}{body}</joppd>"
    return xml

def hzmo_template_json(action, employer_oib, employee):
    payload = {
        "action": action,
        "employer_oib": employer_oib,
        "employee": employee
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)