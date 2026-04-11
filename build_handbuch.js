const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType,
  PageNumber, Footer, Header, TabStopType, TabStopPosition,
  LevelFormat, PageBreak, ExternalHyperlink
} = require('docx');
const fs = require('fs');

// ── Helpers ──────────────────────────────────────────────────────
const C = {
  accent:  "5B50E8",  // PiClaw purple
  accent2: "2196F3",  // blue
  dark:    "1A1A2E",
  gray:    "555555",
  light:   "F5F4FF",
  mid:     "EAE8FF",
  white:   "FFFFFF",
  green:   "2E7D32",
  code_bg: "F0F0F0",
};

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const noBorder = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const noBorders = { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder };

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    children: [new TextRun({ text, bold: true, font: "Arial", size: 36, color: C.accent })],
    spacing: { before: 480, after: 200 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: C.accent, space: 4 } }
  });
}
function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    children: [new TextRun({ text, bold: true, font: "Arial", size: 28, color: C.dark })],
    spacing: { before: 360, after: 140 },
  });
}
function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    children: [new TextRun({ text, bold: true, font: "Arial", size: 24, color: C.accent2 })],
    spacing: { before: 240, after: 100 },
  });
}
function p(text, opts = {}) {
  return new Paragraph({
    children: [new TextRun({ text, font: "Arial", size: 22, color: C.gray, ...opts })],
    spacing: { before: 80, after: 80 },
  });
}
function bold(text) {
  return new Paragraph({
    children: [new TextRun({ text, font: "Arial", size: 22, bold: true, color: C.dark })],
    spacing: { before: 80, after: 80 },
  });
}
function code(text) {
  return new Paragraph({
    children: [new TextRun({ text, font: "Courier New", size: 18, color: C.dark })],
    shading: { fill: C.code_bg, type: ShadingType.CLEAR },
    spacing: { before: 60, after: 60 },
    indent: { left: 360 },
    border: { left: { style: BorderStyle.SINGLE, size: 8, color: C.accent, space: 8 } }
  });
}
function bullet(text, level = 0) {
  return new Paragraph({
    numbering: { reference: "bullets", level },
    children: [new TextRun({ text, font: "Arial", size: 22, color: C.gray })],
    spacing: { before: 40, after: 40 },
  });
}
function spacer() {
  return new Paragraph({ children: [new TextRun("")], spacing: { before: 120, after: 120 } });
}
function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

function infoBox(title, lines, fillColor = C.light) {
  const rows = [];
  // Header row
  rows.push(new TableRow({
    children: [new TableCell({
      borders, columnSpan: 1,
      shading: { fill: C.accent, type: ShadingType.CLEAR },
      margins: { top: 100, bottom: 100, left: 160, right: 160 },
      children: [new Paragraph({ children: [new TextRun({ text: title, font: "Arial", size: 22, bold: true, color: C.white })] })]
    })]
  }));
  // Content rows
  for (const line of lines) {
    rows.push(new TableRow({
      children: [new TableCell({
        borders,
        shading: { fill: fillColor, type: ShadingType.CLEAR },
        margins: { top: 80, bottom: 80, left: 160, right: 160 },
        children: [new Paragraph({ children: [new TextRun({ text: line, font: "Arial", size: 21, color: C.dark })] })]
      })]
    }));
  }
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [9360],
    rows
  });
}

function twoColTable(rows_data, w1 = 3000, w2 = 6360) {
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [w1, w2],
    rows: rows_data.map(([a, b]) => new TableRow({
      children: [
        new TableCell({
          borders, width: { size: w1, type: WidthType.DXA },
          shading: { fill: C.mid, type: ShadingType.CLEAR },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ children: [new TextRun({ text: a, font: "Arial", size: 20, bold: true, color: C.dark })] })]
        }),
        new TableCell({
          borders, width: { size: w2, type: WidthType.DXA },
          margins: { top: 80, bottom: 80, left: 120, right: 120 },
          children: [new Paragraph({ children: [new TextRun({ text: b, font: "Arial", size: 20, color: C.gray })] })]
        }),
      ]
    }))
  });
}

// ── Cover Page ───────────────────────────────────────────────────
function coverPage() {
  return [
    spacer(), spacer(), spacer(),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "PiClaw OS", font: "Arial", size: 72, bold: true, color: C.accent })],
      spacing: { before: 0, after: 120 },
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "v0.15.0", font: "Arial", size: 32, color: C.accent2 })],
      spacing: { before: 0, after: 240 },
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "KI-Betriebssystem für den Raspberry Pi 5", font: "Arial", size: 28, color: C.gray })],
      spacing: { before: 0, after: 600 },
    }),
    new Table({
      width: { size: 6000, type: WidthType.DXA },
      columnWidths: [6000],
      rows: [new TableRow({ children: [new TableCell({
        borders: { top: { style: BorderStyle.SINGLE, size: 8, color: C.accent }, bottom: noBorder, left: noBorder, right: noBorder },
        shading: { fill: C.light, type: ShadingType.CLEAR },
        margins: { top: 240, bottom: 240, left: 360, right: 360 },
        children: [
          new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Dameon — Dein persönlicher KI-Agent", font: "Arial", size: 24, bold: true, color: C.dark })], spacing: { before: 0, after: 80 } }),
          new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Raspberry Pi 5 · Kimi K2 · Gemma 2B · NVIDIA NIM", font: "Arial", size: 20, color: C.gray })], spacing: { before: 0, after: 0 } }),
        ]
      })]})],
    }),
    spacer(), spacer(), spacer(), spacer(), spacer(),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: "März 2026", font: "Arial", size: 22, color: C.gray })],
    }),
    pageBreak(),
  ];
}

// ── Document ─────────────────────────────────────────────────────
const doc = new Document({
  numbering: {
    config: [
      { reference: "bullets", levels: [
        { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 480, hanging: 240 } } } },
        { level: 1, format: LevelFormat.BULLET, text: "–", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 960, hanging: 240 } } } },
      ]},
    ]
  },
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 36, bold: true, font: "Arial", color: C.accent },
        paragraph: { spacing: { before: 480, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial", color: C.dark },
        paragraph: { spacing: { before: 360, after: 140 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, font: "Arial", color: C.accent2 },
        paragraph: { spacing: { before: 240, after: 100 }, outlineLevel: 2 } },
    ]
  },
  sections: [{
    properties: {
      page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, right: 1134, bottom: 1134, left: 1134 } }
    },
    headers: {
      default: new Header({ children: [
        new Paragraph({
          children: [
            new TextRun({ text: "PiClaw OS v0.15 — Handbuch", font: "Arial", size: 18, color: C.gray }),
          ],
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: C.accent, space: 4 } },
          spacing: { after: 0 }
        })
      ]})
    },
    footers: {
      default: new Footer({ children: [
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [
            new TextRun({ text: "Seite ", font: "Arial", size: 18, color: C.gray }),
            new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 18, color: C.gray }),
            new TextRun({ text: " von ", font: "Arial", size: 18, color: C.gray }),
            new TextRun({ children: [PageNumber.TOTAL_PAGES], font: "Arial", size: 18, color: C.gray }),
          ],
          border: { top: { style: BorderStyle.SINGLE, size: 4, color: C.accent, space: 4 } },
          spacing: { before: 80 }
        })
      ]})
    },
    children: [
      // ── Cover ──
      ...coverPage(),

      // ── Kap 1: Überblick ──
      h1("1. Was ist PiClaw OS?"),
      p("PiClaw OS ist ein KI-Betriebssystem für den Raspberry Pi 5. Anstatt einen Cloud-Assistenten zu nutzen, der nach jedem Gespräch alles vergisst, lebt Dameon — dein persönlicher KI-Agent — dauerhaft auf deinem Pi."),
      spacer(),
      p("Dameon kennt deine Hardware, merkt sich Entscheidungen und Präferenzen, führt eigenständig Aufgaben aus und ist per Telegram, Discord oder Web-Dashboard erreichbar — auch wenn kein Internet verfügbar ist."),
      spacer(),
      infoBox("Kernfunktionen", [
        "🤖  Dauerhafter KI-Agent mit persistentem Gedächtnis (QMD + MEMORY.md)",
        "📡  Erreichbar via Telegram, Discord, WhatsApp, Web-Dashboard",
        "🔍  Marktplatzsuche: Kleinanzeigen, eBay, eGun, willhaben, Troostwijk, Zoll-Auktion — neue Inserate als Alert",
        "🌡  Thermisches LLM-Routing: cloud bei Überhitzung, lokal im Normalbetrieb",
        "🤖  Sub-Agenten: spezialisierte KI-Helfer für Suche, Installation, Monitoring",
        "🔌  Home Assistant Integration: Lichter, Thermostate, Szenen per Sprache",
        "🛡  Watchdog: unabhängiger Sicherheits-Daemon, append-only Logs",
        "📊  Metriken-Dashboard mit Live-Charts im Browser",
        "🔄  Self-Update: piclaw update — git pull + Neustart ohne root",
      ]),
      pageBreak(),

      // ── Kap 2: Installation ──
      h1("2. Installation"),
      h2("2.1 Voraussetzungen"),
      twoColTable([
        ["Hardware", "Raspberry Pi 5 (4 GB oder 8 GB empfohlen)"],
        ["OS", "Raspberry Pi OS Lite 64-bit (bookworm)"],
        ["Speicher", "16 GB SD-Karte minimum, 32 GB empfohlen"],
        ["Internet", "Für Online-Installation und Cloud-LLM erforderlich"],
        ["LLM-Key (optional)", "NVIDIA NIM API-Key (nvapi-...) für Cloud-KI"],
      ]),
      spacer(),
      h2("2.2 Online-Installation (empfohlen)"),
      p("Die einfachste Methode — der Installer lädt alles automatisch von GitHub:"),
      spacer(),
      code("# Schritt 1: SD-Karte mit Raspberry Pi Imager flashen"),
      code("# → Raspberry Pi OS Lite 64-bit, SSH + WLAN in den Einstellungen aktivieren"),
      spacer(),
      code("# Schritt 2: Pi booten und verbinden"),
      code("ssh DEIN_USER@piclaw.local"),
      spacer(),
      code("# Schritt 3: Installer laden und ausführen"),
      code("curl -sO https://raw.githubusercontent.com/RainbowLabsInc/PiClawOS/main/piclaw-os/boot/piclaw/install.sh"),
      code("sudo bash install.sh"),
      spacer(),
      p("Dauer: ca. 5–10 Minuten. Am Ende startet PiClaw automatisch."),
      spacer(),
      h2("2.3 Offline-Installation (SD-Karte)"),
      p("Für Installationen ohne Internet — alle Dateien befinden sich auf der SD-Karte:"),
      spacer(),
      code("# Im piclaw-os/ Verzeichnis auf dem PC:"),
      code("make sync     # befüllt piclaw-src/ mit aktuellem Code"),
      code("make sdcard   # erstellt piclaw-sdcard-v0.15.0.zip"),
      spacer(),
      p("ZIP entpacken, Ordner boot/piclaw/ auf die Boot-Partition der SD-Karte kopieren."),
      code("sudo bash /boot/piclaw/install.sh"),
      spacer(),
      h2("2.4 Ersteinrichtung nach Installation"),
      code("piclaw setup    # interaktiver Wizard: LLM-Key, Telegram, Soul, Fan"),
      code("piclaw doctor   # Systemcheck"),
      code("piclaw          # KI-Chat starten"),
      spacer(),
      infoBox("Nach der Installation erreichbar", [
        "Web-Dashboard:   http://piclaw.local:7842",
        "KI-Chat:         ssh pi@piclaw.local  →  piclaw",
        "Telegram:        nach Setup direkt im Chat schreiben",
        "API:             http://piclaw.local:7842/api/stats",
      ]),
      pageBreak(),

      // ── Kap 3: Erste Schritte ──
      h1("3. Erste Schritte"),
      h2("3.1 Der KI-Chat"),
      p("Der einfachste Einstieg: direkt im Terminal eintippen:"),
      code("piclaw"),
      spacer(),
      p("PiClaw verbindet sich mit dem laufenden Daemon (schnelle Antworten). Ist der Daemon nicht erreichbar, startet PiClaw im Offline-Modus mit dem lokalen Gemma-Modell."),
      spacer(),
      h2("3.2 Beispiel-Gespräche"),
      twoColTable([
        ["Systemstatus", "\"Wie warm ist der Pi gerade?\" / \"Zeig mir RAM und CPU\""],
        ["Marktplatz", "\"Suche Raspberry Pi 5 auf Kleinanzeigen in 22081 Umkreis 20km\""],
        ["Dienste", "\"Starte den SSH-Dienst\" / \"Ist Homeassistant aktiv?\""],
        ["Memory", "\"Merke dir: ich bevorzuge Antworten auf Deutsch\""],
        ["Sub-Agent", "\"Erstelle einen Agenten der täglich um 7 Uhr den CPU-Status prüft\""],
        ["WLAN", "\"Verbinde mit Netzwerk MeinWLAN, Passwort xyz\""],
        ["Update", "\"Gibt es Updates?\" / piclaw update"],
      ], 2800, 6560),
      spacer(),
      h2("3.3 Wichtige Befehle"),
      twoColTable([
        ["piclaw", "KI-Chat öffnen"],
        ["piclaw doctor", "Vollständiger Systemcheck"],
        ["piclaw setup", "Interaktiver Konfigurationsassistent"],
        ["piclaw update", "PiClaw auf neuesten Stand bringen"],
        ["piclaw update check", "Ausstehende Updates anzeigen"],
        ["piclaw model download", "Gemma 2B lokal herunterladen (~1.6 GB)"],
        ["piclaw agent list", "Alle Sub-Agenten auflisten"],
        ["piclaw soul show", "Aktuelle Persönlichkeitsdatei anzeigen"],
        ["piclaw llm list", "Registrierte LLM-Backends anzeigen"],
        ["piclaw backup", "Konfiguration sichern"],
      ]),
      pageBreak(),

      // ── Kap 4: KI-Backends ──
      h1("4. KI-Backends"),
      h2("4.1 Multi-LLM-Router"),
      p("PiClaw kann mehrere KI-Backends gleichzeitig verwalten und wählt automatisch das passende für jede Anfrage — basierend auf Tags, Priorität und Temperatur des Pi."),
      spacer(),
      h2("4.2 NVIDIA NIM (Standard)"),
      p("Kimi K2 und Nemotron 70B laufen in der Cloud auf NVIDIA-Hardware. Kein eigener GPU nötig."),
      spacer(),
      twoColTable([
        ["API-Key", "nvapi-... von https://build.nvidia.com"],
        ["Kimi K2 Modell-ID", "moonshotai/kimi-k2-instruct-0905"],
        ["Nemotron Modell-ID", "nvidia/llama-3.1-nemotron-70b-instruct"],
        ["Base URL", "https://integrate.api.nvidia.com/v1"],
        ["Temperature", "0.6 für Kimi K2 (empfohlen von NVIDIA)"],
      ]),
      spacer(),
      code("piclaw llm list                        # aktuell registrierte Backends"),
      code("piclaw llm add --name kimi --provider openai \\"),
      code("  --model moonshotai/kimi-k2-instruct-0905 \\"),
      code("  --api-key nvapi-DEIN-KEY \\"),
      code("  --base-url https://integrate.api.nvidia.com/v1 --priority 8"),
      spacer(),
      h2("4.3 Lokales Modell (Gemma 2B)"),
      p("Für den Offline-Betrieb oder wenn die Cloud nicht erreichbar ist:"),
      spacer(),
      code("piclaw model download    # lädt Gemma 2B Q4 herunter (~1.6 GB)"),
      code("# Modell liegt danach in: /etc/piclaw/models/gemma-2b-q4.gguf"),
      spacer(),
      p("Gemma 2B benötigt ~2.2 GB RAM und antwortet in 10–30 Sekunden auf dem Pi 5."),
      spacer(),
      h2("4.4 Thermisches Routing"),
      p("Bei hoher CPU-Temperatur schaltet PiClaw automatisch auf Cloud-Backends um:"),
      spacer(),
      twoColTable([
        ["< 55°C (cool)", "Lokales Modell erlaubt, Cloud optional"],
        ["55–70°C (warm)", "Monitoring, lokales Modell noch OK"],
        ["70–80°C (hot)", "Cloud bevorzugt, lokales Modell möglich"],
        ["80–85°C (critical)", "Nur Cloud, lokales Modell deaktiviert"],
        ["> 85°C (emergency)", "Alles gedrosselt, Telegram-Alert"],
      ]),
      pageBreak(),

      // ── Kap 5: Soul ──
      h1("5. Soul — Dameons Persönlichkeit"),
      p("Die Soul-Datei definiert, wer Dameon ist: Persönlichkeit, Sprache, Aufgaben und Grenzen. Sie wird als erstes in jeden System-Prompt injiziert."),
      spacer(),
      code("piclaw soul show        # aktuellen Soul anzeigen"),
      code("piclaw soul edit        # im Editor öffnen"),
      code("piclaw soul reset       # auf Standard zurücksetzen"),
      spacer(),
      p("Die Datei liegt unter /etc/piclaw/SOUL.md und kann auch direkt bearbeitet werden. Änderungen wirken beim nächsten Gespräch."),
      spacer(),
      infoBox("Was in den Soul gehört", [
        "Name und Charakter (direkt, freundlich, technisch präzise...)",
        "Sprache (antworte auf Deutsch / English)",
        "Primäre Aufgaben (Home Automation, Raspberry Pi, Marktplatz...)",
        "Verhaltensregeln (keine destruktiven Aktionen ohne Bestätigung)",
        "Kontext (lebt in Hamburg, hilft mit Home Lab, Haustiere...)",
      ]),
      pageBreak(),

      // ── Kap 6: Gedächtnis ──
      h1("6. Persistentes Gedächtnis"),
      h2("6.1 Wie das Gedächtnis funktioniert"),
      p("PiClaw merkt sich Fakten, Entscheidungen und Präferenzen über Gespräche hinweg. Das Gedächtnis besteht aus drei Teilen:"),
      spacer(),
      twoColTable([
        ["MEMORY.md", "Dauerhafte Fakten, Entscheidungen, Präferenzen"],
        ["Tages-Logs", "Automatische Protokolle (YYYY-MM-DD.md)"],
        ["QMD-Index", "Hybrid-Suchindex (BM25 + Vektor + Reranking)"],
      ]),
      spacer(),
      h2("6.2 Gedächtnis nutzen"),
      twoColTable([
        ["\"Merke dir das\"", "Schreibt in MEMORY.md"],
        ["\"Erinnerst du dich an...\"", "Sucht im QMD-Index"],
        ["memory_search Tool", "Direkte Suche im Chat"],
        ["memory_write Tool", "Explizit speichern"],
      ], 2800, 6560),
      spacer(),
      p("Der QMD-Index wird stündlich im Hintergrund aktualisiert (systemd-Timer), nicht nach jedem Chat — das würde den Pi für Minuten blockieren."),
      spacer(),
      h2("6.3 Wichtige Hinweise"),
      bullet("SOUL.md wird bewusst nicht im Gedächtnisindex erfasst"),
      bullet("Sessions werden als JSONL gespeichert und sind durchsuchbar"),
      bullet("Gedächtnis-Dateien liegen in: /etc/piclaw/memory/"),
      pageBreak(),

      // ── Kap 7: Sub-Agenten ──
      h1("7. Sub-Agenten"),
      p("Sub-Agenten sind spezialisierte KI-Helfer, die Dameon für bestimmte Aufgaben erstellt und verwaltet. Jeder Agent hat eine eigene Mission, eigene Tools und einen eigenen Zeitplan."),
      spacer(),
      h2("7.1 Sub-Agenten erstellen"),
      p("Einfach im Chat beschreiben:"),
      spacer(),
      code("\"Erstelle einen Agenten der täglich um 7 Uhr die CPU-Temperatur prüft\""),
      code("\"Überwache Kleinanzeigen für Raspberry Pi alle 30 Minuten\""),
      code("\"Starte einen Agenten der täglich mein GitHub Repository pullt\""),
      spacer(),
      h2("7.2 Eingebaute Sub-Agenten"),
      twoColTable([
        ["SearchAssistant", "Marktplatzsuche (Kleinanzeigen, eBay, eGun, willhaben, Troostwijk, Zoll-Auktion)"],
        ["InstallerAgent", "Software installieren mit Bestätigungs-Workflow"],
        ["WebCrawler", "Webseiten crawlen, einmalig oder wiederkehrend"],
        ["Watchdog", "Systemüberwachung, eigener Linux-User, tamper-proof"],
      ]),
      spacer(),
      h2("7.3 Verwaltung per CLI"),
      code("piclaw agent list              # alle Sub-Agenten"),
      code("piclaw agent start <name>      # Agent starten"),
      code("piclaw agent stop <name>       # Agent stoppen"),
      code("piclaw agent run <name>        # sofort ausführen"),
      code("piclaw agent remove <name>     # Agent löschen"),
      spacer(),
      h2("7.4 @-Prefix für direkten Aufruf"),
      p("Im Chat kann ein Sub-Agent direkt adressiert werden:"),
      code("@installer  installiere htop"),
      pageBreak(),

      // ── Kap 8: Marktplatzsuche ──
      h1("8. Marktplatzsuche"),
      p("PiClaw sucht auf Kleinanzeigen.de, eBay.de, eGun.de, willhaben.at, Troostwijk und Zoll-Auktion.de nach Inseraten. Neue Inserate werden als Alert über Telegram gesendet. Troostwijk und Zoll-Auktion unterstützen PLZ + Umkreis-Suche."),
      spacer(),
      h2("8.1 Suche starten"),
      code("\"Suche Raspberry Pi 5 auf Kleinanzeigen in 22081 Umkreis 30km\""),
      code("\"Finde einen gebrauchten Monitor unter 100€ auf eBay in Hamburg\""),
      code("\"Durchsuche Kleinanzeigen und eBay nach Lego Technic\""),
      code("\"Suche Land Rover auf der Zoll-Auktion\""),
      code("\"Überwache Troostwijk Auktionen im Umkreis von 100km um 21224\""),
      spacer(),
      h2("8.2 Wiederholende Suche"),
      code("\"Überwache Kleinanzeigen für Raspberry Pi 5 und melde neue Inserate\""),
      code("\"Suche alle 30 Minuten nach gebrauchten iPhones unter 200€\""),
      spacer(),
      infoBox("Wie die Suche funktioniert", [
        "1. PLZ wird automatisch aus der Anfrage extrahiert",
        "2. Suchbegriff wird von Rauschwörtern bereinigt",
        "3. Direkte Suche wenn PLZ + Begriff erkannt (schneller Pfad)",
        "4. Neue Inserate werden markiert und gemeldet",
        "5. Gesehene Inserate werden nicht erneut gemeldet",
      ]),
      spacer(),
      p("Die Datei /etc/piclaw/marketplace_seen.json enthält alle bereits gemeldeten Inserate. Löschen zum Zurücksetzen."),
      pageBreak(),

      // ── Kap 9: Messaging ──
      h1("9. Messaging & Benachrichtigungen"),
      h2("9.1 Telegram (empfohlen)"),
      p("Telegram ist der primäre Kommunikationskanal. Nachrichten senden und Befehle empfangen."),
      spacer(),
      code("piclaw setup   # Schritt 'Telegram' im Wizard"),
      code("# oder direkt:"),
      code("piclaw messaging setup telegram"),
      spacer(),
      twoColTable([
        ["Bot erstellen", "@BotFather auf Telegram → /newbot"],
        ["Chat-ID finden", "@userinfobot auf Telegram anschreiben"],
        ["Konfiguration", "/etc/piclaw/config.toml → [telegram]"],
      ]),
      spacer(),
      h2("9.2 Discord"),
      code("piclaw messaging setup discord"),
      spacer(),
      h2("9.3 Alle Adapter testen"),
      code("piclaw messaging test    # sendet Testnachricht an alle konfigurierten Kanäle"),
      code("piclaw messaging status  # zeigt aktive Adapter"),
      pageBreak(),

      // ── Kap 10: Web-Dashboard ──
      h1("10. Web-Dashboard"),
      p("Das Web-Dashboard ist unter http://piclaw.local:7842 erreichbar. Es zeigt Echtzeit-Metriken, erlaubt Chat und verwaltet Sub-Agenten."),
      spacer(),
      twoColTable([
        ["Dashboard", "CPU, RAM, Temperatur, Uptime, Services"],
        ["Memory", "Gedächtnis durchsuchen (BM25 + Vektor)"],
        ["Agenten", "Sub-Agenten erstellen, starten, stoppen"],
        ["Soul", "Persönlichkeit direkt im Browser bearbeiten"],
        ["Hardware", "I2C-Scan, Sensoren, thermisches Routing"],
        ["Metriken", "Zeitreihen-Charts für CPU, RAM, Temperatur"],
        ["Kamera", "Fotos aufnehmen, KI-Bildanalyse"],
        ["Chat", "Direkter KI-Chat im Browser"],
      ]),
      spacer(),
      p("Der API-Token wird automatisch generiert und ist in der HTML-Seite eingebettet. Zum Anzeigen: piclaw config token"),
      pageBreak(),

      // ── Kap 11: Updates ──
      h1("11. Updates"),
      p("PiClaw aktualisiert sich über git pull — kein root-Passwort nötig, da die Berechtigungen beim Installer gesetzt werden."),
      spacer(),
      code("piclaw update check   # zeigt ausstehende Commits"),
      code("piclaw update         # führt Update aus + Neustart"),
      code("piclaw update system  # apt upgrade (System-Pakete)"),
      spacer(),
      infoBox("Update-Ablauf", [
        "1. git pull origin main  — holt neuen Code von GitHub",
        "2. pip install -e .      — nur wenn pyproject.toml geändert",
        "3. sudo systemctl restart piclaw-api piclaw-agent",
        "→ Dauer: ca. 10–30 Sekunden, Config bleibt erhalten",
      ]),
      pageBreak(),

      // ── Kap 12: Watchdog ──
      h1("12. Watchdog & Sicherheit"),
      p("Der Watchdog läuft als eigenständiger Linux-User (piclaw-watchdog) und kann nicht vom Hauptagenten beeinflusst werden."),
      spacer(),
      h2("12.1 Was der Watchdog überwacht"),
      bullet("Disk > 85% → Warning, > 95% → Critical"),
      bullet("CPU-Temperatur > 75°C → Warning, > 80°C → Critical"),
      bullet("RAM > 90% → Warning"),
      bullet("Services down → Warning (3× → Critical)"),
      bullet("Datei-Integrität: config.toml, systemd-Services, sshd_config"),
      bullet("Heartbeat des Hauptagenten (alle 30s)"),
      bullet("Installer-Hänger (Lock-Datei älter als 15 Min)"),
      spacer(),
      h2("12.2 Alerts lesen"),
      code("piclaw  →  watchdog_alerts    # im Chat"),
      code("piclaw  →  watchdog_status    # Übersicht"),
      spacer(),
      h2("12.3 Watchdog-Logs"),
      p("Watchdog-Logs sind append-only (SQLite-Trigger) und können nicht nachträglich geändert werden."),
      code("sudo journalctl -u piclaw-watchdog -f"),
      pageBreak(),

      // ── Kap 13: Fehlerbehebung ──
      h1("13. Fehlerbehebung"),
      twoColTable([
        ["piclaw.local nicht gefunden", "Warte 90s nach Boot. IP im Router nachschauen."],
        ["'No LLM backends configured'", "piclaw setup → LLM-Key eintragen oder piclaw model download"],
        ["Doctor zeigt Standardwerte", "CONFIG_DIR-Bug: /etc/piclaw/config.toml fehlt?"],
        ["API startet und stoppt sofort", "api.log prüfen: sudo journalctl -u piclaw-api -n 50"],
        ["Watchdog: Permission denied", "chmod 1777 /etc/piclaw/ipc/ && sudo usermod -aG piclaw piclaw-watchdog"],
        ["QMD CPU 100%", "Prüfen ob QMD pro Turn läuft (sollte nur cron sein)"],
        ["Marketplace: keine Ergebnisse", "PLZ korrekt? /etc/piclaw/marketplace_seen.json löschen zum Zurücksetzen"],
        ["piclaw update schlägt fehl", "/etc/sudoers.d/piclaw vorhanden? sudo bash install.sh erneut ausführen"],
      ]),
      spacer(),
      h2("13.1 Systemcheck"),
      code("piclaw doctor                          # vollständiger Check"),
      code("sudo systemctl status piclaw-api piclaw-agent piclaw-watchdog piclaw-crawler"),
      code("sudo tail -f /var/log/piclaw/api.log   # API + Agent-Logs"),
      code("sudo tail -f /var/log/piclaw/watchdog/watchdog.log"),
      pageBreak(),

      // ── Kap 14: Konfiguration ──
      h1("14. Konfigurationsdatei"),
      p("Die Hauptkonfiguration liegt unter /etc/piclaw/config.toml. Wichtigste Sektionen:"),
      spacer(),
      code("[agent]"),
      code("agent_name = \"Dameon\""),
      spacer(),
      code("[llm]"),
      code("backend  = \"openai\""),
      code("model    = \"moonshotai/kimi-k2-instruct-0905\""),
      code("api_key  = \"nvapi-...\""),
      code("base_url = \"https://integrate.api.nvidia.com/v1\""),
      spacer(),
      code("[telegram]"),
      code("token   = \"123456:ABC-...\""),
      code("chat_id = \"987654321\""),
      spacer(),
      p("Einzelne Werte ändern:"),
      code("piclaw config set llm.api_key nvapi-DEIN-KEY"),
      code("piclaw config set agent_name Jarvis"),
      pageBreak(),

      // ── Kap 15: Roadmap ──
      h1("15. Roadmap"),
      twoColTable([
        ["v0.15.0 (jetzt)", "Multi-LLM-Router, Marketplace-Fix, sauberer Installer, git-Update"],
        ["v0.16 — AgentMail", "E-Mail-Postfach für Dameon via agentmail.to"],
        ["v0.17 — LLM Autonomie", "Dameon findet selbständig neue kostenlose LLM-Backends. Troostwijk Umkreissuche (PLZ + Radius). Zoll-Auktion.de als Plattform. 4 Security-PRs gemergt."],
        ["v0.17 — Emergency", "Notabschaltung via smarter Steckdose (Modem-Schnitt)"],
        ["v0.18 — Sicherheit", "fail2ban-Integration, IP-Blocking, Sicherheits-Reports"],
        ["v0.19 — Browser", "Tandem Browser: autonomes Surfen und Formular-Ausfüllen"],
        ["v0.22 — Effizienz", "Einzelne Gemma-Instanz (spart ~2 GB RAM)"],
      ]),
      spacer(),
      infoBox("Projekt-Repository", [
        "https://github.com/RainbowLabsInc/PiClawOS",
        "Issues, Feature-Requests und Pull Requests willkommen.",
      ], C.mid),

      // ── Ende ──
      spacer(), spacer(),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "PiClaw OS v0.15.0 — März 2026", font: "Arial", size: 18, color: C.gray, italics: true })],
      }),
    ]
  }]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync('/home/claude/PiClaw-OS-Handbuch-v0.15.docx', buffer);
  console.log('✅ Handbuch-DE erstellt');
});
