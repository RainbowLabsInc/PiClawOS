"""
PiClaw OS – Einkaufslisten-Store (SQLite)

Hält Artikel, die daraus entdeckten Produkte, deren Preisreihe, ausgelöste
Alerts sowie die Geo-Caches (Heimatadresse, Läden im Umkreis).

Warum SQLite und nicht JSON wie bei parcels.json: die Preisreihe wächst
täglich. Ein JSON-Store müsste bei jedem Sample die ganze Datei neu schreiben,
und `with_file_lock` ist auf Windows ein No-op – Cross-Process-Zugriff von
piclaw-api und piclaw-agent wäre erst auf dem Pi abgesichert. WAL löst das auf
beiden Plattformen.

Schema-Hinweis: Das Repo hat KEINE Migrations-Infrastruktur (kein user_version,
kein Alembic). Das Schema unten ist deshalb bewusst vollständig – inklusive der
alerts-Tabelle, die erst der Push-Monitor auswertet. Ein Schema-Upgrade auf
einer DB mit Monaten an Preishistorie will man nicht.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from piclaw.config import CONFIG_DIR

log = logging.getLogger("piclaw.shopping.store")

# Modul-Konstante, zur Importzeit aus CONFIG_DIR abgeleitet. MUSS in
# tests/conftest.py::patch_config_dir in die targets-Liste – sonst schreiben
# Tests in die Produktiv-DB (siehe SlowAgent-Vorfall im conftest-Docstring).
SHOPPING_DB = CONFIG_DIR / "shopping.db"

# Preispunkte werden ein gutes Jahr gehalten: der Jahresvergleich ("war im
# letzten Sommer billiger") ist bei Lebensmitteln genau der interessante Fall.
RETENTION_DAYS = 400

_SECS_PER_DAY = 86_400


# ── Datenmodell ──────────────────────────────────────────────────────────────


@dataclass
class Item:
    """Ein Artikel auf der Einkaufsliste."""

    id: int = 0
    name: str = ""
    query: str = ""          # Suchbegriff; leer → name wird benutzt
    qty: str = ""
    max_price: float | None = None
    owner_id: str | None = None
    muted: bool = False
    created_at: int = 0
    # Bis wann der Artikel als erledigt gilt (abgehakt). Er bleibt auf der
    # Liste und wird weiter gesampelt, taucht aber nicht im Digest oder
    # Warenkorb auf – so reißt die Preisreihe nicht ab.
    bought_until: int | None = None
    # Warenkategorie, die die Quelle für diesen Artikel liefert – der Bot
    # zeigt damit, wie er den Begriff verstanden hat ("Tempo → Toilettenpapier").
    category_id: int | None = None
    category: str = ""
    # Ganze Kategorie statt nur des Begriffs verfolgen. Antwort auf
    # Gattungsnamen: "Tempo" findet 2 Angebote (nur Tempo),
    # "Toilettenpapier" 14 – inklusive Zewa, Hakle und Eigenmarken.
    track_category: bool = False

    @property
    def search_term(self) -> str:
        """Womit tatsächlich gesucht wird.

        Bei aktivierter Kategorie-Verfolgung die Kategoriebezeichnung –
        UNVERÄNDERT mit Umlauten, das ist keine Kosmetik: "küchenrolle"
        liefert 9 Treffer, "kuechenrolle" null.
        """
        if self.track_category and self.category:
            return self.category.strip()
        return (self.query or self.name).strip()

    def is_bought(self, now: int | None = None) -> bool:
        """Gerade abgehakt – gehört nicht auf die Einkaufsliste."""
        if not self.bought_until:
            return False
        return (now if now is not None else int(time.time())) < self.bought_until

    @property
    def strict_matching(self) -> bool:
        """Ob Treffer zusätzlich lokal gefiltert werden sollen.

        Beim Artikelnamen ja: die Provider-Suche nach "Butter" liefert auch
        "Buttermilch", und das verdirbt die Preisreihe. Hat der Nutzer aber
        einen eigenen Suchbegriff hinterlegt, hat er sich bewusst festgelegt –
        dann würde die Kompositum-Regel ihn überstimmen ("geschirrspül" findet
        "Geschirrspültabs"). `query` ist genau der Notausgang für die Fälle,
        die die Heuristik nicht trifft.
        """
        return not self.query.strip()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "query": self.query,
            "qty": self.qty,
            "max_price": self.max_price,
            "owner_id": self.owner_id,
            "muted": self.muted,
            "created_at": self.created_at,
            "category_id": self.category_id,
            "category": self.category,
            "track_category": self.track_category,
            "search_term": self.search_term,
            "bought_until": self.bought_until,
            "is_bought": self.is_bought(),
        }


@dataclass
class Product:
    """Ein konkretes Produkt eines Händlers, an dem eine Preisreihe hängt.

    Die Zeitreihe hängt NICHT am Suchbegriff: "Butter" ist die Suche,
    "Kerrygold Original Irische Butter bei Lidl" ist die Reihe. Sonst wäre
    jeder vermeintliche Preisverfall bloß ein anderer Treffer.
    """

    id: int = 0
    item_id: int = 0
    retailer: str = ""
    title: str = ""
    title_norm: str = ""
    unit: str = ""
    # Packungsgröße in kg/l/Stk. Der Grundpreis wird daraus und aus dem
    # jeweiligen Preis berechnet – so stimmen auch historische Werte.
    unit_size: float | None = None
    unit_label: str = ""
    first_seen: int = 0
    last_seen: int = 0

    def unit_price(self, price: float | None) -> float | None:
        from piclaw.shopping.units import unit_price

        return unit_price(price, self.unit_size)

    def to_dict(self) -> dict:
        from piclaw.shopping.units import format_size

        return {
            "id": self.id,
            "item_id": self.item_id,
            "retailer": self.retailer,
            "title": self.title,
            "unit": self.unit,
            "unit_size": self.unit_size,
            "unit_label": self.unit_label,
            "size_text": format_size(self.unit_size, self.unit_label),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }


@dataclass
class PricePoint:
    """Ein Preis zu einem Zeitpunkt."""

    product_id: int = 0
    price: float = 0.0
    ts: int = field(default_factory=lambda: int(time.time()))
    is_promo: bool = False
    # Streichpreis, falls die Quelle einen liefert. Einzige direkte Quelle
    # für den Normalpreis – deshalb mitschreiben, auch wenn selten.
    old_price: float | None = None


def address_hash(*parts: str) -> str:
    """Stabiler Schlüssel für eine Adresse.

    Normalisiert Groß/Kleinschreibung und Leerraum, damit "Musterweg 12A" und
    " musterweg  12a " denselben Cache treffen. Eine echte Adressänderung
    ergibt einen neuen Hash und invalidiert damit automatisch Heimat- und
    Ladencache.
    """
    joined = "|".join(" ".join(str(p or "").split()).lower() for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]


# ── Datenbank ────────────────────────────────────────────────────────────────


def _add_column(con: sqlite3.Connection, table: str, column: str, ddl: str) -> bool:
    """Fügt eine Spalte hinzu, falls sie fehlt. Idempotent.

    Das Repo hat keine Migrations-Infrastruktur; das Schema wird bewusst
    vollständig angelegt. Für Felder, die einer bereits befüllten Datenbank
    fehlen, ist das hier der minimale Weg – ein Neuaufbau würde Monate an
    Preishistorie kosten.
    """
    vorhanden = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
    if column in vorhanden:
        return False
    con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    log.info("ShoppingDB: Spalte %s.%s ergänzt", table, column)
    return True


class ShoppingDB:
    """SQLite-Store der Einkaufsliste. Muster wie piclaw/metrics.py."""

    def __init__(self, path: Path = SHOPPING_DB, retention_days: int = RETENTION_DAYS):
        self.path = Path(path)
        self.retention_days = retention_days
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self):
        # timeout= ist der Python-Wrapper-Timeout; busy_timeout ist
        # SQLite-intern und greift bei jeder Operation. Auf dem Pi greifen
        # piclaw-api und piclaw-agent gleichzeitig zu.
        con = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("PRAGMA cache_size=-4000")
        con.execute("PRAGMA foreign_keys=ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _init_db(self) -> None:
        with self._conn() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    name       TEXT    NOT NULL,
                    query      TEXT    DEFAULT '',
                    qty        TEXT    DEFAULT '',
                    max_price  REAL,
                    owner_id   TEXT,
                    muted      INTEGER DEFAULT 0,
                    created_at INTEGER NOT NULL
                )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_items_owner ON items(owner_id)")
            # Bestandsdatenbanken nachziehen (Kategorie kam spaeter dazu).
            _add_column(con, "items", "category_id", "INTEGER")
            _add_column(con, "items", "category", "TEXT DEFAULT ''")
            _add_column(con, "items", "track_category", "INTEGER DEFAULT 0")
            # Abgehakte Artikel: gelten bis zu diesem Zeitpunkt als erledigt,
            # werden aber weiter gesampelt – so bleibt die Preisreihe dicht.
            _add_column(con, "items", "bought_until", "INTEGER")

            # UNIQUE über (item_id, retailer, title_norm) ist die
            # Produkt-Identität – siehe Product-Docstring.
            con.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id    INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    retailer   TEXT    NOT NULL,
                    title      TEXT    NOT NULL,
                    title_norm TEXT    NOT NULL,
                    unit       TEXT    DEFAULT '',
                    unit_size  REAL,
                    unit_label TEXT    DEFAULT '',
                    first_seen INTEGER NOT NULL,
                    last_seen  INTEGER NOT NULL,
                    UNIQUE(item_id, retailer, title_norm)
                )
            """)
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_products_item ON products(item_id)"
            )
            # Bestandsdatenbanken nachziehen (Grundpreis kam später dazu).
            _add_column(con, "products", "unit_size", "REAL")
            _add_column(con, "products", "unit_label", "TEXT DEFAULT ''")

            con.execute("""
                CREATE TABLE IF NOT EXISTS price_points (
                    ts         INTEGER NOT NULL,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    price      REAL    NOT NULL,
                    is_promo   INTEGER DEFAULT 0,
                    old_price  REAL
                )
            """)
            # Streichpreis nachtragen: er ist die einzige direkte Quelle für
            # den Normalpreis (nur ~8% der Angebote führen ihn).
            _add_column(con, "price_points", "old_price", "REAL")
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_pp_product ON price_points(product_id, ts)"
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_pp_ts ON price_points(ts)")

            # Wird von analysis.py geschrieben; der Push-Monitor liest sie.
            con.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    ts         INTEGER NOT NULL,
                    price      REAL    NOT NULL,
                    baseline   REAL    NOT NULL,
                    drop_pct   REAL    NOT NULL,
                    notified   INTEGER DEFAULT 0
                )
            """)
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_alerts_product ON alerts(product_id, ts)"
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_alerts_notified ON alerts(notified, ts)"
            )

            # Geo-Caches. payload ist JSON, weil die Ladenliste nur am Stück
            # gelesen und geschrieben wird – dafür lohnt keine eigene Tabelle.
            con.execute("""
                CREATE TABLE IF NOT EXISTS stores (
                    addr_hash  TEXT    NOT NULL,
                    radius_km  INTEGER NOT NULL,
                    fetched_at INTEGER NOT NULL,
                    payload    TEXT    NOT NULL,
                    PRIMARY KEY (addr_hash, radius_km)
                )
            """)
            # Merkt sich, was zuletzt gemeldet wurde – damit der Digest nur
            # bei tatsächlichen Änderungen zugestellt wird.
            con.execute("""
                CREATE TABLE IF NOT EXISTS digest_state (
                    user_id     TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    sent_at     INTEGER NOT NULL
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS home (
                    addr_hash   TEXT PRIMARY KEY,
                    lat         REAL NOT NULL,
                    lon         REAL NOT NULL,
                    precision   TEXT DEFAULT '',
                    zip         TEXT DEFAULT '',
                    resolved_at INTEGER NOT NULL
                )
            """)
        log.debug("ShoppingDB initialisiert: %s", self.path)

    # ── Artikel ──────────────────────────────────────────────────────────

    def add_item(
        self,
        name: str,
        query: str = "",
        qty: str = "",
        max_price: float | None = None,
        owner_id: str | None = None,
    ) -> Item:
        now = int(time.time())
        with self._conn() as con:
            cur = con.execute(
                "INSERT INTO items (name, query, qty, max_price, owner_id, muted,"
                " created_at) VALUES (?,?,?,?,?,0,?)",
                (name.strip(), query.strip(), qty.strip(), max_price, owner_id, now),
            )
            item_id = int(cur.lastrowid or 0)
        return Item(
            id=item_id, name=name.strip(), query=query.strip(), qty=qty.strip(),
            max_price=max_price, owner_id=owner_id, created_at=now,
        )

    def list_items(self, owner_id: str | None = None, include_muted: bool = True) -> list[Item]:
        """Artikel auflisten.

        owner_id=None bedeutet System-/Scheduler-Kontext und sieht alles –
        dieselbe Konvention wie bei parcels und sub-agents.
        """
        sql = "SELECT * FROM items"
        params: list = []
        where = []
        if owner_id is not None:
            where.append("(owner_id = ? OR owner_id IS NULL)")
            params.append(owner_id)
        if not include_muted:
            where.append("muted = 0")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id"
        with self._conn() as con:
            rows = con.execute(sql, params).fetchall()
        return [_row_to_item(r) for r in rows]

    def get_item(self, item_id: int) -> Item | None:
        with self._conn() as con:
            row = con.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return _row_to_item(row) if row else None

    def find_item_by_name(self, name: str, owner_id: str | None = None) -> Item | None:
        """Sucht case-insensitiv nach dem Namen – für die Chat-Bedienung."""
        sql = "SELECT * FROM items WHERE LOWER(name) = LOWER(?)"
        params: list = [name.strip()]
        if owner_id is not None:
            sql += " AND (owner_id = ? OR owner_id IS NULL)"
            params.append(owner_id)
        with self._conn() as con:
            row = con.execute(sql + " ORDER BY id LIMIT 1", params).fetchone()
        return _row_to_item(row) if row else None

    def remove_item(self, item_id: int) -> bool:
        with self._conn() as con:
            cur = con.execute("DELETE FROM items WHERE id = ?", (item_id,))
            return cur.rowcount > 0

    def set_muted(self, item_id: int, muted: bool) -> bool:
        with self._conn() as con:
            cur = con.execute(
                "UPDATE items SET muted = ? WHERE id = ?", (1 if muted else 0, item_id)
            )
            return cur.rowcount > 0

    def set_category(
        self, item_id: int, category_id: int | None, category: str
    ) -> bool:
        """Merkt sich, wie die Quelle den Suchbegriff einordnet."""
        with self._conn() as con:
            cur = con.execute(
                "UPDATE items SET category_id = ?, category = ? WHERE id = ?",
                (category_id, category or "", item_id),
            )
            return cur.rowcount > 0

    def set_bought(self, item_id: int, days: int = 14) -> int | None:
        """Hakt einen Artikel ab. days<=0 macht das Abhaken rückgängig."""
        bis = int(time.time()) + days * _SECS_PER_DAY if days > 0 else None
        with self._conn() as con:
            cur = con.execute(
                "UPDATE items SET bought_until = ? WHERE id = ?", (bis, item_id)
            )
            return bis if cur.rowcount else None

    # ── Digest ───────────────────────────────────────────────────────────

    def digest_changed(self, user_id: str | None, fingerprint: str) -> bool:
        """Ob sich seit der letzten Zustellung etwas geändert hat."""
        key = user_id or "__system__"
        with self._conn() as con:
            row = con.execute(
                "SELECT fingerprint FROM digest_state WHERE user_id = ?", (key,)
            ).fetchone()
        return not row or row["fingerprint"] != fingerprint

    def digest_sent(self, user_id: str | None, fingerprint: str) -> None:
        key = user_id or "__system__"
        with self._conn() as con:
            con.execute(
                "INSERT INTO digest_state (user_id, fingerprint, sent_at)"
                " VALUES (?,?,?)"
                " ON CONFLICT(user_id) DO UPDATE SET fingerprint=excluded.fingerprint,"
                " sent_at=excluded.sent_at",
                (key, fingerprint, int(time.time())),
            )

    def set_track_category(self, item_id: int, track: bool) -> bool:
        with self._conn() as con:
            cur = con.execute(
                "UPDATE items SET track_category = ? WHERE id = ?",
                (1 if track else 0, item_id),
            )
            return cur.rowcount > 0

    # ── Produkte und Preise ──────────────────────────────────────────────

    def upsert_product(
        self, item_id: int, retailer: str, title: str, title_norm: str,
        unit: str = "", ts: int | None = None,
        unit_size: float | None = None, unit_label: str = "",
    ) -> int:
        """Legt das Produkt an oder frischt last_seen auf. Gibt product_id zurück.

        Eine einmal bekannte Packungsgröße wird nicht durch einen leeren Wert
        überschrieben: liefert eine Quelle sie später nicht mehr mit, bleibt
        der Grundpreis trotzdem berechenbar.
        """
        now = ts if ts is not None else int(time.time())
        with self._conn() as con:
            con.execute(
                "INSERT INTO products (item_id, retailer, title, title_norm, unit,"
                " unit_size, unit_label, first_seen, last_seen)"
                " VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(item_id, retailer, title_norm) DO UPDATE SET"
                "   last_seen = excluded.last_seen,"
                "   title = excluded.title,"
                "   unit = CASE WHEN excluded.unit != '' THEN excluded.unit"
                "               ELSE products.unit END,"
                "   unit_size = COALESCE(excluded.unit_size, products.unit_size),"
                "   unit_label = CASE WHEN excluded.unit_label != ''"
                "                     THEN excluded.unit_label"
                "                     ELSE products.unit_label END",
                (item_id, retailer, title, title_norm, unit,
                 unit_size, unit_label, now, now),
            )
            row = con.execute(
                "SELECT id FROM products WHERE item_id = ? AND retailer = ?"
                " AND title_norm = ?",
                (item_id, retailer, title_norm),
            ).fetchone()
        return int(row["id"]) if row else 0

    def record_price(
        self, product_id: int, price: float, ts: int | None = None,
        is_promo: bool = False,
    ) -> None:
        self.record_prices([PricePoint(product_id, price,
                                       ts if ts is not None else int(time.time()),
                                       is_promo)])

    def record_prices(self, points: list[PricePoint]) -> int:
        """Schreibt Preispunkte im Batch – genau einer pro Produkt und Tag.

        Der günstigste Preis des Tages gewinnt. Ohne diese Invariante zählte
        ein zweiter Lauf am selben Tag (manueller Trigger neben dem Cron) den
        Tag doppelt in den Median, und `min_samples` würde Messwerte statt
        Tage zählen.

        Gibt die Zahl der tatsächlich geschriebenen Punkte zurück.
        """
        if not points:
            return 0
        written = 0
        with self._conn() as con:
            for point in points:
                day = point.ts // _SECS_PER_DAY
                row = con.execute(
                    "SELECT MIN(price) AS p FROM price_points"
                    " WHERE product_id = ? AND ts / ? = ?",
                    (point.product_id, _SECS_PER_DAY, day),
                ).fetchone()
                existing = row["p"] if row else None
                if existing is not None and existing <= point.price:
                    continue  # heute schon günstiger gesehen
                if existing is not None:
                    con.execute(
                        "DELETE FROM price_points WHERE product_id = ? AND ts / ? = ?",
                        (point.product_id, _SECS_PER_DAY, day),
                    )
                con.execute(
                    "INSERT INTO price_points (ts, product_id, price, is_promo,"
                    " old_price) VALUES (?,?,?,?,?)",
                    (point.ts, point.product_id, point.price,
                     1 if point.is_promo else 0, point.old_price),
                )
                written += 1
        return written

    def list_products(self, item_id: int) -> list[Product]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM products WHERE item_id = ? ORDER BY last_seen DESC",
                (item_id,),
            ).fetchall()
        return [_row_to_product(r) for r in rows]

    def history(
        self, product_id: int, since_ts: int | None = None
    ) -> list[tuple[int, float]]:
        """Preisreihe eines Produkts, aufsteigend nach Zeit."""
        sql = "SELECT ts, price FROM price_points WHERE product_id = ?"
        params: list = [product_id]
        if since_ts is not None:
            sql += " AND ts >= ?"
            params.append(since_ts)
        sql += " ORDER BY ts"
        with self._conn() as con:
            rows = con.execute(sql, params).fetchall()
        return [(int(r["ts"]), float(r["price"])) for r in rows]

    def item_history(
        self, item_id: int, since_ts: int | None = None
    ) -> list[tuple[int, float]]:
        """Günstigster Preis pro Tag über alle Produkte eines Artikels.

        Das ist die Reihe für die Sparkline im Dashboard: "was hätte mich
        dieser Artikel an dem Tag mindestens gekostet".
        """
        return [(p["ts"], p["price"]) for p in self.item_history_detailed(
            item_id, since_ts)]

    def item_history_detailed(
        self, item_id: int, since_ts: int | None = None
    ) -> list[dict]:
        """Wie item_history, aber mit Händler und Produkt des Tagesbestpreises.

        Beantwortet "wo war der Artikel an dem Tag am günstigsten". Die
        Gruppierung passiert bewusst in Python statt per Window-Function:
        die Datenmenge ist winzig (ein Punkt je Produkt und Tag), und so
        hängt nichts an der SQLite-Version auf dem Pi.
        """
        sql = (
            "SELECT p.ts, p.price, pr.retailer, pr.title,"
            "       pr.unit_size, pr.unit_label, pr.id AS product_id"
            " FROM price_points p JOIN products pr ON pr.id = p.product_id"
            " WHERE pr.item_id = ?"
        )
        params: list = [item_id]
        if since_ts is not None:
            sql += " AND p.ts >= ?"
            params.append(since_ts)
        sql += " ORDER BY p.ts"
        with self._conn() as con:
            rows = con.execute(sql, params).fetchall()

        from piclaw.shopping.units import format_unit_price

        je_tag: dict[int, dict] = {}
        for row in rows:
            tag = (int(row["ts"]) // _SECS_PER_DAY) * _SECS_PER_DAY
            preis = float(row["price"])
            bisher = je_tag.get(tag)
            if bisher is not None and bisher["price"] <= preis:
                continue
            groesse = row["unit_size"]
            groesse = float(groesse) if groesse is not None else None
            je_tag[tag] = {
                "ts": tag,
                "price": preis,
                "retailer": row["retailer"],
                "title": row["title"],
                "product_id": int(row["product_id"]),
                "unit_price_text": format_unit_price(
                    preis, groesse, row["unit_label"] or ""
                ),
            }
        return [je_tag[t] for t in sorted(je_tag)]

    def normal_price_estimate(
        self, item_id: int, min_days: int = 5
    ) -> tuple[float | None, str]:
        """Schätzt, was der Artikel regulär kostet – ohne Aktion.

        Gebraucht für den Warenkorb-Vergleich: ein Laden, der nur 4 von 5
        Artikeln im Angebot hat, ist nicht billiger – man kauft den fünften
        dort zum Normalpreis mit. Ohne diese Schätzung erscheinen Läden mit
        wenigen Aktionsartikeln fälschlich als die günstigsten.

        Die Quellen sind unterschiedlich verlässlich, deshalb wird sie
        mitgegeben und in der Anzeige kenntlich gemacht:

        1. **Streichpreis** – der einzige echte Normalpreis in den Daten.
           Bei Lidl bei rund der Hälfte der Angebote dabei, bei marktguru nur
           bei ~8 % (gemessen 08/2026).
        2. **Höchster beobachteter Preis** der eigenen Historie – aber erst
           ab `min_days` verschiedenen Messtagen. Alles darunter wäre nur
           das Maximum der heutigen *Aktions*preise und läge damit
           systematisch unter dem Regalpreis. Lieber keine Zahl als eine,
           die den Vergleich in die falsche Richtung verschiebt.
        3. Nichts davon → (None, ""), der Aufrufer muss den Laden als nicht
           vergleichbar ausweisen statt eine Zahl zu erfinden.
        """
        with self._conn() as con:
            row = con.execute(
                "SELECT MAX(p.old_price) AS streich, MAX(p.price) AS hoechster,"
                "       COUNT(DISTINCT p.ts / ?) AS tage"
                " FROM price_points p JOIN products pr ON pr.id = p.product_id"
                " WHERE pr.item_id = ?",
                (_SECS_PER_DAY, item_id),
            ).fetchone()
        if not row:
            return None, ""
        if row["streich"]:
            return float(row["streich"]), "streichpreis"
        if row["hoechster"] and int(row["tage"] or 0) >= min_days:
            return float(row["hoechster"]), "historie"
        return None, ""

    def retailer_summary(self, item_id: int, since_ts: int | None = None) -> list[dict]:
        """Wie oft war welcher Händler der günstigste des Tages?"""
        from collections import Counter

        zaehler = Counter(
            p["retailer"] for p in self.item_history_detailed(item_id, since_ts)
        )
        gesamt = sum(zaehler.values())
        return [
            {"retailer": name, "days": n, "share": n / gesamt if gesamt else 0.0}
            for name, n in zaehler.most_common()
        ]

    def best_current(self, item_id: int, max_age_s: int = 3 * _SECS_PER_DAY) -> dict | None:
        """Günstigster zuletzt gesehener Preis eines Artikels."""
        return self._best(item_id, max_age_s, "p.price ASC, p.ts DESC")

    def best_unit_price(
        self, item_id: int, max_age_s: int = 3 * _SECS_PER_DAY
    ) -> dict | None:
        """Bestes Preis-Leistungs-Verhältnis (€/kg, €/l, €/Stück).

        Das ist die eigentlich interessante Frage: 1,79 € für 250 g Butter ist
        teurer als 2,49 € für 400 g, obwohl der Absolutpreis das Gegenteil
        nahelegt. Produkte ohne bekannte Packungsgröße bleiben außen vor.
        """
        return self._best(
            item_id, max_age_s,
            "(p.price / pr.unit_size) ASC, p.ts DESC",
            zusatz=" AND pr.unit_size IS NOT NULL AND pr.unit_size > 0",
        )

    def _best(
        self, item_id: int, max_age_s: int, order: str, zusatz: str = ""
    ) -> dict | None:
        cutoff = int(time.time()) - max_age_s
        with self._conn() as con:
            row = con.execute(
                "SELECT p.price, p.ts, p.is_promo, pr.retailer, pr.title, pr.unit,"
                "       pr.unit_size, pr.unit_label, pr.id AS product_id"
                " FROM price_points p JOIN products pr ON pr.id = p.product_id"
                f" WHERE pr.item_id = ? AND p.ts >= ?{zusatz}"
                f" ORDER BY {order} LIMIT 1",
                (item_id, cutoff),
            ).fetchone()
        if not row:
            return None
        from piclaw.shopping.units import format_size, format_unit_price, unit_price

        preis = float(row["price"])
        groesse = row["unit_size"]
        groesse = float(groesse) if groesse is not None else None
        label = row["unit_label"] or ""
        return {
            "product_id": int(row["product_id"]),
            "price": preis,
            "ts": int(row["ts"]),
            "is_promo": bool(row["is_promo"]),
            "retailer": row["retailer"],
            "title": row["title"],
            "unit": row["unit"],
            "unit_size": groesse,
            "unit_label": label,
            "size_text": format_size(groesse, label),
            "unit_price": unit_price(preis, groesse),
            "unit_price_text": format_unit_price(preis, groesse, label),
        }

    # ── Alerts ───────────────────────────────────────────────────────────

    def add_alert(
        self, product_id: int, price: float, baseline: float, drop_pct: float,
        ts: int | None = None,
    ) -> int:
        with self._conn() as con:
            cur = con.execute(
                "INSERT INTO alerts (product_id, ts, price, baseline, drop_pct,"
                " notified) VALUES (?,?,?,?,?,0)",
                (product_id, ts if ts is not None else int(time.time()),
                 price, baseline, drop_pct),
            )
            return int(cur.lastrowid or 0)

    def last_alert(self, product_id: int) -> dict | None:
        with self._conn() as con:
            row = con.execute(
                "SELECT * FROM alerts WHERE product_id = ? ORDER BY ts DESC LIMIT 1",
                (product_id,),
            ).fetchone()
        return dict(row) if row else None

    def pending_alerts(self) -> list[dict]:
        """Noch nicht gemeldete Alerts – der Push-Monitor holt sie hier ab."""
        with self._conn() as con:
            rows = con.execute(
                "SELECT a.*, pr.retailer, pr.title, pr.unit, pr.item_id, i.name AS item_name"
                " FROM alerts a"
                " JOIN products pr ON pr.id = a.product_id"
                " JOIN items i ON i.id = pr.item_id"
                " WHERE a.notified = 0 ORDER BY a.ts"
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_alerts_notified(self, alert_ids: list[int]) -> int:
        if not alert_ids:
            return 0
        placeholders = ",".join("?" * len(alert_ids))
        with self._conn() as con:
            cur = con.execute(
                f"UPDATE alerts SET notified = 1 WHERE id IN ({placeholders})",
                alert_ids,
            )
            return cur.rowcount

    # ── Geo-Caches ───────────────────────────────────────────────────────

    def save_home(
        self, addr_hash: str, lat: float, lon: float, precision: str, zip_code: str
    ) -> None:
        with self._conn() as con:
            con.execute(
                "INSERT INTO home (addr_hash, lat, lon, precision, zip, resolved_at)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(addr_hash) DO UPDATE SET lat=excluded.lat,"
                " lon=excluded.lon, precision=excluded.precision, zip=excluded.zip,"
                " resolved_at=excluded.resolved_at",
                (addr_hash, lat, lon, precision, zip_code, int(time.time())),
            )

    def get_home(self, addr_hash: str) -> dict | None:
        with self._conn() as con:
            row = con.execute(
                "SELECT * FROM home WHERE addr_hash = ?", (addr_hash,)
            ).fetchone()
        return dict(row) if row else None

    def save_stores(self, addr_hash: str, radius_km: int, shops: list[dict]) -> None:
        with self._conn() as con:
            con.execute(
                "INSERT INTO stores (addr_hash, radius_km, fetched_at, payload)"
                " VALUES (?,?,?,?)"
                " ON CONFLICT(addr_hash, radius_km) DO UPDATE SET"
                " fetched_at=excluded.fetched_at, payload=excluded.payload",
                (addr_hash, int(radius_km), int(time.time()),
                 json.dumps(shops, ensure_ascii=False)),
            )

    def get_stores(
        self, addr_hash: str, radius_km: int, max_age_days: int = 30
    ) -> list[dict] | None:
        """Ladencache. None wenn nicht vorhanden oder abgelaufen."""
        with self._conn() as con:
            row = con.execute(
                "SELECT * FROM stores WHERE addr_hash = ? AND radius_km = ?",
                (addr_hash, int(radius_km)),
            ).fetchone()
        if not row:
            return None
        # >= statt >, damit max_age_days=0 verlässlich "immer neu holen" heißt.
        if int(time.time()) - int(row["fetched_at"]) >= max_age_days * _SECS_PER_DAY:
            return None
        try:
            return json.loads(row["payload"])
        except (ValueError, TypeError):
            log.warning("Ladencache unlesbar (addr_hash=%s) – wird neu geholt", addr_hash)
            return None

    # ── Wartung ──────────────────────────────────────────────────────────

    def purge_old(self, now: int | None = None) -> int:
        """Löscht Preispunkte jenseits der Retention. Gibt gelöschte Zeilen zurück."""
        cutoff = (now if now is not None else int(time.time())) \
            - self.retention_days * _SECS_PER_DAY
        with self._conn() as con:
            cur = con.execute("DELETE FROM price_points WHERE ts < ?", (cutoff,))
            deleted = cur.rowcount
            # Produkte ohne verbleibende Preispunkte und ohne aktuellen
            # Sichtkontakt sind Karteileichen.
            con.execute(
                "DELETE FROM products WHERE last_seen < ?"
                " AND id NOT IN (SELECT DISTINCT product_id FROM price_points)",
                (cutoff,),
            )
        if deleted:
            log.info("ShoppingDB: %d alte Preispunkte gelöscht", deleted)
        return deleted

    def vacuum(self) -> None:
        con = sqlite3.connect(self.path, timeout=60)
        try:
            con.execute("VACUUM")
        finally:
            con.close()

    def stats(self) -> dict:
        with self._conn() as con:
            def _count(table: str) -> int:
                return int(con.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"])

            oldest = con.execute("SELECT MIN(ts) m FROM price_points").fetchone()["m"]
            return {
                "path": str(self.path),
                "size_kb": round(self.path.stat().st_size / 1024, 1)
                if self.path.exists() else 0,
                "items": _count("items"),
                "products": _count("products"),
                "price_points": _count("price_points"),
                "alerts": _count("alerts"),
                "oldest_price_ts": int(oldest) if oldest else None,
                "retention_days": self.retention_days,
            }


def _row_to_item(row: sqlite3.Row) -> Item:
    spalten = row.keys()
    kid = row["category_id"] if "category_id" in spalten else None
    return Item(
        id=int(row["id"]),
        name=row["name"],
        query=row["query"] or "",
        qty=row["qty"] or "",
        max_price=float(row["max_price"]) if row["max_price"] is not None else None,
        owner_id=row["owner_id"],
        muted=bool(row["muted"]),
        created_at=int(row["created_at"]),
        bought_until=(int(row["bought_until"])
                      if "bought_until" in spalten and row["bought_until"] else None),
        category_id=int(kid) if kid is not None else None,
        category=(row["category"] if "category" in spalten else "") or "",
        track_category=bool(
            row["track_category"] if "track_category" in spalten else 0
        ),
    )


def _row_to_product(row: sqlite3.Row) -> Product:
    groesse = row["unit_size"] if "unit_size" in row.keys() else None
    return Product(
        id=int(row["id"]),
        item_id=int(row["item_id"]),
        retailer=row["retailer"],
        title=row["title"],
        title_norm=row["title_norm"],
        unit=row["unit"] or "",
        unit_size=float(groesse) if groesse is not None else None,
        unit_label=(row["unit_label"] if "unit_label" in row.keys() else "") or "",
        first_seen=int(row["first_seen"]),
        last_seen=int(row["last_seen"]),
    )


# ── Singleton ────────────────────────────────────────────────────────────────

_db: ShoppingDB | None = None


def get_db() -> ShoppingDB:
    """Prozessweite Instanz.

    SHOPPING_DB wird erst beim Aufruf gelesen, damit der conftest-Patch greift.
    """
    global _db
    if _db is None:
        _db = ShoppingDB(SHOPPING_DB)
    return _db


def reset_db() -> None:
    """Setzt das Singleton zurück (Tests)."""
    global _db
    _db = None


__all__ = [
    "SHOPPING_DB",
    "RETENTION_DAYS",
    "Item",
    "Product",
    "PricePoint",
    "ShoppingDB",
    "address_hash",
    "get_db",
    "reset_db",
]
