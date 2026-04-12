"""
PiClaw OS – Encrypted Secrets Store
Speichert API-Keys verschlüsselt in /etc/piclaw/secrets.enc
Schlüssel abgeleitet aus Pi CPU-Seriennummer + Installations-Salt.

Nutzung:
    from piclaw.secrets import get_secret, set_secret, migrate_from_config
    api_key = get_secret("llm.api_key")
    set_secret("telegram.token", "123:ABC...")
"""

import base64
import hashlib
import json
import logging
import os
import secrets as _secrets
from pathlib import Path

log = logging.getLogger("piclaw.secrets")

# Lazy import — cryptography might not be installed
_Fernet = None


def _ensure_fernet():
    global _Fernet
    if _Fernet is None:
        try:
            from cryptography.fernet import Fernet
            _Fernet = Fernet
        except ImportError:
            raise ImportError(
                "cryptography nicht installiert. "
                "Bitte: /opt/piclaw/.venv/bin/pip install cryptography --break-system-packages"
            )
    return _Fernet


# ── Paths ────────────────────────────────────────────────────────────────────

def _config_dir() -> Path:
    """Config-Dir ermitteln (gleiche Logik wie config.py)."""
    if Path("/etc/piclaw/config.toml").exists():
        return Path("/etc/piclaw")
    if Path("/etc/piclaw").exists() and os.getuid() == 0:
        return Path("/etc/piclaw")
    return Path.home() / ".piclaw"


SECRETS_FILE = _config_dir() / "secrets.enc"
SALT_FILE = _config_dir() / ".secret_salt"


# ── Key-Listen ───────────────────────────────────────────────────────────────

# Alle Secret-Keys die aus config.toml migriert werden
SECRET_KEYS = [
    ("llm", "api_key"),
    ("telegram", "token"),
    ("discord", "token"),
    ("threema", "api_secret"),
    ("whatsapp", "access_token"),
    ("agentmail", "api_key"),
    ("api", "secret_key"),
    # homeassistant.token wird separat behandelt (eigene Sektion)
]

# Shell-Blocklist Einträge für Secrets-Schutz
SECRETS_BLOCKLIST = [
    "secrets.enc",
    ".secret_salt",
    "config.toml",
]


# ── Key Derivation ───────────────────────────────────────────────────────────

def _get_pi_serial() -> str:
    """Liest die CPU-Seriennummer des Raspberry Pi."""
    try:
        for line in open("/proc/cpuinfo"):
            if line.strip().startswith("Serial"):
                return line.split(":")[1].strip()
    except Exception:
        pass
    # Fallback: hostname + machine-id
    try:
        mid = Path("/etc/machine-id").read_text().strip()
        return mid
    except Exception:
        return "piclaw-default-serial"


def _derive_key() -> bytes:
    """Leitet den Fernet-Key aus Pi-Serial + Salt ab."""
    serial = _get_pi_serial()

    config_dir = _config_dir()
    salt_path = config_dir / ".secret_salt"

    if not salt_path.exists():
        salt = _secrets.token_bytes(32)
        config_dir.mkdir(parents=True, exist_ok=True)
        salt_path.write_bytes(salt)
        try:
            salt_path.chmod(0o600)
        except OSError:
            pass
        log.info("Secret-Salt erstellt: %s", salt_path)
    else:
        salt = salt_path.read_bytes()

    key_material = hashlib.pbkdf2_hmac(
        "sha256",
        serial.encode("utf-8"),
        salt,
        iterations=100_000,
        dklen=32,
    )
    return base64.urlsafe_b64encode(key_material)


# ── Core Functions ───────────────────────────────────────────────────────────

def _load_raw() -> dict:
    """Entschlüsselt und lädt secrets.enc."""
    if not SECRETS_FILE.exists():
        return {}

    Fernet = _ensure_fernet()
    key = _derive_key()
    f = Fernet(key)

    try:
        encrypted = SECRETS_FILE.read_bytes()
        decrypted = f.decrypt(encrypted)
        return json.loads(decrypted.decode("utf-8"))
    except Exception as e:
        log.error("Secrets entschlüsseln fehlgeschlagen: %s", e)
        return {}


def _save_raw(data: dict) -> None:
    """Verschlüsselt und speichert secrets.enc."""
    Fernet = _ensure_fernet()
    key = _derive_key()
    f = Fernet(key)

    plaintext = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    encrypted = f.encrypt(plaintext)

    SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SECRETS_FILE.write_bytes(encrypted)
    try:
        SECRETS_FILE.chmod(0o600)
    except OSError:
        pass


def get_secret(key: str, default: str = "") -> str:
    """Liest einen Secret-Wert. Key-Format: 'section.field' (z.B. 'llm.api_key')."""
    data = _load_raw()
    return data.get(key, default)


def set_secret(key: str, value: str) -> None:
    """Setzt einen Secret-Wert."""
    data = _load_raw()
    if value:
        data[key] = value
    elif key in data:
        del data[key]
    _save_raw(data)
    log.info("Secret '%s' aktualisiert", key)


def list_keys() -> list[str]:
    """Listet alle gespeicherten Secret-Keys (ohne Werte)."""
    data = _load_raw()
    return list(data.keys())


def has_secret(key: str) -> bool:
    """Prüft ob ein Secret existiert."""
    data = _load_raw()
    return bool(data.get(key))


# ── Migration ────────────────────────────────────────────────────────────────

def migrate_from_config(config_path: Path | None = None) -> int:
    """
    Migriert Secrets aus config.toml nach secrets.enc.
    Ersetzt die Werte in config.toml durch leere Strings.
    Gibt Anzahl migrierter Keys zurück.
    """
    if config_path is None:
        config_path = _config_dir() / "config.toml"

    if not config_path.exists():
        return 0

    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

    try:
        raw_toml = config_path.read_text(encoding="utf-8")
        cfg = tomllib.loads(raw_toml)
    except Exception as e:
        log.error("config.toml laden fehlgeschlagen: %s", e)
        return 0

    data = _load_raw()
    migrated = 0

    for section, field in SECRET_KEYS:
        value = cfg.get(section, {}).get(field, "")
        if value and value != "" and not value.startswith("@enc:"):
            secret_key = f"{section}.{field}"
            data[secret_key] = value
            migrated += 1
            log.info("Migriert: %s.%s", section, field)

    # homeassistant.token separat
    ha_token = cfg.get("homeassistant", {}).get("token", "")
    if ha_token and ha_token != "":
        data["homeassistant.token"] = ha_token
        migrated += 1

    # DHL API Key
    dhl_key = cfg.get("parcel_tracking", {}).get("dhl_api_key", "")
    if dhl_key and dhl_key != "":
        data["parcel_tracking.dhl_api_key"] = dhl_key
        migrated += 1

    if migrated > 0:
        _save_raw(data)

        # config.toml: Secrets durch Platzhalter ersetzen
        import re
        for section, field in SECRET_KEYS:
            value = cfg.get(section, {}).get(field, "")
            if value and value != "":
                # Ersetze den Wert in der TOML-Datei
                # Pattern: field = "value" oder field = 'value'
                pattern = rf'({field}\s*=\s*)["\']([^"\']+)["\']'
                replacement = rf'\1""  # @encrypted → secrets.enc'
                raw_toml = re.sub(pattern, replacement, raw_toml)

        # homeassistant.token
        if ha_token:
            raw_toml = re.sub(
                r'(token\s*=\s*)["\']([^"\']+)["\']',
                r'\1""  # @encrypted → secrets.enc',
                raw_toml,
            )

        config_path.write_text(raw_toml, encoding="utf-8")
        log.info("config.toml bereinigt – %d Secrets nach secrets.enc migriert", migrated)

    return migrated


# ── Config Integration ───────────────────────────────────────────────────────

def inject_secrets_into_config(cfg) -> None:
    """
    Lädt Secrets aus secrets.enc und injiziert sie in ein PiClawConfig-Objekt.
    Wird nach config.load() aufgerufen.
    """
    if not SECRETS_FILE.exists():
        return

    try:
        data = _load_raw()
    except Exception:
        return

    for key, value in data.items():
        if not value:
            continue
        parts = key.split(".", 1)
        if len(parts) != 2:
            continue
        section, field = parts

        # Dynamisch ins Config-Objekt schreiben
        sub = getattr(cfg, section, None)
        if sub is not None and hasattr(sub, field):
            current = getattr(sub, field)
            # Nur überschreiben wenn der Config-Wert leer ist
            if not current or current == "":
                setattr(sub, field, value)

    log.debug("Secrets aus secrets.enc in Config injiziert")
