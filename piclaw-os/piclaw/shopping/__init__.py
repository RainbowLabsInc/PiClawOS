"""
PiClaw OS – Einkaufsliste mit Angebots- und Preisbeobachtung.

Teile:
  store.py      SQLite-Store (Artikel, Produkte, Preisreihe, Alerts, Caches)
  providers/    Angebotsquellen (marktguru, lidl)
  matching.py   Titel-Normalisierung, Marken-Zuordnung, Produkt-Identität
  analysis.py   Preisverfall-Erkennung über die Zeitreihe
  location.py   Heimatadresse + Läden im Umkreis (nutzt tools/geo.py)
  sampler.py    Täglicher Sammellauf, füllt die Preisreihe
  tools.py      Agent-Tools
"""
