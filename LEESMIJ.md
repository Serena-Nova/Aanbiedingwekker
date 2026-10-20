# Aanbiedingwekker – zo zet je hem op

Eén keer instellen, daarna kijkt hij elke ochtend (rond 7:40, in de winter 6:40) op Folderz.nl en mailt je als iets van je lijstje in de aanbieding is. Duurt ongeveer 15 minuten.

## Wat zit erin

| Bestand | Wat het doet |
|---|---|
| `index.html` | Je pagina om het lijstje bij te houden en te zien wat er in de aanbieding is |
| `checker.py` | Het script dat Folderz bekijkt en de mail stuurt |
| `watchlist.json` | Je lijstje (met één voorbeeldproduct, dat kun je weghalen) |
| `.github/workflows/check.yml` | Zegt tegen GitHub: draai het script elke ochtend |
| `workflow-check.yml` | Een zichtbare kopie van hetzelfde bestand (zie stap 2) |

## 1. Nieuwe repository

Op je **SerenaNova**-account: *New repository* → naam `aanbiedingwekker` → **Public** (nodig voor gratis GitHub Pages). Vink "Add a README" aan zodat hij niet leeg is.

Je lijstje is dan zichtbaar voor wie de repository vindt. Je mailgegevens niet: die staan in de geheime instellingen.

## 2. Bestanden erin zetten

1. *Add file → Upload files* → sleep `index.html`, `checker.py` en `watchlist.json` erin → *Commit changes*.
2. De GitHub-taak moet in een map die op de Mac verborgen is, dus die maak je met de hand:
   *Add file → Create new file* → typ als naam precies `.github/workflows/check.yml` → plak de inhoud van `workflow-check.yml` → *Commit changes*.

## 3. Gmail app-wachtwoord

GitHub mag niet met je gewone Gmail-wachtwoord inloggen. Maak een apart wachtwoord:

1. Ga naar https://myaccount.google.com/apppasswords (tweestapsverificatie moet aan staan).
2. Naam: `Aanbiedingwekker` → *Maken*.
3. Je krijgt 16 letters. Kopieer ze; je ziet ze maar één keer.

## 4. Geheimen in GitHub zetten

In je repository: *Settings → Secrets and variables → Actions → New repository secret*. Maak er twee (of drie):

| Naam | Waarde |
|---|---|
| `MAIL_USER` | je Gmail-adres |
| `MAIL_PASS` | het app-wachtwoord van stap 3 |
| `MAIL_TO` | *(optioneel)* een ander adres waar de mail heen moet |

## 5. De pagina online zetten

*Settings → Pages* → Source: *Deploy from a branch* → Branch: `main`, map `/ (root)` → *Save*.
Na een minuutje staat hij op `https://serenanova.github.io/aanbiedingwekker/`.

## 6. Sleutel zodat de pagina mag opslaan

1. Ga naar https://github.com/settings/personal-access-tokens/new
2. Naam: `Aanbiedingwekker`. Verloopdatum: kies zelf (bijv. een jaar).
3. *Repository access → Only select repositories →* `aanbiedingwekker`.
4. *Permissions → Repository permissions → Contents →* **Read and write**.
5. *Generate token* en kopieer hem.

Open je pagina, tik op het tandwieltje, vul gebruikersnaam (`SerenaNova`), repository (`aanbiedingwekker`) en de sleutel in → *Bewaren*. De sleutel wordt alleen in die browser bewaard, dus op je telefoon en laptop vul je hem allebei een keer in.

## 7. Eerste test

Voeg op je pagina een product toe dat bijna altijd ergens in de aanbieding is (bijv. "shampoo" bij Kruidvat en Etos), zet de melding aan en tik op **Opslaan**. Opslaan start meteen een controle.

Kijk in je repository bij het tabblad **Actions** → *Aanbiedingen checken*. In het verslag van de stap "Folderz bekijken en mailen" zie je per winkel hoeveel aanbiedingen er gevonden zijn, bijvoorbeeld `Etos: 214 aanbiedingen`. Binnen een paar minuten heb je mail.

**Staat er bij een winkel 0 aanbiedingen of een fout?** Dan leest het script die pagina van Folderz nog niet goed. Ik heb het niet rechtstreeks op Folderz kunnen testen, dus stuur me dan het verslag (of een schermafbeelding ervan) en dan pas ik het aan. Je krijgt hierover ook zelf een mail, hooguit één keer per week.

## Hoe het werkt

- **Zoekwoorden**: alle woorden moeten in de naam van de aanbieding staan, hoofdletters en accenten maken niet uit. `nivea dag` vindt "Nivea dagcrème". Meerdere varianten scheid je met een komma: `andrelon shampoo, dove shampoo`.
- **Maximumprijs**: alleen een treffer als de aanbiedingsprijs niet hoger is.
- **Melding aan/uit**: uit = je ziet het wel op je pagina, maar krijgt geen mail.
- **Geen dubbele mails**: een aanbieding wordt maar één keer gemaild. Komt hetzelfde product later in een nieuwe folder terug, dan krijg je wel weer een mail.
- **Terugzoeken**: het onderwerp van de mail is "Aanbieding: " plus de productnamen, dus zoek in Gmail op bijvoorbeeld `Aanbieding: Nivea`.
- **Winkel toevoegen** (bijv. later een kledingwinkel): tandwieltje → plak de Folderz-link van die winkel, bijv. `https://www.folderz.nl/winkels/zeeman/folders-aanbiedingen`. Dat werkt alleen voor winkels die hun aanbiedingen op Folderz zetten.
- **Zelf een controle starten**: *Actions → Aanbiedingen checken → Run workflow*.
