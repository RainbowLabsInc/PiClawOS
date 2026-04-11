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
            new TextRun({ text: "PiClaw OS v0.15 – Manual  |  Page ", size: 18, color: "888888", font: "Arial" }),
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
        children: [new TextRun({ text: "Manual v0.15", size: 36, font: "Arial", color: DGRAY })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 0, after: 800 },
        children: [new TextRun({ text: "KI-Operating System f\u00FCr Raspberry Pi 5", size: 26, font: "Arial", color: DGRAY })]
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
      h2("1.1 System Requirements"),
      twoColTable([
        ["Hardware", "Raspberry Pi 5 (empfohlen) oder Pi 4"],
        ["Operating System", "Raspberry Pi OS Lite 64-bit (Bookworm oder Trixie)"],
        ["SD Card", "\u2265 16 GB"],
        ["RAM", "4 GB (8 GB empfohlen f\u00FCr lokale Modelle)"],
        ["Python", "3.11 oder h\u00F6her (getestet: 3.13.5)"],
        ["Internet Connection", "Ben\u00F6tigt f\u00FCr Installation und Cloud-LLM"]
      ]),
      p(""),
      h2("1.2 Features"),
      twoColTable([
        ["Multi-LLM-Routing", "Kimi K2 (NVIDIA NIM), Nemotron, Anthropic Claude, OpenAI, Ollama, Gemma 2B local"],
        ["Messaging Hub", "Telegram, Discord, Threema, WhatsApp, MQTT"],
        ["Home Assistant", "REST + WebSocket, 11 tools, real-time push events"],
        ["Marketplace Crawler", "Kleinanzeigen, eBay, eGun, willhaben, Troostwijk, Zoll-Auktion – new listings only"],
        ["Network Monitor", "LAN-Scan via nmap, neue Ger\u00E4te erkennen, Telegram-Alert"],
        ["Proactive Agent", "Morgenbriefing, Abendcheck, Schwellwert-Monitoring"],
        ["Hybrid Memory", "BM25 + vector search (QMD), persistent facts across conversations"],
        ["Watchdog", "Dienst- und Hardware-\u00DCberwachung"],
        ["Web-Dashboard", "8 Tabs: Dashboard \u00B7 Memory \u00B7 Agenten \u00B7 Soul \u00B7 Hardware \u00B7 Metriken \u00B7 Kamera \u00B7 Chat"],
        ["Installer Sub-Agent", "Dameon kann Software autonom installieren (mit Nutzer-Best\u00E4tigung)"],
        ["Tandem Browser", "Autonomous browser control, form filling, page reading"]
      ]),

      pageBreak(),

      // ── 2. Installation ───────────────────────────────────────
      h1("2. Installation"),
      h2("2.1 Method A – GitHub Clone (recommended)"),
      p("Diese Methode ben\u00F6tigt eine aktive SSH-Verbindung zum Pi und Internetzugang."),
      pCode("git clone https://github.com/RainbowLabsInc/PiClawOS.git"),
      pCode("cd PiClawOS/piclaw-os"),
      pCode("sudo bash install.sh"),
      p(""),
      h2("2.2 Method B – SD Card (offline)"),
      bullet("piclaw-sdcard.zip entpacken"),
      bullet("Den Ordner piclaw/ auf die bootfs-Partition der SD Card kopieren"),
      bullet("piclaw/piclaw.conf \u00F6ffnen und optionale Werte eintragen"),
      bullet("SD Card einlegen, Pi starten, 60 Sekunden warten"),
      bullet("SSH verbinden (das -t Flag ist Pflicht):"),
      pCode("ssh -t pi@piclaw.local"),
      bullet("Installer starten:"),
      pCode("# Raspberry Pi 5:"),
      pCode("sudo bash /boot/firmware/piclaw/install.sh"),
      pCode(""),
      pCode("# Raspberry Pi 4:"),
      pCode("sudo bash /boot/piclaw/install.sh"),
      p(""),
      h2("2.3 First-time Setup"),
      p("Nach der Installation den Configuration wizard starten:"),
      pCode("piclaw setup"),
      p("Der Wizard f\u00FChrt durch folgende Schritte:"),
      bullet("Configure agent name and mode"),
      bullet("LLM-Backend ausw\u00E4hlen (NVIDIA NIM, Anthropic, OpenAI, lokal)"),
      bullet("Register additional LLM backends (with purpose selection)"),
      bullet("Configure Telegram bot"),
      bullet("Connect Home Assistant (optional)"),
      bullet("Proactive Agent aktivieren"),
      bullet("Edit soul file"),
      p(""),
      h2("2.4 Systemstatus pr\u00FCfen"),
      pCode("piclaw doctor"),

      pageBreak(),

      // ── 3. LLM Configuration ──────────────────────────────────
      h1("3. LLM Configuration"),
      h2("3.1 Unterst\u00FCtzte Anbieter"),
      twoColTable([
        ["NVIDIA NIM (Kimi K2)", "nvapi-... \u2013 Recommended. Kimi K2 as primary backend."],
        ["NVIDIA NIM (Nemotron)", "nvapi-... \u2013 Secondary backend, auto-registered."],
        ["Anthropic Claude", "sk-ant-... \u2013 High-quality cloud alternative."],
        ["OpenAI GPT", "sk-... \u2013 Alternative cloud."],
        ["Ollama (lokal)", "Kein Key \u2013 Eigener Server auf dem Pi oder im Netzwerk."],
        ["Gemma 2B (offline)", "Kein Key \u2013 Lokal auf dem Pi, kein Internet n\u00F6tig."],
        ["Phi-3 Mini (offline)", "Kein Key \u2013 St\u00E4rkeres lokales Modell (~2.2 GB)."],
        ["TinyLlama (offline)", "Kein Key \u2013 Kleinstes Modell, sehr schnell (~0.7 GB)."]
      ]),
      p(""),
      h2("3.2 Fallback Order"),
      p("When a backend is unavailable, Dameon switches automatically:"),
      bullet("API 1: Kimi K2 (NVIDIA NIM) \u2013 Haupt-Backend, Priorit\u00E4t 8"),
      bullet("API 2: Nemotron (NVIDIA NIM) \u2013 Zweites Backend, Priorit\u00E4t 6"),
      bullet("Lokal: Gemma 2B \u2013 Offline-Fallback mit Hinweis an den Nutzer"),
      p(""),
      h2("3.3 Download Local Models"),
      pCode("piclaw model download               # Gemma 2B Q4 (Standard, ~1.6 GB)"),
      pCode("piclaw model download phi3-mini-q4  # Phi-3 Mini (~2.2 GB)"),
      pCode("piclaw model download tinyllama-q4  # TinyLlama (~0.7 GB, schnellstes)"),
      p(""),
      h2("3.4 Manage Registry"),
      pCode("piclaw llm list                    # Show all registered backends"),
      pCode("piclaw llm add --name mein-backend \\"),
      pCode("  --provider openai \\"),
      pCode("  --model moonshotai/kimi-k2-instruct-0905 \\"),
      pCode("  --api-key nvapi-... \\"),
      pCode("  --base-url https://integrate.api.nvidia.com/v1 \\"),
      pCode("  --priority 8 --tags coding,reasoning"),
      pCode("piclaw llm remove <name>           # Remove a backend"),
      pCode("piclaw llm update <name> --model <neues-modell>"),
      p("In chat, a backend can be addressed directly:"),
      pCode("[you] @nemotron Schreib mir ein Python Hello World"),

      pageBreak(),

      // ── 4. Messaging ──────────────────────────────────────────
      h1("4. Messaging"),
      h2("4.1 Telegram"),
      p("Telegram ist der prim\u00E4re Kommunikationskanal. Alle Nachrichten werden an Dameon weitergeleitet und beantwortet."),
      bullet("Bot erstellen: @BotFather in Telegram \u2192 /newbot"),
      bullet("Enter token and chat ID in piclaw setup"),
      bullet("Watchdog-Bot: separater Bot f\u00FCr Hardware-Alerts (eigener Token empfohlen)"),
      p(""),
      h2("4.2 Weitere Kan\u00E4le"),
      twoColTable([
        ["Discord", "Bot token + channel ID in piclaw setup"],
        ["WhatsApp", "Access token (Meta Cloud API) + Verify token"],
        ["Threema", "Threema Gateway ID and API key"],
        ["MQTT", "Broker-URL, Port, Topic-Pr\u00E4fix, optional TLS"]
      ]),

      pageBreak(),

      // ── 5. Network Monitor ───────────────────────────────────
      h1("5. Network Monitor"),
      p("Der Network Monitor scannt das lokale Netzwerk und meldet neue oder unbekannte Ger\u00E4te."),
      h2("5.1 Tools"),
      twoColTable([
        ["network_scan", "Alle Ger\u00E4te im LAN per nmap scannen"],
        ["port_scan", "Offene Ports eines bestimmten Ger\u00E4ts pr\u00FCfen"],
        ["check_new_devices", "Nur neue (bisher unbekannte) Ger\u00E4te melden"]
      ]),
      h2("5.2 Requirement"),
      pCode("sudo apt install nmap"),
      h2("5.3 Chat Example"),
      pCode("[you] Scan mein Heimnetzwerk"),
      pCode("[Dameon] Ich scanne das Netzwerk 192.168.178.0/24..."),
      pCode("         Gefunden: 12 Ger\u00E4te. 1 neues Ger\u00E4t: 192.168.178.55 (unbekannt)"),

      pageBreak(),

      // ── 6. Installer Sub-Agent ────────────────────────────────
      h1("6. Installer Sub-Agent"),
      p("Dameon kann Software autonom installieren. Jede Installation wird dem Nutzer zuerst zur Best\u00E4tigung vorgelegt."),
      h2("6.1 Usage"),
      p("Im Chat den @installer Pr\u00E4fix nutzen:"),
      pCode("[you] @installer Installiere Tandem aus github.com/hydro13/tandem-browser"),
      pCode("[Dameon] Installer-Subagent wurde gestartet."),
      pCode("         Plan: git clone + pip install -e ."),
      pCode("         Fortfahren? [j/N]"),
      h2("6.2 Unterst\u00FCtzte Quellen"),
      bullet("GitHub-Repositories (Whitelist vertrauensw\u00FCrdiger Repos)"),
      bullet("pip packages"),
      bullet("apt packages (with sudo)"),
      h2("6.3 Security"),
      p("Jeder Schritt wird vom Watchdog \u00FCberwacht. Ohne explizite Nutzer-Best\u00E4tigung wird nichts installiert. Der Installer-Subagent l\u00E4uft in einer isolierten Umgebung."),

      pageBreak(),

      // ── 7. Tandem Browser ──────────────────────────────────────
      h1("7. Tandem Browser (v0.19 \u2013 in Entwicklung)"),
      p("Der Tandem Browser gibt Dameon die F\u00E4higkeit, Webseiten autonom aufzurufen, zu navigieren und Inhalte zu extrahieren."),
      h2("7.1 Tools"),
      twoColTable([
        ["browser_open(url)", "Webseite \u00F6ffnen"],
        ["browser_click(selector)", "Click an element (CSS selector)"],
        ["browser_read()", "Extract page content as text"],
        ["browser_screenshot()", "Take a screenshot"]
      ]),
      h2("7.2 Scrapling"),
      p("Erg\u00E4nzend zu Tandem wird Scrapling f\u00FCr adaptives Web Scraping eingesetzt:"),
      bullet("Cloudflare bypass out of the box (StealthyFetcher)"),
      bullet("Adaptives Element-Tracking \u2013 findet Elemente auch nach Website-Redesign"),
      bullet("CSS / XPath / text / regex selectors"),

      pageBreak(),

      // ── 8. Home Assistant ─────────────────────────────────────
      h1("8. Home Assistant"),
      p("PiClaw OS integriert sich vollst\u00E4ndig mit Home Assistant \u00FCber REST + WebSocket."),
      h2("8.1 Configuration"),
      pCode("piclaw setup  \u2192 Schritt 'Home Assistant'"),
      p("Ben\u00F6tigt: HA-URL (z.B. http://192.168.1.10:8123) + Long-Lived Access Token"),
      h2("8.2 Verf\u00FCgbare Tools"),
      twoColTable([
        ["ha_get_state", "Query the state of an entity"],
        ["ha_list_entities", "List all entities"],
        ["ha_turn_on/off/toggle", "Ger\u00E4t ein-/ausschalten"],
        ["ha_set_temperature", "Set thermostat temperature"],
        ["ha_media", "Mediensteuerung (Play, Pause, Lautst\u00E4rke)"],
        ["ha_summary", "Zusammenfassung aller wichtigen Zust\u00E4nde"],
        ["ha_trigger_automation", "Automation ausf\u00FChren"],
        ["ha_run_script", "Start a script"],
        ["ha_call_service", "Call any service"],
        ["emergency_network_off", "Emergency network shutdown (v0.17)"]
      ]),

      pageBreak(),

      // ── 9. Web Dashboard ──────────────────────────────────────
      h1("9. Web Dashboard"),
      p("Das Web-Dashboard ist \u00FCber Port 7842 erreichbar:"),
      pCode("http://piclaw.local:7842"),
      p("or via IP address:"),
      pCode("http://192.168.178.120:7842"),
      h2("9.1 Tabs"),
      twoColTable([
        ["Dashboard", "System\u00FCbersicht, CPU/RAM/Temp, Service-Status"],
        ["Memory", "Search and manage stored facts"],
        ["Agenten", "Sub-Agenten erstellen, starten, stoppen und l\u00F6schen"],
        ["Soul", "Pers\u00F6nlichkeitsdatei (SOUL.md) direkt im Browser bearbeiten"],
        ["Hardware", "I2C scan, GPIO, sensors, camera"],
        ["Metriken", "Live charts: CPU temperature, RAM, CPU load"],
        ["Kamera", "Live snapshot, AI image description"],
        ["Chat", "Chat with Dameon directly in the browser"]
      ]),
      h2("9.2 API Token"),
      pCode("piclaw config token   # Token anzeigen"),

      pageBreak(),

      // ── 10. CLI Reference ───────────────────────────────────────
      h1("10. CLI Reference"),
      twoColTable([
        ["piclaw", "Start chatting with the agent"],
        ["piclaw setup", "Configuration wizard"],
        ["piclaw doctor", "Systemstatus pr\u00FCfen"],
        ["piclaw start / stop", "Start / stop all services"],
        ["piclaw model download [id]", "Download a local model"],
        ["piclaw model list", "Alle verf\u00FCgbaren Modelle anzeigen"],
        ["piclaw llm list", "Show registered LLM backends"],
        ["piclaw llm add --name ...", "Register a new backend"],
        ["piclaw llm remove <name>", "Remove a backend"],
        ["piclaw llm update <name> ...", "Backend-Einstellungen \u00E4ndern"],
        ["piclaw agent list", "List sub-agents"],
        ["piclaw agent start <id>", "Start a sub-agent"],
        ["piclaw soul show", "Show soul file"],
        ["piclaw soul edit", "Edit soul file"],
        ["piclaw routine list", "List routines"],
        ["piclaw routine enable <n>", "Enable a routine"],
        ["piclaw briefing morning", "Show morning briefing immediately"],
        ["piclaw backup", "Create a backup"],
        ["piclaw metrics", "Show current metrics"],
        ["piclaw camera snapshot", "Take a photo"]
      ]),

      pageBreak(),

      // ── 11. System Services ─────────────────────────────────────
      h1("11. System Services"),
      twoColTable([
        ["piclaw-api", "REST API + Web Dashboard (port 7842)"],
        ["piclaw-agent", "Main agent daemon"],
        ["piclaw-watchdog", "Hardware- und Dienst-\u00DCberwachung (isolierter User)"],
        ["piclaw-crawler", "Background crawler sub-agent"],
        ["piclaw-tandem (optional)", "Tandem Browser Service"]
      ]),
      p(""),
      h2("Restart services"),
      pCode("sudo systemctl restart piclaw-api piclaw-agent"),
      p(""),
      h2("View logs"),
      pCode("sudo tail -f /var/log/piclaw/api.log"),
      pCode("sudo tail -f /var/log/piclaw/agent.log"),
      pCode("journalctl -u piclaw-api -f"),

      pageBreak(),

      // ── 12. Soul System ───────────────────────────────────────
      h1("12. Soul System"),
      p("Die SOUL.md Datei definiert die Pers\u00F6nlichkeit, Ziele und Verhaltensregeln von Dameon. Ihr Inhalt wird bei jedem Gespr\u00E4ch als erster Block in den System-Prompt eingef\u00FCgt."),
      h2("Pfad"),
      pCode("/etc/piclaw/SOUL.md"),
      h2("Bearbeiten"),
      pCode("piclaw soul edit          # Edit in editor"),
      pCode("piclaw soul show          # Show current content"),
      pCode("piclaw soul reset         # Restore default soul"),
      p("Oder direkt im Web-Dashboard unter dem Tab 'Soul'."),

      pageBreak(),

      // ── 13. Watchdog ──────────────────────────────────────────
      h1("13. Watchdog"),
      p("Der Watchdog l\u00E4uft als isolierter Systembenutzer (piclaw-watchdog) und \u00FCberwacht alle PiClaw-Dienste sowie die Hardware."),
      h2("Configuration"),
      pCode("/etc/piclaw/watchdog.toml"),
      twoColTable([
        ["temp_warn_c", "Warnung bei \u00FCberschreitung (Standard: 75\u00B0C)"],
        ["temp_crit_c", "Kritisch-Schwelle (Standard: 80\u00B0C)"],
        ["disk_warn_pct", "Disk warning (default: 85%)"],
        ["ram_warn_pct", "RAM warning (default: 90%)"],
        ["telegram_token", "Separater Bot-Token f\u00FCr Watchdog-Alerts"],
        ["heartbeat_timeout", "Seconds until heartbeat alarm (default: 90s)"]
      ]),

      pageBreak(),

      // ── 14. Troubleshooting ────────────────────────────────────
      h1("14. Troubleshooting"),
      twoColTable([
        ["piclaw doctor shows errors", "API-Key in config.toml pr\u00FCfen; piclaw setup ausf\u00FChren"],
        ["API not responding", "sudo systemctl restart piclaw-api; Logs pr\u00FCfen"],
        ["Dameon not responding", "piclaw doctor; LLM health pr\u00FCfen; API-Key g\u00FCltig?"],
        ["WebSocket 401 error", "sudo systemctl restart piclaw-api (reload token)"],
        ["No local model", "piclaw model download ausf\u00FChren (~1.6 GB)"],
        ["High CPU temperature", "Thermal routing active: Dameon switches to cloud API"],
        ["Sub-agent not starting", "piclaw agent list; sa_registry.json pr\u00FCfen"],
        ["Installer fails", "Quelle in Whitelist? Internet Connection? Logs prüfen"]
      ]),

      pageBreak(),

      // ── 15. Version History ───────────────────────────────────
      h1("15. Version History"),
      twoColTable([
        ["v0.15 (M\u00E4rz 2026)", "Network Monitor, Parallele Queue, Installer Sub-Agent, Tandem Browser, Multi-LLM Registry, NVIDIA NIM Integration"],
        ["v0.14 (M\u00E4rz 2026)", "Queue system, llama.cpp output fix, router fallback fix"],
        ["v0.13 (M\u00E4rz 2026)", "Proactive Agent, Debugging-Runden, Stabilisierung"],
        ["v0.12 (M\u00E4rz 2026)", "Home Assistant integration"],
        ["v0.11 (M\u00E4rz 2026)", "Boot partition installer, piclaw.conf"],
        ["v0.10 (M\u00E4rz 2026)", "Metrics, camera, MQTT, backup & restore"],
        ["v0.9 (M\u00E4rz 2026)", "Setup wizard, API authentication, sub-agent sandboxing"],
        ["v0.8 (M\u00E4rz 2026)", "Soul system, sub-agents, multi-LLM routing, QMD memory"]
      ]),
      p(""),
      p("Vollst\u00E4ndiges Changelog: CHANGELOG.md"),
      p("Roadmap: ROADMAP.md"),
    ]
  }]
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync('/home/claude/PiClaw-OS-Manual-v0.15-EN.docx', buf);
  console.log('Manual EN created.');
});
