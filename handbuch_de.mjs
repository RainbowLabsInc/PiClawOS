import { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
         HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType,
         LevelFormat, PageNumberElement, Footer, PageBreak } from 'docx';
import fs from 'fs';

const BLUE   = "1F4E79";
const LBLUE  = "D6E4F0";
const DGRAY  = "404040";
const LGRAY  = "F5F5F5";
const GREEN  = "1D6B34";
const LGREEN = "E8F5E9";
const ORANGE = "B45309";
const LORANGE= "FEF3C7";

const border  = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const noBorder  = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
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
function pNote(text) {
  return new Paragraph({
    spacing: { before: 60, after: 60 },
    shading: { fill: LORANGE, type: ShadingType.CLEAR },
    indent: { left: 200, right: 200 },
    children: [new TextRun({ text: "💡 " + text, size: 20, font: "Arial", color: ORANGE })]
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
function threeColTable(rows, w1=2500, w2=3000, w3=3860) {
  return new Table({
    width: { size: w1+w2+w3, type: WidthType.DXA },
    columnWidths: [w1, w2, w3],
    rows: rows.map(([a,b,c]) => new TableRow({
      children: [
        new TableCell({ borders, width:{size:w1,type:WidthType.DXA},
          shading:{fill:LGRAY,type:ShadingType.CLEAR},
          margins:{top:80,bottom:80,left:120,right:120},
          children:[new Paragraph({children:[new TextRun({text:a,bold:true,size:20,font:"Arial"})]})]
        }),
        new TableCell({ borders, width:{size:w2,type:WidthType.DXA},
          margins:{top:80,bottom:80,left:120,right:120},
          children:[new Paragraph({children:[new TextRun({text:b,size:20,font:"Arial"})]})]
        }),
        new TableCell({ borders, width:{size:w3,type:WidthType.DXA},
          margins:{top:80,bottom:80,left:120,right:120},
          children:[new Paragraph({children:[new TextRun({text:c,size:20,font:"Arial"})]})]
        }),
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
            new TextRun({ text: "PiClaw OS v0.15.5 \u2013 Handbuch  |  Seite ", size: 18, color: "888888", font: "Arial" }),
            new PageNumberElement()
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
        children: [new TextRun({ text: "Handbuch v0.15.5", size: 36, font: "Arial", color: DGRAY })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 0, after: 800 },
        children: [new TextRun({ text: "KI-Betriebssystem f\u00FCr Raspberry Pi 5", size: 26, font: "Arial", color: DGRAY })]
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 0, after: 200 },
        children: [new TextRun({ text: "April 2026", size: 22, font: "Arial", color: "888888" })]
      }),
      pageBreak(),

      // ── 1. Überblick ───────────────────────────────────────────
      h1("1. \u00DCberblick"),
      p("PiClaw OS verwandelt einen Raspberry Pi in einen autonomen KI-Assistenten, der rund um die Uhr l\u00E4uft. Der Agent Dameon verarbeitet Nachrichten \u00FCber Telegram, WhatsApp und weitere Kan\u00E4le, steuert Smart-Home-Ger\u00E4te via Home Assistant, durchsucht Marktpl\u00E4tze und Auktionsplattformen, \u00FCberwacht das Netzwerk und meldet sich proaktiv bei wichtigen Ereignissen."),
      p(""),
      h2("1.1 Systemvoraussetzungen"),
      twoColTable([
        ["Hardware", "Raspberry Pi 5 (empfohlen) oder Pi 4"],
        ["Betriebssystem", "Raspberry Pi OS Lite 64-bit (Bookworm oder Trixie)"],
        ["SD-Karte", "\u2265 16 GB"],
        ["RAM", "4 GB (8 GB empfohlen f\u00FCr lokale Modelle)"],
        ["Python", "3.11 oder h\u00F6her (getestet: 3.13)"],
        ["Internetverbindung", "Ben\u00F6tigt f\u00FCr Installation und Cloud-LLM"]
      ]),
      p(""),
      h2("1.2 Hauptfunktionen"),
      twoColTable([
        ["Multi-LLM-Routing", "Groq (Llama 3.3, Kimi K2), NVIDIA NIM, Anthropic Claude, OpenAI, Ollama, Qwen3 lokal"],
        ["Messaging Hub", "Telegram, WhatsApp, Threema, MQTT"],
        ["Home Assistant", "REST + WebSocket, 11 Tools, Echtzeit-Push-Events"],
        ["Marktplatz-Crawler", "Kleinanzeigen.de, eBay.de, eGun.de, Willhaben.at, Troostwijk-Auktionen \u2013 nur neue Inserate"],
        ["Auktions-Monitor", "Troostwijk: ganze Auktions-Events nach Land/Stadt \u00FCberwachen (tokenlos)"],
        ["Netzwerk-Monitor", "LAN-Scan via nmap, neue Ger\u00E4te erkennen, Telegram-Alert"],
        ["Proaktiver Agent", "Morgenbriefing, Abendcheck, Schwellwert-Monitoring"],
        ["Hybrid Memory", "BM25 + Vektorsuche (QMD), persistente Fakten"],
        ["Watchdog", "Dienst- und Hardware-\u00DCberwachung"],
        ["Web-Dashboard", "8 Tabs: Dashboard \u00B7 Memory \u00B7 Agenten \u00B7 Soul \u00B7 Hardware \u00B7 Metriken \u00B7 Kamera \u00B7 Chat"],
        ["Installer Sub-Agent", "Dameon kann Software autonom installieren (mit Nutzer-Best\u00E4tigung)"],
        ["Tandem Browser", "Autonomes Browser-Steuern, Formularausf\u00FCllen, Webseiten lesen"]
      ]),

      pageBreak(),

      // ── 2. Installation ───────────────────────────────────────
      h1("2. Installation"),
      h2("2.1 Methode A \u2013 GitHub Clone (empfohlen)"),
      p("Diese Methode ben\u00F6tigt eine aktive SSH-Verbindung zum Pi und Internetzugang."),
      pCode("git clone https://github.com/RainbowLabsInc/PiClawOS.git"),
      pCode("cd PiClawOS/piclaw-os"),
      pCode("sudo bash install.sh"),
      p(""),
      h2("2.2 Methode B \u2013 SD-Karte (offline)"),
      bullet("piclaw-sdcard.zip entpacken"),
      bullet("Den Ordner piclaw/ auf die bootfs-Partition der SD-Karte kopieren"),
      bullet("piclaw/piclaw.conf \u00F6ffnen und optionale Werte eintragen"),
      bullet("SD-Karte einlegen, Pi starten, 60 Sekunden warten"),
      bullet("SSH verbinden:"),
      pCode("ssh -t pi@piclaw.local"),
      bullet("Installer starten:"),
      pCode("sudo bash /boot/firmware/piclaw/install.sh   # Pi 5"),
      pCode("sudo bash /boot/piclaw/install.sh            # Pi 4"),
      p(""),
      h2("2.3 Ersteinrichtung"),
      p("Nach der Installation den Konfigurations-Wizard starten:"),
      pCode("piclaw setup"),
      p("Der Wizard f\u00FChrt durch: Agent-Name, LLM-Backend, Telegram, Home Assistant, Soul."),
      p(""),
      h2("2.4 Update"),
      pCode("piclaw update    # Neuesten Code ziehen + Dienste neu starten"),
      pCode("piclaw doctor    # Systemstatus pr\u00FCfen"),

      pageBreak(),

      // ── 3. Kostenlose APIs ────────────────────────────────────
      h1("3. Kostenlose APIs \u2013 Wo bekomme ich sie?"),
      p("PiClaw OS ist so konzipiert, dass es vollst\u00E4ndig mit kostenlosen API-Tiers betreibbar ist. Folgende Anbieter bieten dauerhaft kostenlose Kontingente:"),
      p(""),
      h2("3.1 Groq \u2013 Prim\u00E4res LLM-Backend (empfohlen)"),
      twoColTable([
        ["URL", "console.groq.com"],
        ["Registrierung", "GitHub / Google OAuth, keine Kreditkarte n\u00F6tig"],
        ["Free Tier", "Dauerhaft kostenlos, begrenzte Requests/Minute (RPM) und Tokens/Minute (TPM)"],
        ["Modelle (kostenlos)", "llama-3.3-70b-versatile, kimi-k2-instruct, gemma2-9b-it und weitere"],
        ["Empfehlung PiClaw", "Prio 10: llama-3.3-70b-versatile / Prio 9: kimi-k2-instruct"],
      ]),
      pCode("# API-Key holen: console.groq.com \u2192 API Keys \u2192 Create API Key"),
      pCode("# Format: gsk_..."),
      pCode("piclaw llm add --name groq-actions --provider openai \\"),
      pCode("  --model llama-3.3-70b-versatile \\"),
      pCode("  --base-url https://api.groq.com/openai/v1 \\"),
      pCode("  --api-key gsk_... --priority 10"),
      pNote("Groq ist Stand April 2026 das beste kostenlose Backend f\u00FCr Geschwindigkeit und Qualit\u00E4t."),
      p(""),
      h2("3.2 NVIDIA NIM \u2013 Alternatives Cloud-Backend"),
      twoColTable([
        ["URL", "build.nvidia.com"],
        ["Registrierung", "E-Mail, keine Kreditkarte f\u00FCr Free Tier"],
        ["Free Tier", "1.000 API-Calls/Monat kostenlos (danach Pay-per-Token)"],
        ["Modelle", "llama-4-maverick, llama-3.3-70b, mistral-nemo und viele weitere"],
        ["API-Key Format", "nvapi-..."],
        ["Base URL", "https://integrate.api.nvidia.com/v1"],
      ]),
      pCode("piclaw llm add --name nvidia-nim --provider openai \\"),
      pCode("  --model meta/llama-4-maverick-17b-128e-instruct \\"),
      pCode("  --base-url https://integrate.api.nvidia.com/v1 \\"),
      pCode("  --api-key nvapi-... --priority 6"),
      p(""),
      h2("3.3 OpenRouter \u2013 Aggregator f\u00FCr viele Modelle"),
      twoColTable([
        ["URL", "openrouter.ai"],
        ["Registrierung", "GitHub / Google OAuth"],
        ["Free Tier", "Viele Modelle gratis (Label: \u201Cfree\u201D), z.B. DeepSeek R1, Gemma 3"],
        ["Besonderheit", "Ein Key, viele Anbieter \u2013 automatischer Fallback"],
        ["API-Key Format", "sk-or-..."],
        ["Base URL", "https://openrouter.ai/api/v1"],
      ]),
      pCode("piclaw llm add --name openrouter-free --provider openai \\"),
      pCode("  --model google/gemma-3-27b-it:free \\"),
      pCode("  --base-url https://openrouter.ai/api/v1 \\"),
      pCode("  --api-key sk-or-... --priority 5"),
      p(""),
      h2("3.4 Anthropic Claude \u2013 Premium-Alternative"),
      twoColTable([
        ["URL", "console.anthropic.com"],
        ["Registrierung", "E-Mail + Telefonnummer, kein kostenloses Tier (Pay-per-Token)"],
        ["Empfehlung", "Claude Haiku 3.5 f\u00FCr g\u00FCnstige, qualitativ hochwertige Antworten"],
        ["API-Key Format", "sk-ant-..."],
      ]),
      p(""),
      h2("3.5 Lokale Modelle \u2013 Kein API-Key n\u00F6tig"),
      twoColTable([
        ["Qwen3-1.7B Q4_K_M", "Standard-Offline-Fallback, ~1.1 GB, f\u00FCr Pi 5 optimiert"],
        ["Gemma 2B Q4", "Alternativ, ~1.6 GB, gut f\u00FCr einfache Aufgaben"],
        ["Phi-3 Mini Q4", "St\u00E4rkeres Modell, ~2.2 GB, langsamer auf Pi 4"],
      ]),
      pCode("piclaw model download               # Qwen3-1.7B (Standard)"),
      pCode("piclaw model download gemma2b-q4    # Alternative"),
      pNote("Lokale Modelle laufen komplett offline \u2013 ideal als letzter Fallback oder bei API-Ausfall."),
      p(""),
      h2("3.6 Telegram Bot \u2013 Kostenlos"),
      twoColTable([
        ["URL", "t.me/BotFather"],
        ["Schritte", "/newbot \u2192 Name vergeben \u2192 Token kopieren"],
        ["Format", "1234567890:ABCdef..."],
        ["Chat-ID", "@userinfobot in Telegram anschreiben"],
      ]),
      pCode("# In piclaw setup Telegram-Schritt ausf\u00FChren:"),
      pCode("piclaw setup  \u2192  Schritt 'Telegram'"),
      p(""),
      h2("3.7 \u00DCbersicht: Empfohlene Konfiguration (alle kostenlos)"),
      threeColTable([
        ["Priorit\u00E4t", "Backend", "Verwendung"],
        ["10 (Haupt)", "Groq \u2013 llama-3.3-70b-versatile", "Normale Anfragen, schnell"],
        ["9", "Groq \u2013 kimi-k2-instruct", "Fallback, Tool-Calling"],
        ["8", "Groq \u2013 gpt-oss-120b (optional)", "Erweiterte Aufgaben"],
        ["6", "NVIDIA NIM \u2013 llama-4-maverick", "Alternativer Cloud-Fallback"],
        ["5", "OpenRouter \u2013 free Modell", "Weiterer Fallback"],
        ["lokal", "Qwen3-1.7B Q4_K_M", "Offline, kein Internet n\u00F6tig"],
      ], 2000, 3500, 3860),

      pageBreak(),

      // ── 4. LLM-Konfiguration ──────────────────────────────────
      h1("4. LLM-Konfiguration"),
      h2("4.1 Unterst\u00FCtzte Anbieter"),
      twoColTable([
        ["Groq", "gsk_... \u2013 Empfohlen. Llama 3.3, Kimi K2 als Haupt-Backend."],
        ["NVIDIA NIM", "nvapi-... \u2013 Zweites Backend, llama-4-maverick."],
        ["OpenRouter", "sk-or-... \u2013 Aggregator, viele kostenlose Modelle."],
        ["Anthropic Claude", "sk-ant-... \u2013 Hochwertige Cloud-Alternative."],
        ["OpenAI GPT", "sk-... \u2013 Alternative Cloud."],
        ["Ollama (lokal)", "Kein Key \u2013 Eigener Server auf dem Pi oder im Netzwerk."],
        ["Qwen3 (offline)", "Kein Key \u2013 Lokal auf dem Pi, kein Internet n\u00F6tig."],
        ["Gemma 2B (offline)", "Kein Key \u2013 Alternativmodell, sehr leicht."],
      ]),
      p(""),
      h2("4.2 Fallback-Reihenfolge"),
      p("Wenn ein Backend nicht erreichbar ist, wechselt Dameon automatisch zum n\u00E4chsten in der Priorit\u00E4tsliste. Das lokale Modell ist immer der letzte Fallback."),
      p(""),
      h2("4.3 Registry verwalten"),
      pCode("piclaw llm list                    # Alle registrierten Backends anzeigen"),
      pCode("piclaw llm add --name mein-backend \\"),
      pCode("  --provider openai \\"),
      pCode("  --model llama-3.3-70b-versatile \\"),
      pCode("  --api-key gsk_... \\"),
      pCode("  --base-url https://api.groq.com/openai/v1 \\"),
      pCode("  --priority 10 --tags coding,reasoning"),
      pCode("piclaw llm remove <n>           # Backend entfernen"),
      pCode("piclaw llm update <n> --model <neues-modell>"),
      p("Im Chat kann ein Backend direkt angesprochen werden:"),
      pCode("[you] @groq-actions Schreib mir ein Python Hello World"),

      pageBreak(),

      // ── 5. Marktplatz-Monitor ─────────────────────────────────
      h1("5. Marktplatz-Monitor"),
      p("Der Marktplatz-Monitor durchsucht regelm\u00E4\u00DFig verschiedene Plattformen nach neuen Inseraten oder Auktionen und meldet nur neue Ergebnisse per Telegram. Er l\u00E4uft vollst\u00E4ndig tokenlos \u2013 kein LLM-Aufruf, kein API-Verbrauch."),
      p(""),
      h2("5.1 Unterst\u00FCtzte Plattformen"),
      twoColTable([
        ["Kleinanzeigen.de \ud83d\udccc", "Gebrauchtwaren, PLZ + Umkreis-Filter, Preis-Filter"],
        ["eBay.de \ud83d\uded2", "Sofort-Kaufen + Auktionen, PLZ-Filter"],
        ["eGun.de \ud83c\udfaf", "Waffen, Zubeh\u00F6r, Jagd, Angeln \u2013 Spezialmarktplatz"],
        ["Willhaben.at \ud83c\udde6\ud83c\uddf9", "\u00D6sterreichs gr\u00F6\u00DFter Marktplatz, Bundesland-Filter"],
        ["Troostwijk \ud83d\udd28", "Industrie-Auktionsplattform: Suche nach Artikeln/Losen"],
        ["Troostwijk Auktionen \ud83c\udfd6\ufe0f", "NEU: ganze Auktions-Events nach Land oder Stadt \u00FCberwachen"],
        ["Websuche \ud83c\udf10", "DuckDuckGo-Fallback f\u00FCr alle anderen Quellen"],
      ]),
      p(""),
      h2("5.2 Monitor erstellen (via Dameon-Chat)"),
      p("Einfach nat\u00FCrlichsprachlich in den Chat schreiben:"),
      pCode("[you] \u00DCberwache Kleinanzeigen auf Gartentisch in 21224, 20km"),
      pCode("[you] Sag mir wenn ein Sauer 505 auf eGun auftaucht"),
      pCode("[you] \u00DCberwache Troostwijk auf neue Auktionen in Deutschland"),
      pCode("[you] \u00DCberwache Troostwijk auf neue Auktionen in Hamburg"),
      pCode("[you] \u00DCberwache Troostwijk auf neue Auktionen in den Niederlanden"),
      p(""),
      h2("5.3 Troostwijk Auktions-Monitor (neu in v0.15.5)"),
      p("Anders als die herk\u00F6mmliche Troostwijk-Suche (die einzelne Lose findet) \u00FCberwacht dieser Monitor ganze Auktions-Events."),
      twoColTable([
        ["Artikel-Suche", "\"Suche nach Sauer 505 auf Troostwijk\" \u2192 findet einzelne Lose"],
        ["Auktions-Monitor", "\"Neue Auktionen in Deutschland\" \u2192 findet neue Auktions-Veranstaltungen"],
      ]),
      p(""),
      pBold("Unterst\u00FCtzte L\u00E4nder:"),
      p("Deutschland, Niederlande, Belgien, Frankreich, \u00D6sterreich, Italien, Spanien, Schweden, D\u00E4nemark, Polen, Tschechien, Ungarn, Kroatien, Portugal, Finnland, Estland, Griechenland, Rum\u00E4nien und mehr."),
      p(""),
      pBold("Stadtfilter:"),
      p("Eine Stadtangabe filtert Auktionsnamen nach dem Stadtbegriff. Da Troostwijk keinen API-seitigen Stadtfilter bietet, erfolgt das Matching als Textsuchein im Auktionsnamen (z.B. \u201ED | Maschinen Hamburg\u201C)."),
      pNote("Der Auktions-Monitor l\u00E4uft vollst\u00E4ndig tokenlos und verbraucht keine LLM-API-Calls."),
      p(""),
      h2("5.4 Manueller Testlauf"),
      pCode("[you] Suche auf Troostwijk nach Gabelstapler in Deutschland"),
      pCode("[you] Suche auf Kleinanzeigen nach Sonnenschirm in 21224, 20km"),
      p(""),
      h2("5.5 Monitor verwalten"),
      pCode("piclaw agent list              # Alle laufenden Monitore anzeigen"),
      pCode("[you] Stoppe den Monitor f\u00FCr Gartentisch"),
      pCode("[you] Zeige alle aktiven Marktplatz-Monitore"),

      pageBreak(),

      // ── 6. Messaging ──────────────────────────────────────────
      h1("6. Messaging"),
      h2("6.1 Telegram"),
      p("Telegram ist der prim\u00E4re Kommunikationskanal. Alle Nachrichten werden an Dameon weitergeleitet."),
      bullet("Bot erstellen: @BotFather in Telegram \u2192 /newbot"),
      bullet("Token und Chat-ID in piclaw setup eintragen"),
      bullet("Watchdog-Bot: separater Bot f\u00FCr Hardware-Alerts (eigener Token empfohlen)"),
      p(""),
      h2("6.2 Weitere Kan\u00E4le"),
      twoColTable([
        ["WhatsApp", "Access Token (Meta Cloud API) + Verify Token"],
        ["Threema", "Threema-Gateway-ID und API-Key"],
        ["MQTT", "Broker-URL, Port, Topic-Pr\u00E4fix, optional TLS"]
      ]),

      pageBreak(),

      // ── 7. Netzwerk-Monitor ───────────────────────────────────
      h1("7. Netzwerk-Monitor"),
      p("Der Netzwerk-Monitor scannt das lokale Netzwerk und meldet neue oder unbekannte Ger\u00E4te per Telegram. Er l\u00E4uft alle 5 Minuten und ist gesch\u00FCtzt \u2013 kann nicht gel\u00F6scht werden."),
      h2("7.1 Tools"),
      twoColTable([
        ["network_scan", "Alle Ger\u00E4te im LAN per nmap scannen"],
        ["port_scan", "Offene Ports eines bestimmten Ger\u00E4ts pr\u00FCfen"],
        ["check_new_devices", "Nur neue (bisher unbekannte) Ger\u00E4te melden"]
      ]),
      h2("7.2 Voraussetzung"),
      pCode("sudo apt install nmap"),
      h2("7.3 Beispiel im Chat"),
      pCode("[you] Scan mein Heimnetzwerk"),
      pCode("[Dameon] Gefunden: 12 Ger\u00E4te. 1 neues Ger\u00E4t: 192.168.178.55 (unbekannt)"),

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
        ["emergency_network_off", "Netzwerk-Notabschaltung"]
      ]),

      pageBreak(),

      // ── 9. Web-Dashboard ──────────────────────────────────────
      h1("9. Web-Dashboard"),
      p("Das Web-Dashboard ist \u00FCber Port 7842 erreichbar:"),
      pCode("http://piclaw.local:7842"),
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
      pCode("piclaw config token   # Bearer-Token f\u00FCr REST-API anzeigen"),

      pageBreak(),

      // ── 10. CLI-Referenz ───────────────────────────────────────
      h1("10. CLI-Referenz"),
      twoColTable([
        ["piclaw", "Chat mit dem Agenten starten"],
        ["piclaw setup", "Konfigurations-Wizard"],
        ["piclaw doctor", "Systemstatus pr\u00FCfen"],
        ["piclaw update", "Code aktualisieren + Dienste neu starten"],
        ["piclaw start / stop", "Alle Services starten / stoppen"],
        ["piclaw model download [id]", "Lokales Modell herunterladen"],
        ["piclaw model list", "Alle verf\u00FCgbaren Modelle anzeigen"],
        ["piclaw llm list", "Registrierte LLM-Backends anzeigen"],
        ["piclaw llm add --name ...", "Neues Backend registrieren"],
        ["piclaw llm remove <n>", "Backend entfernen"],
        ["piclaw llm update <n> ...", "Backend-Einstellungen \u00E4ndern"],
        ["piclaw agent list", "Sub-Agenten anzeigen"],
        ["piclaw agent start <id>", "Sub-Agent starten"],
        ["piclaw soul show", "Soul-Datei anzeigen"],
        ["piclaw soul edit", "Soul-Datei bearbeiten"],
        ["piclaw routine list", "Routinen anzeigen"],
        ["piclaw briefing morning", "Morgenbriefing sofort ausgeben"],
        ["piclaw backup", "Backup erstellen"],
        ["piclaw metrics", "Aktuelle Metriken anzeigen"],
        ["piclaw camera snapshot", "Foto aufnehmen"]
      ]),

      pageBreak(),

      // ── 11. Sub-Agenten ───────────────────────────────────────
      h1("11. Sub-Agenten"),
      p("Sub-Agenten sind eigenst\u00E4ndige, geplante Aufgaben die Dameon im Hintergrund ausf\u00FChrt. Marktplatz-Monitore laufen vollst\u00E4ndig tokenlos \u2013 kein LLM, keine API-Kosten."),
      h2("11.1 Aktuelle Standard-Agenten"),
      twoColTable([
        ["Monitor_Netzwerk", "LAN-Scan alle 5 Min. \u2013 GESCH\u00DCTZT, kann nicht gel\u00F6scht werden"],
        ["Monitor_Gartentisch", "Kleinanzeigen: Gartentisch, PLZ 21224, 20 km \u2013 st\u00FCndlich"],
        ["Monitor_Sonnenschirm", "Kleinanzeigen: Sonnenschirm, PLZ 21224, 20 km \u2013 st\u00FCndlich"],
        ["Monitor_Sauer505", "eGun: Sauer 505 \u2013 st\u00FCndlich"],
        ["Monitor_TW_Deutschland", "Troostwijk: Neue Auktions-Events in Deutschland \u2013 st\u00FCndlich"],
        ["CronJob_0715", "T\u00E4glicher Bericht um 07:15 Uhr"],
      ]),
      h2("11.2 Neuen Monitor erstellen"),
      p("Im Chat mit Dameon:"),
      pCode("[you] \u00DCberwache Troostwijk auf neue Auktionen in Belgien"),
      pCode("[you] \u00DCberwache Kleinanzeigen auf Raspberry Pi in Berlin"),
      pCode("[you] Sag mir wenn ein Sauer 303 auf eGun auftaucht"),
      h2("11.3 mission-JSON Format"),
      pCode("# Standard Marktplatz-Monitor:"),
      pCode("{\"query\":\"Gartentisch\",\"platforms\":[\"kleinanzeigen\"],"),
      pCode(" \"location\":\"21224\",\"radius_km\":20,\"max_price\":null}"),
      pCode(""),
      pCode("# Troostwijk Auktions-Monitor:"),
      pCode("{\"query\":\"\",\"platforms\":[\"troostwijk_auctions\"],"),
      pCode(" \"location\":null,\"country\":\"de\",\"max_results\":24}"),

      pageBreak(),

      // ── 12. Systemdienste ─────────────────────────────────────
      h1("12. Systemdienste"),
      twoColTable([
        ["piclaw-api", "REST API + Web-Dashboard (Port 7842)"],
        ["piclaw-agent", "Haupt-Agent Daemon"],
        ["piclaw-watchdog", "Hardware- und Dienst-\u00DCberwachung (isolierter User)"],
        ["piclaw-tandem (optional)", "Tandem Browser Service"]
      ]),
      p(""),
      h2("Dienste neu starten"),
      pCode("sudo systemctl restart piclaw-api piclaw-agent"),
      p(""),
      h2("Logs anzeigen"),
      pCode("journalctl -u piclaw-api -f"),
      pCode("journalctl -u piclaw-agent -f"),

      pageBreak(),

      // ── 13. Soul-System ───────────────────────────────────────
      h1("13. Soul-System"),
      p("Die SOUL.md Datei definiert die Pers\u00F6nlichkeit, Ziele und Verhaltensregeln von Dameon. Ihr Inhalt wird bei jedem Gespr\u00E4ch als erster Block in den System-Prompt eingef\u00FCgt."),
      h2("Pfad"),
      pCode("/etc/piclaw/SOUL.md"),
      h2("Bearbeiten"),
      pCode("piclaw soul edit          # Im Editor bearbeiten"),
      pCode("piclaw soul show          # Aktuellen Inhalt anzeigen"),
      pCode("piclaw soul reset         # Standard-Soul wiederherstellen"),
      p("Oder direkt im Web-Dashboard unter dem Tab 'Soul'."),

      pageBreak(),

      // ── 14. Fehlerbehebung ────────────────────────────────────
      h1("14. Fehlerbehebung"),
      twoColTable([
        ["piclaw doctor zeigt Fehler", "API-Key in config.toml pr\u00FCfen; piclaw setup ausf\u00FChren"],
        ["API antwortet nicht", "sudo systemctl restart piclaw-api; Logs pr\u00FCfen"],
        ["Dameon antwortet nicht", "piclaw doctor; LLM health pr\u00FCfen; API-Key g\u00FCltig?"],
        ["piclaw update h\u00E4ngt", "github_token in /etc/piclaw/config.toml eintragen"],
        ["Kein lokales Modell", "piclaw model download ausf\u00FChren (~1.1 GB)"],
        ["hohe CPU-Temperatur", "Thermisches Routing aktiv: Dameon wechselt zu Cloud-API"],
        ["Sub-Agent startet nicht", "piclaw agent list; subagents.json pr\u00FCfen"],
        ["Troostwijk liefert 404", "BuildId veraltet, wird automatisch erneuert beim n\u00E4chsten Lauf"],
        ["Installer schl\u00E4gt fehl", "Quelle in Whitelist? Internetverbindung? Logs pr\u00FCfen"]
      ]),

      pageBreak(),

      // ── 15. Versionsverlauf ───────────────────────────────────
      h1("15. Versionsverlauf"),
      twoColTable([
        ["v0.15.5 (April 2026)", "Troostwijk Auktions-Monitor (Stadt/Land), country-Parameter, Groq-Backends, Qwen3 Offline-Fallback"],
        ["v0.15 (M\u00E4rz 2026)", "marketplace_monitor Refactor (JSON-Params), eGun + Willhaben, Netzwerk-Monitor, Multi-LLM Registry, NVIDIA NIM"],
        ["v0.14 (M\u00E4rz 2026)", "Queue-System, llama.cpp Output-Fix, Router-Fallback-Fix"],
        ["v0.13 (M\u00E4rz 2026)", "Proaktiver Agent, Debugging-Runden, Stabilisierung"],
        ["v0.12 (M\u00E4rz 2026)", "Home Assistant Integration"],
        ["v0.11 (M\u00E4rz 2026)", "Boot-Partition Installer, piclaw.conf"],
        ["v0.10 (M\u00E4rz 2026)", "Metriken, Kamera, MQTT, Backup & Restore"],
        ["v0.9 (M\u00E4rz 2026)", "Setup-Wizard, API-Authentifizierung, Sub-Agent Sandboxing"],
        ["v0.8 (M\u00E4rz 2026)", "Soul-System, Sub-Agenten, Multi-LLM-Routing, QMD Memory"]
      ]),
      p(""),
      p("Vollst\u00E4ndiges Changelog: piclaw-os/CHANGELOG.md"),
      p("Roadmap: piclaw-os/ROADMAP.md"),
    ]
  }]
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync('PiClaw-OS-Handbuch-v0.15.5.docx', buf);
  console.log('Handbuch DE v0.15.5 erstellt.');
});
