#!/usr/bin/env python3
"""
Aanbiedingwekker – kijkt elke dag op Folderz.nl of producten van je lijstje
in de aanbieding zijn bij de winkels die je hebt gekozen, en stuurt je dan een e-mail.

Bestanden in deze map:
  watchlist.json   – je lijstje (wordt bijgehouden via de webpagina)
  resultaten.json  – wat er bij de laatste controle gevonden is (de webpagina toont dit)
  gezien.json      – onthoudt welke aanbiedingen al gemaild zijn, zodat je geen dubbele mails krijgt

E-mail instellingen komen uit GitHub Secrets:
  MAIL_USER  – je Gmail-adres
  MAIL_PASS  – een Gmail app-wachtwoord (niet je gewone wachtwoord)
  MAIL_TO    – (optioneel) naar welk adres de mail moet; anders naar MAIL_USER

Testen zonder internet:  python checker.py --offline map_met_html --dry-run
"""

import argparse
import html
import json
import os
import re
import smtplib
import ssl
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    NL = ZoneInfo("Europe/Amsterdam")
except Exception:  # pragma: no cover
    NL = timezone(timedelta(hours=1))

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
BASE = "https://www.folderz.nl"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9",
}
MAX_PAGINAS = 15          # per winkel, ruim genoeg voor een folder
PAUZE = 1.5               # seconden tussen verzoeken, om Folderz niet te belasten
VERGEET_NA_DAGEN = 90     # na hoeveel dagen een gemailde aanbieding weer "nieuw" mag zijn
FOUT_MAIL_INTERVAL = 7    # dagen: niet vaker dan dit een mail over een winkel die niet lukt

OFFER_HREF = re.compile(
    r"^(?:https?://www\.folderz\.nl)?/winkels/(?P<winkel>[^/]+)/aanbiedingen/"
    r"(?P<slug>[^/?#]+)-(?P<id>\d+)/?(?:[?#].*)?$"
)
PRIJS = re.compile(r"€\s*(\d+(?:[.,]\d{1,2})?)")
ACTIE = re.compile(
    r"(\d+\s*\+\s*\d+\s*gratis|\d+\s*%\s*korting|\d+e\s+halve\s+prijs|\d+e\s+gratis|"
    r"\d+\s+voor\s+€?\s*\d+(?:[.,]\d{1,2})?|halve\s+prijs|gratis\s+bezorging)",
    re.IGNORECASE,
)
GELDIG = re.compile(
    r"(vanaf\s+morgen\s+geldig|vanaf\s+\S+\s+geldig|nog\s+\d+\s+\w+\s+geldig|"
    r"\d+\s+(?:uur|dag|dagen|week|weken|maand|maanden)\b|bijna\s+geldig)",
    re.IGNORECASE,
)


# ───────────────────────── hulpjes ─────────────────────────

def lees_json(naam, standaard):
    pad = ROOT / naam
    if not pad.exists():
        return standaard
    try:
        return json.loads(pad.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Let op: {naam} is geen geldige JSON ({e}); ik gebruik een lege versie.")
        return standaard


def schrijf_json(naam, data):
    (ROOT / naam).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def normaal(tekst):
    """kleine letters, zonder accenten, alleen letters/cijfers en spaties."""
    t = unicodedata.normalize("NFKD", tekst or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"[^a-z0-9%+]+", " ", t)
    return t.strip()


def naar_getal(s):
    try:
        return float(str(s).replace(",", "."))
    except (TypeError, ValueError):
        return None


def euro(x):
    if x is None:
        return ""
    return "€ " + f"{x:.2f}".replace(".", ",")


def nu_nl():
    return datetime.now(NL)


# ───────────────────────── Folderz uitlezen ─────────────────────────

def haal_pagina(url, offline_dir=None, winkel=None, pagina=1):
    if offline_dir:
        naam = f"{winkel}.html" if pagina == 1 else f"{winkel}-{pagina}.html"
        pad = Path(offline_dir) / naam
        return pad.read_text(encoding="utf-8") if pad.exists() else None
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.text


def lees_aanbiedingen(html_tekst, winkel_slug, winkel_naam):
    """Zoekt alle aanbieding-links van deze winkel op een Folderz-pagina."""
    soup = BeautifulSoup(html_tekst, "html.parser")
    gevonden = {}
    for a in soup.find_all("a", href=True):
        m = OFFER_HREF.match(a["href"].strip())
        if not m or m.group("winkel") != winkel_slug:
            continue
        aid = m.group("id")
        tekst = a.get_text(" ", strip=True)

        # productnaam: liefst uit het title-attribuut ("Jumbo Hak aanbieding")
        titel = (a.get("title") or "").strip()
        if not titel:
            img = a.find("img", alt=True)
            titel = (img["alt"] if img else "").strip()
        if not titel:
            titel = m.group("slug").replace("-", " ")
        titel = re.sub(r"\s+aanbieding$", "", titel, flags=re.IGNORECASE).strip()
        for voorvoegsel in (winkel_naam, winkel_slug.replace("-", " ")):
            if voorvoegsel and titel.lower().startswith(voorvoegsel.lower() + " "):
                titel = titel[len(voorvoegsel) + 1:].strip()
                break

        prijzen = [naar_getal(p) for p in PRIJS.findall(tekst)]
        prijzen = [p for p in prijzen if p is not None]
        prijs = prijzen[-1] if prijzen else None
        oud = prijzen[-2] if len(prijzen) >= 2 and prijzen[-2] > prijzen[-1] else None

        actie = ACTIE.search(tekst)
        geldig = GELDIG.search(tekst)

        url = a["href"]
        if url.startswith("/"):
            url = BASE + url

        item = {
            "id": aid,
            "winkel": winkel_slug,
            "winkel_naam": winkel_naam,
            "titel": titel,
            "prijs": prijs,
            "oud": oud,
            "actie": actie.group(1) if actie else "",
            "geldig": geldig.group(1) if geldig else "",
            "url": url.split("?")[0],
        }
        # dezelfde aanbieding kan vaker op een pagina staan; bewaar de meest complete
        vorige = gevonden.get(aid)
        if not vorige or sum(bool(v) for v in item.values()) > sum(bool(v) for v in vorige.values()):
            gevonden[aid] = item
    return gevonden


def haal_winkel(slug, naam, offline_dir=None):
    """Alle aanbiedingen van één winkel. Geeft (lijst, foutmelding) terug."""
    alles = {}
    pogingen = [
        f"{BASE}/winkels/{slug}/aanbiedingen",
        f"{BASE}/winkels/{slug}/folders-aanbiedingen",
    ]
    laatste_fout = ""
    for basis_url in pogingen:
        for pagina in range(1, MAX_PAGINAS + 1):
            url = basis_url if pagina == 1 else f"{basis_url}?page={pagina}"
            try:
                tekst = haal_pagina(url, offline_dir, slug, pagina)
            except Exception as e:  # netwerk / blokkade
                laatste_fout = f"{type(e).__name__}: {e}"
                break
            if not tekst:
                break
            nieuw = lees_aanbiedingen(tekst, slug, naam)
            erbij = {k: v for k, v in nieuw.items() if k not in alles}
            alles.update(erbij)
            if not erbij:
                break
            if not offline_dir:
                time.sleep(PAUZE)
        if alles:
            break
        if offline_dir:
            break
    if not alles and not laatste_fout:
        laatste_fout = "Geen aanbiedingen gevonden op de pagina (misschien is Folderz veranderd)."
    return list(alles.values()), ("" if alles else laatste_fout)


# ───────────────────────── vergelijken met je lijstje ─────────────────────────

def varianten(product):
    bron = product.get("zoekwoorden") or product.get("naam") or ""
    uit = []
    for v in bron.split(","):
        woorden = normaal(v).split()
        if woorden:
            uit.append(woorden)
    return uit


def past_bij(product, aanbieding):
    woorden_titel = normaal(aanbieding["titel"]).split()
    for variant in varianten(product):
        if all(any(w.startswith(z) for w in woorden_titel) for z in variant):
            max_prijs = naar_getal(product.get("maxPrijs"))
            if max_prijs is not None and aanbieding["prijs"] is not None and aanbieding["prijs"] > max_prijs:
                return False
            return True
    return False


# ───────────────────────── e-mail ─────────────────────────

def maak_mail(nieuw_gevonden, fouten):
    namen = []
    for g in nieuw_gevonden:
        if g["product_naam"] not in namen:
            namen.append(g["product_naam"])

    if namen:
        onderwerp = "Aanbieding: " + ", ".join(namen)
        if len(onderwerp) > 110:
            onderwerp = onderwerp[:107].rsplit(",", 1)[0] + " en meer"
    else:
        onderwerp = "Aanbiedingwekker: een winkel lukte niet"

    # tekstversie
    regels = []
    for naam in namen:
        regels.append(naam.upper())
        for g in [x for x in nieuw_gevonden if x["product_naam"] == naam]:
            prijs = euro(g["prijs"])
            if g["oud"]:
                prijs = f"{euro(g['oud'])} → {prijs}"
            extra = " · ".join(x for x in (g["actie"], g["geldig"]) if x)
            regels.append(f"  {g['winkel_naam']}: {g['titel']}  {prijs}  {extra}".rstrip())
            regels.append(f"  {g['url']}")
        regels.append("")
    if fouten:
        regels.append("Deze winkels kon ik vandaag niet uitlezen:")
        for slug, f in fouten.items():
            regels.append(f"  {slug}: {f}")
    tekst = "\n".join(regels)

    # html-versie
    blokken = []
    for naam in namen:
        kaarten = []
        for g in [x for x in nieuw_gevonden if x["product_naam"] == naam]:
            prijs = f"<strong style='font-size:17px;color:#2f5d50'>{html.escape(euro(g['prijs']))}</strong>"
            if g["oud"]:
                prijs = (f"<span style='text-decoration:line-through;color:#9a8f86'>"
                         f"{html.escape(euro(g['oud']))}</span> " + prijs)
            labels = ""
            if g["actie"]:
                labels += (f"<span style='background:#f6e3c8;color:#7a4b12;border-radius:6px;"
                           f"padding:2px 7px;font-size:12px;margin-right:6px'>{html.escape(g['actie'])}</span>")
            if g["geldig"]:
                labels += f"<span style='color:#7d746c;font-size:12px'>{html.escape(g['geldig'])}</span>"
            kaarten.append(f"""
            <tr><td style="padding:12px 14px;border-top:1px solid #eee6dc">
              <div style="font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:#a0522d">{html.escape(g['winkel_naam'])}</div>
              <div style="font-size:15px;color:#2b2622;margin:2px 0 6px">{html.escape(g['titel'])}</div>
              <div>{prijs}</div>
              <div style="margin-top:6px">{labels}</div>
              <div style="margin-top:8px"><a href="{html.escape(g['url'])}" style="color:#2f5d50">Bekijk aanbieding →</a></div>
            </td></tr>""")
        blokken.append(f"""
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
               style="background:#fff;border:1px solid #eee6dc;border-radius:12px;margin:0 0 16px;overflow:hidden">
          <tr><td style="padding:12px 14px;background:#faf6f0;font-weight:600;color:#2b2622">{html.escape(naam)}</td></tr>
          {''.join(kaarten)}
        </table>""")
    fout_html = ""
    if fouten:
        items = "".join(f"<li><b>{html.escape(s)}</b>: {html.escape(f)}</li>" for s, f in fouten.items())
        fout_html = (f"<div style='background:#fdf0ec;border-radius:10px;padding:10px 14px;color:#7a3324;"
                     f"font-size:13px'>Deze winkels kon ik niet uitlezen:<ul style='margin:6px 0 0 18px;padding:0'>{items}</ul></div>")
    html_body = f"""<!doctype html><html><body style="margin:0;background:#f4efe8;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif">
      <div style="max-width:560px;margin:0 auto;padding:22px 16px">
        <div style="font-size:20px;font-weight:600;color:#2b2622;margin-bottom:4px">Van je lijstje in de aanbieding</div>
        <div style="font-size:13px;color:#7d746c;margin-bottom:18px">{nu_nl().strftime('%d-%m-%Y')}</div>
        {''.join(blokken)}
        {fout_html}
        <div style="font-size:12px;color:#9a8f86;margin-top:18px">Verstuurd door je Aanbiedingwekker. Prijzen en geldigheid zoals op Folderz.nl.</div>
      </div></body></html>"""
    return onderwerp, tekst, html_body


def verstuur_mail(onderwerp, tekst, html_body, dry_run=False, voorbeeld_pad=None):
    if voorbeeld_pad:
        Path(voorbeeld_pad).write_text(html_body, encoding="utf-8")
    gebruiker = os.environ.get("MAIL_USER", "").strip()
    wachtwoord = os.environ.get("MAIL_PASS", "").replace(" ", "").strip()
    naar = os.environ.get("MAIL_TO", "").strip() or gebruiker
    if dry_run or not gebruiker or not wachtwoord:
        print(f"[geen mail verstuurd{' (dry-run)' if dry_run else ': MAIL_USER/MAIL_PASS ontbreken'}]")
        print("Onderwerp:", onderwerp)
        print(tekst)
        return False
    msg = EmailMessage()
    msg["Subject"] = onderwerp
    msg["From"] = f"Aanbiedingwekker <{gebruiker}>"
    msg["To"] = naar
    msg.set_content(tekst)
    msg.add_alternative(html_body, subtype="html")
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    poort = int(os.environ.get("SMTP_PORT", "465"))
    with smtplib.SMTP_SSL(host, poort, context=ssl.create_default_context()) as s:
        s.login(gebruiker, wachtwoord)
        s.send_message(msg)
    print(f"Mail verstuurd naar {naar}: {onderwerp}")
    return True


# ───────────────────────── hoofdprogramma ─────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", help="map met opgeslagen Folderz-pagina's (winkel.html) om te testen")
    ap.add_argument("--dry-run", action="store_true", help="niets mailen, alleen laten zien")
    ap.add_argument("--voorbeeld-mail", help="sla de html van de mail op in dit bestand")
    args = ap.parse_args()

    lijst = lees_json("watchlist.json", {"winkels": [], "producten": []})
    gezien = lees_json("gezien.json", {"aanbiedingen": {}, "fout_gemeld": {}})
    gezien.setdefault("aanbiedingen", {})
    gezien.setdefault("fout_gemeld", {})

    winkel_namen = {w["slug"]: w.get("naam") or w["slug"] for w in lijst.get("winkels", [])}
    producten = [p for p in lijst.get("producten", []) if p.get("naam")]
    nodig = []
    for p in producten:
        for slug in p.get("winkels", []):
            if slug not in nodig:
                nodig.append(slug)

    print(f"{len(producten)} producten, {len(nodig)} winkels om te bekijken: {', '.join(nodig) or '-'}")

    per_winkel, status, fouten = {}, {}, {}
    for slug in nodig:
        naam = winkel_namen.get(slug, slug)
        items, fout = haal_winkel(slug, naam, args.offline)
        per_winkel[slug] = items
        status[slug] = {"naam": naam, "ok": not fout, "aantal": len(items), "fout": fout}
        print(f"  {naam}: {len(items)} aanbiedingen{' – FOUT: ' + fout if fout else ''}")
        if fout:
            fouten[naam] = fout

    vandaag = nu_nl()
    gevonden, nieuw_voor_mail = [], []
    for p in producten:
        for slug in p.get("winkels", []):
            for a in per_winkel.get(slug, []):
                if not past_bij(p, a):
                    continue
                sleutel = f"{p.get('id')}:{a['winkel']}:{a['id']}"
                is_nieuw = sleutel not in gezien["aanbiedingen"]
                rij = dict(a, product_id=p.get("id"), product_naam=p["naam"],
                           melding=bool(p.get("melding", True)), nieuw=is_nieuw)
                gevonden.append(rij)
                if is_nieuw:
                    gezien["aanbiedingen"][sleutel] = vandaag.date().isoformat()
                    if rij["melding"]:
                        nieuw_voor_mail.append(rij)

    # oude 'gezien' opruimen
    grens = (vandaag - timedelta(days=VERGEET_NA_DAGEN)).date().isoformat()
    gezien["aanbiedingen"] = {k: v for k, v in gezien["aanbiedingen"].items() if v >= grens}

    # winkels die niet lukten: hooguit eens per week melden
    fouten_te_melden = {}
    for naam, f in fouten.items():
        laatst = gezien["fout_gemeld"].get(naam)
        if nieuw_voor_mail or not laatst or laatst <= (vandaag - timedelta(days=FOUT_MAIL_INTERVAL)).date().isoformat():
            fouten_te_melden[naam] = f
            gezien["fout_gemeld"][naam] = vandaag.date().isoformat()
    for naam in list(gezien["fout_gemeld"]):
        if naam not in fouten:
            del gezien["fout_gemeld"][naam]

    print(f"{len(gevonden)} treffers, waarvan {len(nieuw_voor_mail)} nieuw met melding aan.")

    if nieuw_voor_mail or fouten_te_melden:
        onderwerp, tekst, html_body = maak_mail(nieuw_voor_mail, fouten_te_melden)
        verstuur_mail(onderwerp, tekst, html_body, args.dry_run, args.voorbeeld_mail)

    gevonden.sort(key=lambda g: (g["product_naam"].lower(), g["winkel_naam"].lower(), g["prijs"] or 0))
    schrijf_json("resultaten.json", {
        "bijgewerkt": vandaag.isoformat(timespec="minutes"),
        "winkels": status,
        "gevonden": gevonden,
    })
    if not args.dry_run:
        schrijf_json("gezien.json", gezien)


if __name__ == "__main__":
    sys.exit(main())
