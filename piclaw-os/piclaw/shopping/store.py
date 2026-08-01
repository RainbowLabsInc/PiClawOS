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

    @property
    def search_term(self) -> str:
        return (self.query or self.name).strip()

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
    first_seen: int = 0
    last_seen: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "item_id": self.item_id,
            "retailer": self.retailer,
            "title": self.title,
            "unit": self.unit,
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
                    first_seen INTEGER NOT NULL,
                    last_seen  INTEGER NOT NULL,
                    UNIQUE(item_id, retailer, title_norm)
                )
            """)
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_products_item ON products(item_id)"
            )

            con.execute("""
                CREATE TABLE IF NOT EXISTS price_points (
                    ts         INTEGER NOT NULL,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    price      REAL    NOT NULL,
                    is_promo   INTEGER DEFAULT 0
                )
            """)
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

    # ── Produkte und Preise ──────────────────────────────────────────────

    def upsert_product(
        self, item_id: int, retailer: str, title: str, title_norm: str,
        unit: str = "", ts: int | None = None,
    ) -> int:
        """Legt das Produkt an oder frischt last_seen auf. Gibt product_id zurück."""
        now = ts if ts is not None else int(time.time())
        with self._conn() as con:
            con.execute(
                "INSERT INTO products (item_id, retailer, title, title_norm, unit,"
                " first_seen, last_seen) VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(item_id, retailer, title_norm) DO UPDATE SET"
                "   last_seen = excluded.last_seen,"
                "   title = excluded.title,"
                "   unit = CASE WHEN excluded.unit != '' THEN excluded.unit"
                "               ELSE products.unit END",
                (item_id, retailer, title, title_norm, unit, now, now),
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
                    "INSERT INTO price_points (ts, product_id, price, is_promo)"
                    " VALUES (?,?,?,?)",
                    (point.ts, point.product_id, point.price,
                     1 if point.is_promo else 0),
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
        sql = (
            "SELECT (ts / ?) * ? AS day_ts, MIN(price) AS price"
            " FROM price_points p JOIN products pr ON pr.id = p.product_id"
            " WHERE pr.item_id = ?"
        )
        params: list = [_SECS_PER_DAY, _SECS_PER_DAY, item_id]
        if since_ts is not None:
            sql += " AND p.ts >= ?"
            params.append(since_ts)
        sql += " GROUP BY day_ts ORDER BY day_ts"
        with self._conn() as con:
            rows = con.execute(sql, params).fetchall()
        return [(int(r["day_ts"]), float(r["price"])) for r in rows]

    def best_current(self, item_id: int, max_age_s: int = 3 * _SECS_PER_DAY) -> dict | None:
        """Günstigster zuletzt gesehener Preis eines Artikels."""
        cutoff = int(time.time()) - max_age_s
        with self._conn() as con:
            row = con.execute(
                "SELECT p.price, p.ts, p.is_promo, pr.retailer, pr.title, pr.unit,"
                "       pr.id AS product_id"
                " FROM price_points p JOIN products pr ON pr.id = p.product_id"
                " WHERE pr.item_id = ? AND p.ts >= ?"
                " ORDER BY p.price ASC, p.ts DESC LIMIT 1",
                (item_id, cutoff),
            ).fetchone()
        if not row:
            return None
        return {
            "product_id": int(row["product_id"]),
            "price": float(row["price"]),
            "ts": int(row["ts"]),
            "is_promo": bool(row["is_promo"]),
            "retailer": row["retailer"],
            "title": row["title"],
            "unit": row["unit"],
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
    return Item(
        id=int(row["id"]),
        name=row["name"],
        query=row["query"] or "",
        qty=row["qty"] or "",
        max_price=float(row["max_price"]) if row["max_price"] is not None else None,
        owner_id=row["owner_id"],
        muted=bool(row["muted"]),
        created_at=int(row["created_at"]),
    )


def _row_to_product(row: sqlite3.Row) -> Product:
    return Product(
        id=int(row["id"]),
        item_id=int(row["item_id"]),
        retailer=row["retailer"],
        title=row["title"],
        title_norm=row["title_norm"],
        unit=row["unit"] or "",
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
