"""
PiClaw OS – Configuration
All state lives in ~/.piclaw/ (or /etc/piclaw/ when running as system service)
"""

import os
import tomllib
import tomli_w
from dataclasses import dataclass, field, asdict
from pathlib import Path


# Config-Pfad: /etc/piclaw hat Vorrang wenn vorhanden (system install)
# Fallback: ~/.piclaw (Entwicklung / non-root)
def _resolve_config_dir() -> Path:
    system_cfg = Path("/etc/piclaw/config.toml")
    system_dir = Path("/etc/piclaw")
    if system_cfg.exists():
        return system_dir  # config.toml vorhanden → immer system
    if system_dir.exists() and os.getuid() == 0:
        return system_dir  # root + Verzeichnis → system
    return Path.home() / ".piclaw"


CONFIG_DIR = _resolve_config_dir()
CONFIG_FILE = CONFIG_DIR / "config.toml"
SKILLS_DIR = CONFIG_DIR / "skills"
LOG_DIR = CONFIG_DIR / "logs"
CRASH_DIR = CONFIG_DIR / "crashes"
SCHEDULE_DB = CONFIG_DIR / "schedules.json"


@dataclass
class LLMConfig:
    backend: str = "anthropic"  # anthropic | openai | ollama
    model: str = "claude-haiku-4-5-20251001"
    base_url: str = "https://api.anthropic.com"
    api_key: str = ""  # set via cloud-init or `piclaw config set`
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: int = 60


@dataclass
class APIConfig:
    host: str = "0.0.0.0"
    port: int = 7842  # PiClaw web UI
    secret_key: str = ""  # JWT signing key, generated on first boot
    cors_origins: list = field(default_factory=lambda: ["*"])
    https: bool = False


@dataclass
class ShellConfig:
    enabled: bool = True
    allowlist: list = field(
        default_factory=lambda: [
            "ls",
            "cat",
            "echo",
            "pwd",
            "d",
            "free",
            "uname",
            "date",
            "whoami",
            "git",
            "python3",
            "pip",
            "pip3",
            "curl",
            "wget",
            "systemctl",
            "journalctl",
            "apt",
            "apt-get",
            "nano",
            "grep",
            "find",
            "ps",
            "top",
            "htop",
            "ip",
            "nmcli",
            "iwconfig",
            "ifconfig",
            "ping",
            "ss",
            "netstat",
            "gpio",
            "raspi-config",
            "vcgencmd",
            "reboot",
            "shutdown",
            "powerof",
        ]
    )
    blocklist: list = field(
        default_factory=lambda: [
            "rm -rf /",
            "mkfs",
            "dd if=/dev/zero",
            "> /dev/sd",
            "secrets.enc",
            ".secret_salt",
            "/etc/shadow",
            "passwd --",
            "useradd",
            "usermod",
            "visudo",
        ]
    )
    timeout: int = 30
    working_dir: str = str(Path.home())


@dataclass
class NetworkConfig:
    managed: bool = True  # allow agent to manage WiFi via nmcli


@dataclass
class GPIOConfig:
    enabled: bool = True
    warn_pins: list = field(default_factory=lambda: [2, 3])  # I2C pins


@dataclass
class ServicesConfig:
    managed: list = field(
        default_factory=lambda: [
            "piclaw-agent",
            "piclaw-api",
            "ollama",
            "homeassistant",
            "ssh",
            "avahi-daemon",
        ]
    )


@dataclass
class UpdaterConfig:
    auto_check: bool = True
    channel: str = "stable"  # stable | beta
    repo_url: str = "https://github.com/piclaw/piclaw"
    github_token: str = ""  # PAT für private Repos (git pull auth)


@dataclass
class TelegramConfig:
    token: str = ""
    chat_id: str = ""


@dataclass
class DiscordConfig:
    token: str = ""
    channel_id: int = 0
    allowed_users: list = field(default_factory=list)


@dataclass
class ThreemaConfig:
    gateway_id: str = ""
    api_secret: str = ""
    private_key_file: str = "/etc/piclaw/threema-private.key"
    recipient_id: str = ""
    webhook_path: str = "/webhook/threema"


@dataclass
class WhatsAppConfig:
    access_token: str = ""
    phone_number_id: str = ""
    app_secret: str = ""
    verify_token: str = "piclaw-whatsapp-verify"
    recipient: str = ""  # E.164 format: +49...


@dataclass
class AgentMailConfig:
    api_key: str = ""
    inbox_id: str = ""      # Primäre Inbox-ID (wird beim Setup oder Create gespeichert)
    email_address: str = ""  # dameon@agentmail.to


@dataclass
class LocationConfig:
    """Geolocation des Pi – wird im Setup-Wizard aus Lat/Lon gesetzt.

    Die Zeitzone wird automatisch via timezonefinder aus den Koordinaten
    ermittelt und per timedatectl auf dem System gesetzt. Danach nutzen
    alle datetime.now()-Aufrufe automatisch die korrekte Ortszeit
    inklusive Sommer/Winterzeit (DST).
    """
    latitude: float | None = None
    longitude: float | None = None
    timezone: str = ""   # IANA-String, z.B. "Europe/Berlin" – leer = nicht gesetzt
    city: str = ""       # optional, für Wetteranzeige/Briefing


@dataclass
class PiClawConfig:
    agent_name: str = "PiClaw"
    log_level: str = "INFO"
    llm: LLMConfig = field(default_factory=LLMConfig)
    api: APIConfig = field(default_factory=APIConfig)
    shell: ShellConfig = field(default_factory=ShellConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    gpio: GPIOConfig = field(default_factory=GPIOConfig)
    services: ServicesConfig = field(default_factory=ServicesConfig)
    updater: UpdaterConfig = field(default_factory=UpdaterConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    threema: ThreemaConfig = field(default_factory=ThreemaConfig)
    whatsapp: WhatsAppConfig = field(default_factory=WhatsAppConfig)
    agentmail: AgentMailConfig = field(default_factory=AgentMailConfig)
    location: LocationConfig = field(default_factory=LocationConfig)


def ensure_dirs():
    for d in [CONFIG_DIR, SKILLS_DIR, LOG_DIR, CRASH_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def _load_section(cls, raw: dict, key: str):
    return (
        cls(**{k: v for k, v in raw[key].items() if k in cls.__dataclass_fields__})
        if key in raw
        else cls()
    )


def load() -> PiClawConfig:
    ensure_dirs()
    if not CONFIG_FILE.exists():
        cfg = PiClawConfig()
        save(cfg)
        return cfg
    with open(CONFIG_FILE, "rb") as f:
        raw = tomllib.load(f)
    cfg = PiClawConfig()
    cfg.llm = _load_section(LLMConfig, raw, "llm")
    cfg.api = _load_section(APIConfig, raw, "api")
    cfg.shell = _load_section(ShellConfig, raw, "shell")
    cfg.network = _load_section(NetworkConfig, raw, "network")
    cfg.gpio = _load_section(GPIOConfig, raw, "gpio")
    cfg.services = _load_section(ServicesConfig, raw, "services")
    cfg.updater = _load_section(UpdaterConfig, raw, "updater")
    cfg.telegram = _load_section(TelegramConfig, raw, "telegram")
    cfg.discord = _load_section(DiscordConfig, raw, "discord")
    cfg.threema = _load_section(ThreemaConfig, raw, "threema")
    cfg.whatsapp = _load_section(WhatsAppConfig, raw, "whatsapp")
    cfg.agentmail = _load_section(AgentMailConfig, raw, "agentmail")
    cfg.location  = _load_section(LocationConfig,  raw, "location")
    cfg.agent_name = raw.get("agent_name", cfg.agent_name)
    cfg.log_level = raw.get("log_level", cfg.log_level)

    # Secrets aus verschlüsseltem Keyfile laden und in Config injizieren
    try:
        from piclaw.secrets import inject_secrets_into_config
        inject_secrets_into_config(cfg)
    except ImportError:
        pass  # cryptography nicht installiert — Secrets bleiben in config.toml
    except Exception as _sec_err:
        log.warning("Secrets laden fehlgeschlagen: %s", _sec_err)

    return cfg


def _strip_none(d: dict) -> dict:
    """Entfernt None-Werte rekursiv – TOML hat keinen Null-Typ."""
    cleaned = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, dict):
            cleaned[k] = _strip_none(v)
        else:
            cleaned[k] = v
    return cleaned


def save(cfg: PiClawConfig):
    ensure_dirs()
    data = _strip_none({
        "agent_name": cfg.agent_name,
        "log_level": cfg.log_level,
        "llm": asdict(cfg.llm),
        "api": asdict(cfg.api),
        "shell": asdict(cfg.shell),
        "network": asdict(cfg.network),
        "gpio": asdict(cfg.gpio),
        "services": asdict(cfg.services),
        "updater": asdict(cfg.updater),
        "telegram": asdict(cfg.telegram),
        "discord": asdict(cfg.discord),
        "threema": asdict(cfg.threema),
        "whatsapp": asdict(cfg.whatsapp),
        "agentmail": asdict(cfg.agentmail),
        "location":  asdict(cfg.location),
    })
    with open(CONFIG_FILE, "wb") as f:
        tomli_w.dump(data, f)
