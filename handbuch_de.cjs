const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
         HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType,
         LevelFormat, PageNumber, Footer, PageBreak } = require('/home/claude/.npm-global/lib/node_modules/docx');
const fs = require("fs");

const BLUE   = "1F4E79";
const LBLUE  = "D6E4F0";
const DGRAY  = "404040";
const LGRAY  = "F5F5F5";
const GREEN  = "1D6B34";
const LGREEN = "E8F5E9";

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const noBorder = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const noBorders = { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder };

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 120 },
    children: [new TextRun({ text, bold: true, size: 36, color: BLUE, font: "Arial" })]
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 240, after: 80 },
    children: [new TextRun({ text, bold: true, size: 28, color: BLUE, font: "Arial" })]
  });
}
function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 160, after: 60 },
    children: [new TextRun({ text, bold: true, size: 24, color: DGRAY, font: "Arial" })]
  });
}
function p(text, opts = {}) {
  return new Paragraph({
    spacing: { before: 60, after: 100 },
    children: [new TextRun({ text, size: 22, font: "Arial", ...opts })]
  });
}
function pBold(text) { return p(text, { bold: true }); }
function pCode(text) {
  return new Paragraph({
    spacing: { before: 40, after: 40 },
    shading: { fill: "F0F0F0", type: ShadingType.CLEAR },
    indent: { left: 360 },
    children: [new TextRun({ text, size: 18, font: "Courier New", color: "1A1A1A" })]
  });
}
function bullet(text) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: { before: 40, after: 40 },
    children: [new TextRun({ text, size: 22, font: "Arial" })]
  });
}
function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}
function divider() {
  return new Paragraph({
    spacing: { before: 120, after: 120 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC" } },
    children: [new TextRun("")]
  });
}
function twoColTable(rows, col1w = 3000, col2w = 6360) {
  return new Table({
    width: { size: col1w + col2w, type: WidthType.DXA },
    columnWidths: [col1w, col2w],
    rows: rows.map(([a, b]) => new TableRow({
      children: [
        new TableCell({
          borders,
          width: { size: col1w, type: WidthType.DXA },
          shading: { fill: LGRAY, type: ShadingType.CLEAR },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ children: [new TextRun({ text: a, bold: true, size: 20, font: "Arial" })] })]
        }),
        new TableCell({
          borders,
          width: { size: col2w, type: WidthType.DXA },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ children: [new TextRun({ text: b, size: 20, font: "Arial" })] })]
        })
      ]
    }))
  });
}

const doc = new Document({
  numbering: {
    config: [{
      reference: "bullets",
      levels: [{ level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } } }]
    }]
  },
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Arial", color: BLUE },
        paragraph: { spacing: { before: 360, after: 120 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: BLUE },
        paragraph: { spacing: { before: 240, after: 80 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: DGRAY },
        paragraph: { spacing: { before: 160, after: 60 }, outlineLevel: 2 } },
    ]
  },
  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
      }
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: "PiClaw OS v0.15 – Handbuch  |  Seite ", size: 18, color: "888888", font: "Arial" }),
            new TextRun({ children: [PageNumber.CURRENT] })
          ]
        })]
      })
    },
    children: [
      // ── Titelseite ────────────────────────────────────────────
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 2000, after: 200 },
        children: [new TextRun({ text: "PiClaw OS", bold: true, size: 72, font: "Arial", color: BLUE })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 0, after: 200 },
        children: [new TextRun({ text: "Handbuch v0.15", size: 36, font: "Arial", color: DGRAY })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 0, after: 800 },
        children: [new TextRun({ text: "KI-Betriebssystem f\u00FCr Raspberry Pi 5", size: 26, font: "Arial", color: DGRAY })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 0, after: 200 },
        children: [new TextRun({ text: "M\u00E4rz 2026", size: 22, font: "Arial", color: "888888" })]
      }),
      pageBreak(),

      // ── 1. \u00DCberblick ──────────────────────────────────────────
      h1("1. \u00DCberblick"),
      p("PiClaw OS verwandelt einen Raspberry Pi in einen autonomen KI-Assistenten, der rund um die Uhr l\u00E4uft. Der Agent Dameon verarbeitet Nachrichten \u00FCber Telegram, Discord, WhatsApp und weitere Kan\u00E4le, steuert Smart-Home-Ger\u00E4te via Home Assistant, durchsucht Marktpl\u00E4tze, \u00FCberwacht das Netzwerk und meldet sich proaktiv bei wichtigen Ereignissen."),
      p(""),
      h2("1.1 Systemvoraussetzungen"),
      twoColTable([
        ["Hardware", "Raspberry Pi 5 (empfohlen) oder Pi 4"],
        ["Betriebssystem", "Raspberry Pi OS Lite 64-bit (Bookworm oder Trixie)"],
        ["SD-Karte", "\u2265 16 GB"],
        ["RAM", "4 GB (8 GB empfohlen f\u00FCr lokale Modelle)"],
        ["Python", "3.11 oder h\u00F6her (getestet: 3.13.5)"],
        ["Internetverbindung", "Ben\u00F6tigt f\u00FCr Installation und Cloud-LLM"]
      ]),
      p(""),
      h2("1.2 Hauptfunktionen"),
      twoColTable([
        ["Multi-LLM-Routing", "Kimi K2 (NVIDIA NIM), Nemotron, Anthropic Claude, OpenAI, Ollama, Gemma 2B lokal"],
        ["Messaging Hub", "Telegram, Discord, Threema, WhatsApp, MQTT"],
        ["Home Assistant", "REST + WebSocket, 11 Tools, Echtzeit-Push-Events"],
        ["Marktplatz-Crawler", "Kleinanzeigen.de, eBay.de, Websuche – nur neue Inserate"],
        ["Netzwerk-Monitor", "LAN-Scan via nmap, neue Ger\u00E4te erkennen, Telegram-Alert"],
        ["Proaktiver Agent", "Morgenbriefing, Abendcheck, Schwellwert-Monitoring"],
        ["Hybrid Memory", "BM25 + Vektorsuche (QMD), persistente Fakten"],
        ["Watchdog", "Dienst- und Hardware-\u00DCberwachung"],
        ["Web-Dashboard", "8 Tabs: Dashboard \u00B7 Memory \u00B7 Agenten \u00B7 Soul \u00B7 Hardware \u00B7 Metriken \u00B7 Kamera \u00B7 Chat"],
        ["Installer Sub-Agent", "Dameon kann Software autonom installieren (mit Nutzer-Best\u00E4tigung)"],
        ["Tandem Browser", "Autonomes Browser-Steuern, Formularausfüllen, Webseiten lesen"]
      ]),

      pageBreak(),

      // ── 2. Installation ───────────────────────────────────────
      h1("2. Installation"),
      h2("2.1 Methode A – GitHub Clone (empfohlen)"),
      p("Diese Methode ben\u00F6tigt eine aktive SSH-Verbindung zum Pi und Internetzugang."),
      pCode("git clone https://github.com/RainbowLabsInc/PiClawOS.git"),
      pCode("cd PiClawOS/piclaw-os"),
      pCode("sudo bash install.sh"),
      p(""),
      h2("2.2 Methode B – SD-Karte (offline)"),
      bullet("piclaw-sdcard.zip entpacken"),
      bullet("Den Ordner piclaw/ auf die bootfs-Partition der SD-Karte kopieren"),
      bullet("piclaw/piclaw.conf \u00F6ffnen und optionale Werte eintragen"),
      bullet("SD-Karte einlegen, Pi starten, 60 Sekunden warten"),
      bullet("SSH verbinden (das -t Flag ist Pflicht):"),
      pCode("ssh -t pi@piclaw.local"),
      bullet("Installer starten:"),
      pCode("# Raspberry Pi 5:"),
      pCode("sudo bash /boot/firmware/piclaw/install.sh"),
      pCode(""),
      pCode("# Raspberry Pi 4:"),
      pCode("sudo bash /boot/piclaw/install.sh"),
      p(""),
      h2("2.3 Ersteinrichtung"),
      p("Nach der Installation den Konfigurations-Wizard starten:"),
      pCode("piclaw setup"),
      p("Der Wizard f\u00FChrt durch folgende Schritte:"),
      bullet("Agent-Name und Modus konfigurieren"),
      bullet("LLM-Backend ausw\u00E4hlen (NVIDIA NIM, Anthropic, OpenAI, lokal)"),
      bullet("Weitere LLM-Backends registrieren (mit Zweck-Auswahl)"),
      bullet("Telegram-Bot konfigurieren"),
      bullet("Home Assistant verbinden (optional)"),
      bullet("Proaktiver Agent aktivieren"),
      bullet("Soul-Datei bearbeiten"),
      p(""),
      h2("2.4 Systemstatus pr\u00FCfen"),
      pCode("piclaw doctor"),

      pageBreak(),

      // ── 3. LLM-Konfiguration ──────────────────────────────────
      h1("3. LLM-Konfiguration"),
      h2("3.1 Unterst\u00FCtzte Anbieter"),
      twoColTable([
        ["NVIDIA NIM (Kimi K2)", "nvapi-... \u2013 Empfohlen. Kimi K2 als Haupt-Backend."],
        ["NVIDIA NIM (Nemotron)", "nvapi-... \u2013 Zweites Backend, automatisch registriert."],
        ["Anthropic Claude", "sk-ant-... \u2013 Hochwertige Cloud-Alternative."],
        ["OpenAI GPT", "sk-... \u2013 Alternative Cloud."],
        ["Ollama (lokal)", "Kein Key \u2013 Eigener Server auf dem Pi oder im Netzwerk."],
        ["Gemma 2B (offline)", "Kein Key \u2013 Lokal auf dem Pi, kein Internet n\u00F6tig."],
        ["Phi-3 Mini (offline)", "Kein Key \u2013 St\u00E4rkeres lokales Modell (~2.2 GB)."],
        ["TinyLlama (offline)", "Kein Key \u2013 Kleinstes Modell, sehr schnell (~0.7 GB)."]
      ]),
      p(""),
      h2("3.2 Fallback-Reihenfolge"),
      p("Wenn ein Backend nicht erreichbar ist, wechselt Dameon automatisch:"),
      bullet("API 1: Kimi K2 (NVIDIA NIM) \u2013 Haupt-Backend, Priorit\u00E4t 8"),
      bullet("API 2: Nemotron (NVIDIA NIM) \u2013 Zweites Backend, Priorit\u00E4t 6"),
      bullet("Lokal: Gemma 2B \u2013 Offline-Fallback mit Hinweis an den Nutzer"),
      p(""),
      h2("3.3 Lokale Modelle herunterladen"),
      pCode("piclaw model download               # Gemma 2B Q4 (Standard, ~1.6 GB)"),
      pCode("piclaw model download phi3-mini-q4  # Phi-3 Mini (~2.2 GB)"),
      pCode("piclaw model download tinyllama-q4  # TinyLlama (~0.7 GB, schnellstes)"),
      p(""),
      h2("3.4 Registry verwalten"),
      pCode("piclaw llm list                    # Alle registrierten Backends anzeigen"),
      pCode("piclaw llm add --name mein-backend \\"),
      pCode("  --provider openai \\"),
      pCode("  --model moonshotai/kimi-k2-instruct-0905 \\"),
      pCode("  --api-key nvapi-... \\"),
      pCode("  --base-url https://integrate.api.nvidia.com/v1 \\"),
      pCode("  --priority 8 --tags coding,reasoning"),
      pCode("piclaw llm remove <name>           # Backend entfernen"),
      pCode("piclaw llm update <name> --model <neues-modell>"),
      p("Im Chat kann ein Backend direkt angesprochen werden:"),
      pCode("[you] @nemotron Schreib mir ein Python Hello World"),

      pageBreak(),

      // ── 4. Messaging ──────────────────────────────────────────
      h1("4. Messaging"),
      h2("4.1 Telegram"),
      p("Telegram ist der prim\u00E4re Kommunikationskanal. Alle Nachrichten werden an Dameon weitergeleitet und beantwortet."),
      bullet("Bot erstellen: @BotFather in Telegram \u2192 /newbot"),
      bullet("Token und Chat-ID in piclaw setup eintragen"),
      bullet("Watchdog-Bot: separater Bot f\u00FCr Hardware-Alerts (eigener Token empfohlen)"),
      p(""),
      h2("4.2 Weitere Kan\u00E4le"),
      twoColTable([
        ["Discord", "Bot-Token + Channel-ID in piclaw setup eintragen"],
        ["WhatsApp", "Access Token (Meta Cloud API) + Verify Token"],
        ["Threema", "Threema-Gateway-ID und API-Key"],
        ["MQTT", "Broker-URL, Port, Topic-Pr\u00E4fix, optional TLS"]
      ]),

      pageBreak(),

      // ── 5. Netzwerk-Monitor ───────────────────────────────────
      h1("5. Netzwerk-Monitor"),
      p("Der Netzwerk-Monitor scannt das lokale Netzwerk und meldet neue oder unbekannte Ger\u00E4te."),
      h2("5.1 Tools"),
      twoColTable([
        ["network_scan", "Alle Ger\u00E4te im LAN per nmap scannen"],
        ["port_scan", "Offene Ports eines bestimmten Ger\u00E4ts pr\u00FCfen"],
        ["check_new_devices", "Nur neue (bisher unbekannte) Ger\u00E4te melden"]
      ]),
      h2("5.2 Voraussetzung"),
      pCode("sudo apt install nmap"),
      h2("5.3 Beispiel im Chat"),
      pCode("[you] Scan mein Heimnetzwerk"),
      pCode("[Dameon] Ich scanne das Netzwerk 192.168.178.0/24..."),
      pCode("         Gefunden: 12 Ger\u00E4te. 1 neues Ger\u00E4t: 192.168.178.55 (unbekannt)"),

      pageBreak(),

      // ── 6. Installer Sub-Agent ────────────────────────────────
      h1("6. Installer Sub-Agent"),
      p("Dameon kann Software autonom installieren. Jede Installation wird dem Nutzer zuerst zur Best\u00E4tigung vorgelegt."),
      h2("6.1 Verwendung"),
      p("Im Chat den @installer Pr\u00E4fix nutzen:"),
      pCode("[you] @installer Installiere Tandem aus github.com/hydro13/tandem-browser"),
      pCode("[Dameon] Installer-Subagent wurde gestartet."),
      pCode("         Plan: git clone + pip install -e ."),
      pCode("         Fortfahren? [j/N]"),
      h2("6.2 Unterst\u00FCtzte Quellen"),
      bullet("GitHub-Repositories (Whitelist vertrauensw\u00FCrdiger Repos)"),
      bullet("pip-Pakete"),
      bullet("apt-Pakete (mit sudo)"),
      h2("6.3 Sicherheit"),
      p("Jeder Schritt wird vom Watchdog \u00FCberwacht. Ohne explizite Nutzer-Best\u00E4tigung wird nichts installiert. Der Installer-Subagent l\u00E4uft in einer isolierten Umgebung."),

      pageBreak(),

      // ── 7. Tandem Browser ──────────────────────────────────────
      h1("7. Tandem Browser (v0.19 \u2013 in Entwicklung)"),
      p("Der Tandem Browser gibt Dameon die F\u00E4higkeit, Webseiten autonom aufzurufen, zu navigieren und Inhalte zu extrahieren."),
      h2("7.1 Tools"),
      twoColTable([
        ["browser_open(url)", "Webseite \u00F6ffnen"],
        ["browser_click(selector)", "Element anklicken (CSS-Selektor)"],
        ["browser_read()", "Seiteninhalt als Text extrahieren"],
        ["browser_screenshot()", "Screenshot erstellen"]
      ]),
      h2("7.2 Scrapling"),
      p("Erg\u00E4nzend zu Tandem wird Scrapling f\u00FCr adaptives Web Scraping eingesetzt:"),
      bullet("Cloudflare Bypass out of the box (StealthyFetcher)"),
      bullet("Adaptives Element-Tracking \u2013 findet Elemente auch nach Website-Redesign"),
      bullet("CSS / XPath / Text / Regex Selektoren"),

      pageBreak(),

      // ── 8. Home Assistant ─────────────────────────────────────
      h1("8. Home Assistant"),
      p("PiClaw OS integriert sich vollst\u00E4ndig mit Home Assistant \u00FCber REST + WebSocket."),
      h2("8.1 Konfiguration"),
      pCode("piclaw setup  \u2192 Schritt 'Home Assistant'"),
      p("Ben\u00F6tigt: HA-URL (z.B. http://192.168.1.10:8123) + Long-Lived Access Token"),
      h2("8.2 Verf\u00FCgbare Tools"),
      twoColTable([
        ["ha_get_state", "Zustand einer Entity abfragen"],
        ["ha_list_entities", "Alle Entities auflisten"],
        ["ha_turn_on/off/toggle", "Ger\u00E4t ein-/ausschalten"],
        ["ha_set_temperature", "Thermostat-Temperatur setzen"],
        ["ha_media", "Mediensteuerung (Play, Pause, Lautst\u00E4rke)"],
        ["ha_summary", "Zusammenfassung aller wichtigen Zust\u00E4nde"],
        ["ha_trigger_automation", "Automation ausf\u00FChren"],
        ["ha_run_script", "Skript starten"],
        ["ha_call_service", "Beliebigen Service aufrufen"],
        ["emergency_network_off", "Netzwerk-Notabschaltung (v0.17)"]
      ]),

      pageBreak(),

      // ── 9. Web-Dashboard ──────────────────────────────────────
      h1("9. Web-Dashboard"),
      p("Das Web-Dashboard ist \u00FCber Port 7842 erreichbar:"),
      pCode("http://piclaw.local:7842"),
      p("oder mit der IP-Adresse:"),
      pCode("http://192.168.178.120:7842"),
      h2("9.1 Tabs"),
      twoColTable([
        ["Dashboard", "System\u00FCbersicht, CPU/RAM/Temp, Service-Status"],
        ["Memory", "Gespeicherte Fakten durchsuchen und verwalten"],
        ["Agenten", "Sub-Agenten erstellen, starten, stoppen und l\u00F6schen"],
        ["Soul", "Pers\u00F6nlichkeitsdatei (SOUL.md) direkt im Browser bearbeiten"],
        ["Hardware", "I2C-Scan, GPIO, Sensoren, Kamera"],
        ["Metriken", "Live-Charts: CPU-Temperatur, RAM, CPU-Auslastung"],
        ["Kamera", "Live-Snapshot, KI-Bildbeschreibung"],
        ["Chat", "Direkter Chat mit Dameon im Browser"]
      ]),
      h2("9.2 API-Token"),
      pCode("piclaw config token   # Token anzeigen"),

      pageBreak(),

      // ── 10. CLI-Referenz ───────────────────────────────────────
      h1("10. CLI-Referenz"),
      twoColTable([
        ["piclaw", "Chat mit dem Agenten starten"],
        ["piclaw setup", "Konfigurations-Wizard"],
        ["piclaw doctor", "Systemstatus pr\u00FCfen"],
        ["piclaw start / stop", "Alle Services starten / stoppen"],
        ["piclaw model download [id]", "Lokales Modell herunterladen"],
        ["piclaw model list", "Alle verf\u00FCgbaren Modelle anzeigen"],
        ["piclaw llm list", "Registrierte LLM-Backends anzeigen"],
        ["piclaw llm add --name ...", "Neues Backend registrieren"],
        ["piclaw llm remove <name>", "Backend entfernen"],
        ["piclaw llm update <name> ...", "Backend-Einstellungen \u00E4ndern"],
        ["piclaw agent list", "Sub-Agenten anzeigen"],
        ["piclaw agent start <id>", "Sub-Agent starten"],
        ["piclaw soul show", "Soul-Datei anzeigen"],
        ["piclaw soul edit", "Soul-Datei bearbeiten"],
        ["piclaw routine list", "Routinen anzeigen"],
        ["piclaw routine enable <n>", "Routine aktivieren"],
        ["piclaw briefing morning", "Morgenbriefing sofort ausgeben"],
        ["piclaw backup", "Backup erstellen"],
        ["piclaw metrics", "Aktuelle Metriken anzeigen"],
        ["piclaw camera snapshot", "Foto aufnehmen"]
      ]),

      pageBreak(),

      // ── 11. Systemdienste ─────────────────────────────────────
      h1("11. Systemdienste"),
      twoColTable([
        ["piclaw-api", "REST API + Web-Dashboard (Port 7842)"],
        ["piclaw-agent", "Haupt-Agent Daemon"],
        ["piclaw-watchdog", "Hardware- und Dienst-\u00DCberwachung (isolierter User)"],
        ["piclaw-crawler", "Hintergrund-Crawler Sub-Agent"],
        ["piclaw-tandem (optional)", "Tandem Browser Service"]
      ]),
      p(""),
      h2("Dienste neu starten"),
      pCode("sudo systemctl restart piclaw-api piclaw-agent"),
      p(""),
      h2("Logs anzeigen"),
      pCode("sudo tail -f /var/log/piclaw/api.log"),
      pCode("sudo tail -f /var/log/piclaw/agent.log"),
      pCode("journalctl -u piclaw-api -f"),

      pageBreak(),

      // ── 12. Soul-System ───────────────────────────────────────
      h1("12. Soul-System"),
      p("Die SOUL.md Datei definiert die Pers\u00F6nlichkeit, Ziele und Verhaltensregeln von Dameon. Ihr Inhalt wird bei jedem Gespr\u00E4ch als erster Block in den System-Prompt eingef\u00FCgt."),
      h2("Pfad"),
      pCode("/etc/piclaw/SOUL.md"),
      h2("Bearbeiten"),
      pCode("piclaw soul edit          # Im Editor bearbeiten"),
      pCode("piclaw soul show          # Aktuellen Inhalt anzeigen"),
      pCode("piclaw soul reset         # Standard-Soul wiederherstellen"),
      p("Oder direkt im Web-Dashboard unter dem Tab 'Soul'."),

      pageBreak(),

      // ── 13. Watchdog ──────────────────────────────────────────
      h1("13. Watchdog"),
      p("Der Watchdog l\u00E4uft als isolierter Systembenutzer (piclaw-watchdog) und \u00FCberwacht alle PiClaw-Dienste sowie die Hardware."),
      h2("Konfiguration"),
      pCode("/etc/piclaw/watchdog.toml"),
      twoColTable([
        ["temp_warn_c", "Warnung bei \u00FCberschreitung (Standard: 75\u00B0C)"],
        ["temp_crit_c", "Kritisch-Schwelle (Standard: 80\u00B0C)"],
        ["disk_warn_pct", "Festplatten-Warnung (Standard: 85 %)"],
        ["ram_warn_pct", "RAM-Warnung (Standard: 90 %)"],
        ["telegram_token", "Separater Bot-Token f\u00FCr Watchdog-Alerts"],
        ["heartbeat_timeout", "Sekunden bis Heartbeat-Alarm (Standard: 90 s)"]
      ]),

      pageBreak(),

      // ── 14. Fehlerbehebung ────────────────────────────────────
      h1("14. Fehlerbehebung"),
      twoColTable([
        ["piclaw doctor zeigt Fehler", "API-Key in config.toml pr\u00FCfen; piclaw setup ausf\u00FChren"],
        ["API antwortet nicht", "sudo systemctl restart piclaw-api; Logs pr\u00FCfen"],
        ["Dameon antwortet nicht", "piclaw doctor; LLM health pr\u00FCfen; API-Key g\u00FCltig?"],
        ["WebSocket 401 Fehler", "sudo systemctl restart piclaw-api (Token neu laden)"],
        ["Kein lokales Modell", "piclaw model download ausf\u00FChren (~1.6 GB)"],
        ["hohe CPU-Temperatur", "Thermisches Routing aktiv: Dameon wechselt zu Cloud-API"],
        ["Sub-Agent startet nicht", "piclaw agent list; sa_registry.json pr\u00FCfen"],
        ["Installer schlägt fehl", "Quelle in Whitelist? Internetverbindung? Logs prüfen"]
      ]),

      pageBreak(),

      // ── 15. Versionsverlauf ───────────────────────────────────
      h1("15. Versionsverlauf"),
      twoColTable([
        ["v0.15 (M\u00E4rz 2026)", "Netzwerk-Monitor, Parallele Queue, Installer Sub-Agent, Tandem Browser, Multi-LLM Registry, NVIDIA NIM Integration"],
        ["v0.14 (M\u00E4rz 2026)", "Queue-System, llama.cpp Output-Fix, Router-Fallback-Fix"],
        ["v0.13 (M\u00E4rz 2026)", "Proaktiver Agent, Debugging-Runden, Stabilisierung"],
        ["v0.12 (M\u00E4rz 2026)", "Home Assistant Integration"],
        ["v0.11 (M\u00E4rz 2026)", "Boot-Partition Installer, piclaw.conf"],
        ["v0.10 (M\u00E4rz 2026)", "Metriken, Kamera, MQTT, Backup & Restore"],
        ["v0.9 (M\u00E4rz 2026)", "Setup-Wizard, API-Authentifizierung, Sub-Agent Sandboxing"],
        ["v0.8 (M\u00E4rz 2026)", "Soul-System, Sub-Agenten, Multi-LLM-Routing, QMD Memory"]
      ]),
      p(""),
      p("Vollst\u00E4ndiges Changelog: CHANGELOG.md"),
      p("Roadmap: ROADMAP.md"),
    ]
  }]
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync('/home/claude/PiClaw-OS-Handbuch-v0.15.docx', buf);
  console.log('Handbuch DE erstellt.');
});
