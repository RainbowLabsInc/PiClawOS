const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType,
  PageNumber, Footer, Header, LevelFormat, PageBreak
} = require('docx');
const fs = require('fs');

const C = {
  accent:  "5B50E8",
  accent2: "2196F3",
  dark:    "1A1A2E",
  gray:    "555555",
  light:   "F5F4FF",
  mid:     "EAE8FF",
  white:   "FFFFFF",
  code_bg: "F0F0F0",
};

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const noBorder = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };
const noBorders = { top: noBorder, bottom: noBorder, left: noBorder, right: noBorder };

function h1(t) { return new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun({ text: t, bold: true, font: "Arial", size: 36, color: C.accent })], spacing: { before: 480, after: 200 }, border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: C.accent, space: 4 } } }); }
function h2(t) { return new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun({ text: t, bold: true, font: "Arial", size: 28, color: C.dark })], spacing: { before: 360, after: 140 } }); }
function h3(t) { return new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun({ text: t, bold: true, font: "Arial", size: 24, color: C.accent2 })], spacing: { before: 240, after: 100 } }); }
function p(t) { return new Paragraph({ children: [new TextRun({ text: t, font: "Arial", size: 22, color: C.gray })], spacing: { before: 80, after: 80 } }); }
function code(t) { return new Paragraph({ children: [new TextRun({ text: t, font: "Courier New", size: 18, color: C.dark })], shading: { fill: C.code_bg, type: ShadingType.CLEAR }, spacing: { before: 60, after: 60 }, indent: { left: 360 }, border: { left: { style: BorderStyle.SINGLE, size: 8, color: C.accent, space: 8 } } }); }
function bullet(t, level = 0) { return new Paragraph({ numbering: { reference: "bullets", level }, children: [new TextRun({ text: t, font: "Arial", size: 22, color: C.gray })], spacing: { before: 40, after: 40 } }); }
function spacer() { return new Paragraph({ children: [new TextRun("")], spacing: { before: 120, after: 120 } }); }
function pageBreak() { return new Paragraph({ children: [new PageBreak()] }); }

function infoBox(title, lines, fillColor = C.light) {
  const rows = [new TableRow({ children: [new TableCell({ borders, shading: { fill: C.accent, type: ShadingType.CLEAR }, margins: { top: 100, bottom: 100, left: 160, right: 160 }, children: [new Paragraph({ children: [new TextRun({ text: title, font: "Arial", size: 22, bold: true, color: C.white })] })] })] })];
  for (const l of lines) rows.push(new TableRow({ children: [new TableCell({ borders, shading: { fill: fillColor, type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 160, right: 160 }, children: [new Paragraph({ children: [new TextRun({ text: l, font: "Arial", size: 21, color: C.dark })] })] })] }));
  return new Table({ width: { size: 9360, type: WidthType.DXA }, columnWidths: [9360], rows });
}

function twoCol(rows_data, w1 = 3000, w2 = 6360) {
  return new Table({
    width: { size: 9360, type: WidthType.DXA }, columnWidths: [w1, w2],
    rows: rows_data.map(([a, b]) => new TableRow({ children: [
      new TableCell({ borders, width: { size: w1, type: WidthType.DXA }, shading: { fill: C.mid, type: ShadingType.CLEAR }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: a, font: "Arial", size: 20, bold: true, color: C.dark })] })] }),
      new TableCell({ borders, width: { size: w2, type: WidthType.DXA }, margins: { top: 80, bottom: 80, left: 120, right: 120 }, children: [new Paragraph({ children: [new TextRun({ text: b, font: "Arial", size: 20, color: C.gray })] })] }),
    ]}))
  });
}

function coverPage() {
  return [
    spacer(), spacer(), spacer(),
    new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "PiClaw OS", font: "Arial", size: 72, bold: true, color: C.accent })], spacing: { before: 0, after: 120 } }),
    new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "v0.15.0", font: "Arial", size: 32, color: C.accent2 })], spacing: { before: 0, after: 240 } }),
    new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "AI Operating System for Raspberry Pi 5", font: "Arial", size: 28, color: C.gray })], spacing: { before: 0, after: 600 } }),
    new Table({ width: { size: 6000, type: WidthType.DXA }, columnWidths: [6000], rows: [new TableRow({ children: [new TableCell({
      borders: { top: { style: BorderStyle.SINGLE, size: 8, color: C.accent }, bottom: noBorder, left: noBorder, right: noBorder },
      shading: { fill: C.light, type: ShadingType.CLEAR }, margins: { top: 240, bottom: 240, left: 360, right: 360 },
      children: [
        new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Dameon — Your Personal AI Agent", font: "Arial", size: 24, bold: true, color: C.dark })], spacing: { before: 0, after: 80 } }),
        new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Raspberry Pi 5 · Kimi K2 · Gemma 2B · NVIDIA NIM", font: "Arial", size: 20, color: C.gray })], spacing: { before: 0, after: 0 } }),
      ]
    })]})]}),
    spacer(), spacer(), spacer(), spacer(), spacer(),
    new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "March 2026", font: "Arial", size: 22, color: C.gray })] }),
    pageBreak(),
  ];
}

const doc = new Document({
  numbering: { config: [{ reference: "bullets", levels: [
    { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 480, hanging: 240 } } } },
    { level: 1, format: LevelFormat.BULLET, text: "–", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 960, hanging: 240 } } } },
  ]}] },
  styles: {
    default: { document: { run: { font: "Arial", size: 22 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 36, bold: true, font: "Arial", color: C.accent }, paragraph: { spacing: { before: 480, after: 200 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 28, bold: true, font: "Arial", color: C.dark }, paragraph: { spacing: { before: 360, after: 140 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 24, bold: true, font: "Arial", color: C.accent2 }, paragraph: { spacing: { before: 240, after: 100 }, outlineLevel: 2 } },
    ]
  },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, right: 1134, bottom: 1134, left: 1134 } } },
    headers: { default: new Header({ children: [new Paragraph({ children: [new TextRun({ text: "PiClaw OS v0.15 — Manual", font: "Arial", size: 18, color: C.gray })], border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: C.accent, space: 4 } }, spacing: { after: 0 } })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "Page ", font: "Arial", size: 18, color: C.gray }), new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 18, color: C.gray }), new TextRun({ text: " of ", font: "Arial", size: 18, color: C.gray }), new TextRun({ children: [PageNumber.TOTAL_PAGES], font: "Arial", size: 18, color: C.gray })], border: { top: { style: BorderStyle.SINGLE, size: 4, color: C.accent, space: 4 } }, spacing: { before: 80 } })] }) },
    children: [
      ...coverPage(),

      // Ch 1: Overview
      h1("1. What is PiClaw OS?"),
      p("PiClaw OS is an AI operating system for the Raspberry Pi 5. Instead of using a cloud assistant that forgets everything after each conversation, Dameon — your personal AI agent — lives permanently on your Pi."),
      spacer(),
      p("Dameon knows your hardware, remembers decisions and preferences, autonomously executes tasks, and is reachable via Telegram, Discord, or the web dashboard — even without internet."),
      spacer(),
      infoBox("Core Features", [
        "🤖  Persistent AI agent with long-term memory (QMD + MEMORY.md)",
        "📡  Reachable via Telegram, Discord, WhatsApp, Web Dashboard",
        "🔍  Marketplace search: Kleinanzeigen, eBay, eGun, willhaben, Troostwijk, Zoll-Auktion — new listing alerts",
        "🌡  Thermal LLM routing: cloud on overheating, local in normal operation",
        "🤖  Sub-agents: specialized AI helpers for search, install, monitoring",
        "🔌  Home Assistant integration: lights, thermostats, scenes by voice",
        "🛡  Watchdog: independent security daemon with append-only logs",
        "📊  Metrics dashboard with live charts in the browser",
        "🔄  Self-update: piclaw update — git pull + restart, no root prompt",
      ]),
      pageBreak(),

      // Ch 2: Installation
      h1("2. Installation"),
      h2("2.1 Requirements"),
      twoCol([
        ["Hardware", "Raspberry Pi 5 (4 GB or 8 GB recommended)"],
        ["OS", "Raspberry Pi OS Lite 64-bit (bookworm)"],
        ["Storage", "16 GB SD card minimum, 32 GB recommended"],
        ["Internet", "Required for online install and cloud LLM"],
        ["LLM Key (optional)", "NVIDIA NIM API key (nvapi-...) for cloud AI"],
      ]),
      spacer(),
      h2("2.2 Online Installation (recommended)"),
      code("# Step 1: Flash SD card with Raspberry Pi Imager"),
      code("# → Raspberry Pi OS Lite 64-bit, enable SSH + WiFi in settings"),
      spacer(),
      code("# Step 2: Boot Pi and connect"),
      code("ssh YOUR_USER@piclaw.local"),
      spacer(),
      code("# Step 3: Download and run installer"),
      code("curl -sO https://raw.githubusercontent.com/RainbowLabsInc/PiClawOS/main/piclaw-os/boot/piclaw/install.sh"),
      code("sudo bash install.sh"),
      spacer(),
      p("Duration: approx. 5–10 minutes. PiClaw starts automatically at the end."),
      spacer(),
      h2("2.3 Offline Installation (SD card)"),
      code("# In the piclaw-os/ directory on your PC:"),
      code("make sync     # populates piclaw-src/ with current code"),
      code("make sdcard   # creates piclaw-sdcard-v0.15.0.zip"),
      spacer(),
      p("Unzip, copy the boot/piclaw/ folder to the SD card boot partition."),
      code("sudo bash /boot/piclaw/install.sh"),
      spacer(),
      h2("2.4 Initial Setup After Installation"),
      code("piclaw setup    # interactive wizard: LLM key, Telegram, Soul, fan"),
      code("piclaw doctor   # system check"),
      code("piclaw          # start AI chat"),
      spacer(),
      infoBox("After Installation", [
        "Web Dashboard:   http://piclaw.local:7842",
        "AI Chat:         ssh pi@piclaw.local  →  piclaw",
        "Telegram:        write to your bot after setup",
        "API:             http://piclaw.local:7842/api/stats",
      ]),
      pageBreak(),

      // Ch 3: Getting Started
      h1("3. Getting Started"),
      h2("3.1 The AI Chat"),
      code("piclaw"),
      spacer(),
      p("PiClaw connects to the running daemon (fast responses). If the daemon is unreachable, PiClaw starts in offline mode using the local Gemma model."),
      spacer(),
      h2("3.2 Example Conversations"),
      twoCol([
        ["System status", "\"How hot is the Pi?\" / \"Show me RAM and CPU\""],
        ["Marketplace", "\"Search Raspberry Pi 5 on Kleinanzeigen near 22081, 30km radius\""],
        ["Services", "\"Start the SSH service\" / \"Is Homeassistant running?\""],
        ["Memory", "\"Remember: I prefer answers in English\""],
        ["Sub-agent", "\"Create an agent that checks CPU temperature daily at 7am\""],
        ["WiFi", "\"Connect to network MyWiFi, password xyz\""],
        ["Update", "\"Are there updates?\" / piclaw update"],
      ], 2800, 6560),
      spacer(),
      h2("3.3 Key Commands"),
      twoCol([
        ["piclaw", "Open AI chat"],
        ["piclaw doctor", "Full system check"],
        ["piclaw setup", "Interactive configuration wizard"],
        ["piclaw update", "Update PiClaw to latest version"],
        ["piclaw update check", "Show pending updates"],
        ["piclaw model download", "Download Gemma 2B locally (~1.6 GB)"],
        ["piclaw agent list", "List all sub-agents"],
        ["piclaw soul show", "Display current personality file"],
        ["piclaw llm list", "Show registered LLM backends"],
        ["piclaw backup", "Backup configuration"],
      ]),
      pageBreak(),

      // Ch 4: LLM Backends
      h1("4. AI Backends"),
      h2("4.1 Multi-LLM Router"),
      p("PiClaw can manage multiple AI backends simultaneously, automatically selecting the best one for each request based on tags, priority, and Pi temperature."),
      spacer(),
      h2("4.2 NVIDIA NIM (Default)"),
      p("Kimi K2 and Nemotron 70B run in the cloud on NVIDIA hardware. No GPU required."),
      spacer(),
      twoCol([
        ["API Key", "nvapi-... from https://build.nvidia.com"],
        ["Kimi K2 Model ID", "moonshotai/kimi-k2-instruct-0905"],
        ["Nemotron Model ID", "nvidia/llama-3.1-nemotron-70b-instruct"],
        ["Base URL", "https://integrate.api.nvidia.com/v1"],
        ["Temperature", "0.6 for Kimi K2 (recommended by NVIDIA)"],
      ]),
      spacer(),
      h2("4.3 Local Model (Gemma 2B)"),
      code("piclaw model download    # downloads Gemma 2B Q4 (~1.6 GB)"),
      code("# Model path: /etc/piclaw/models/gemma-2b-q4.gguf"),
      spacer(),
      p("Gemma 2B requires ~2.2 GB RAM and responds in 10–30 seconds on Pi 5."),
      spacer(),
      h2("4.4 Thermal Routing"),
      twoCol([
        ["< 55°C (cool)", "Local model allowed, cloud optional"],
        ["55–70°C (warm)", "Monitoring active, local model still OK"],
        ["70–80°C (hot)", "Cloud preferred, local model possible"],
        ["80–85°C (critical)", "Cloud only, local model disabled"],
        ["> 85°C (emergency)", "Everything throttled, Telegram alert sent"],
      ]),
      pageBreak(),

      // Ch 5: Soul
      h1("5. Soul — Dameon's Personality"),
      p("The Soul file defines who Dameon is: personality, language, tasks, and boundaries. It is injected first into every system prompt."),
      spacer(),
      code("piclaw soul show        # display current soul"),
      code("piclaw soul edit        # open in editor"),
      code("piclaw soul reset       # restore default"),
      spacer(),
      p("The file lives at /etc/piclaw/SOUL.md and can be edited directly. Changes take effect on the next conversation."),
      spacer(),
      infoBox("What belongs in the Soul", [
        "Name and character (direct, friendly, technically precise...)",
        "Language preference (respond in English / German)",
        "Primary tasks (home automation, Raspberry Pi, marketplace...)",
        "Behavioral rules (no destructive actions without confirmation)",
        "Context (lives in Hamburg, helps with home lab, pets...)",
      ]),
      pageBreak(),

      // Ch 6: Memory
      h1("6. Persistent Memory"),
      h2("6.1 How Memory Works"),
      p("PiClaw remembers facts, decisions, and preferences across conversations. Memory consists of three parts:"),
      spacer(),
      twoCol([
        ["MEMORY.md", "Permanent facts, decisions, preferences"],
        ["Daily logs", "Automatic logs (YYYY-MM-DD.md)"],
        ["QMD Index", "Hybrid search index (BM25 + vector + reranking)"],
      ]),
      spacer(),
      h2("6.2 Using Memory"),
      twoCol([
        ["\"Remember that\"", "Writes to MEMORY.md"],
        ["\"Do you remember...\"", "Searches QMD index"],
        ["memory_search tool", "Direct search in chat"],
        ["memory_write tool", "Explicit save"],
      ], 2800, 6560),
      spacer(),
      p("The QMD index is updated hourly in the background (systemd timer), not after each chat — that would block the Pi for minutes."),
      spacer(),
      bullet("SOUL.md is intentionally excluded from the memory index"),
      bullet("Sessions are saved as JSONL and are searchable"),
      bullet("Memory files live in: /etc/piclaw/memory/"),
      pageBreak(),

      // Ch 7: Sub-agents
      h1("7. Sub-Agents"),
      p("Sub-agents are specialized AI helpers that Dameon creates and manages for specific tasks. Each agent has its own mission, tools, and schedule."),
      spacer(),
      h2("7.1 Creating Sub-Agents"),
      code("\"Create an agent that checks CPU temperature daily at 7am\""),
      code("\"Monitor Kleinanzeigen for Raspberry Pi every 30 minutes\""),
      code("\"Start an agent that pulls my GitHub repo daily\""),
      spacer(),
      h2("7.2 Built-in Sub-Agents"),
      twoCol([
        ["SearchAssistant", "Marketplace search (Kleinanzeigen, eBay, eGun, willhaben, Troostwijk, Zoll-Auktion)"],
        ["InstallerAgent", "Install software with confirmation workflow"],
        ["WebCrawler", "Crawl websites, one-time or recurring"],
        ["Watchdog", "System monitoring, own Linux user, tamper-proof"],
      ]),
      spacer(),
      h2("7.3 CLI Management"),
      code("piclaw agent list              # all sub-agents"),
      code("piclaw agent start <name>      # start agent"),
      code("piclaw agent stop <name>       # stop agent"),
      code("piclaw agent run <name>        # run immediately"),
      code("piclaw agent remove <name>     # delete agent"),
      spacer(),
      h2("7.4 @-Prefix for Direct Invocation"),
      code("@installer  install htop"),
      pageBreak(),

      // Ch 8: Marketplace
      h1("8. Marketplace Search"),
      p("PiClaw searches Kleinanzeigen.de, eBay.de, eGun.de, willhaben.at, Troostwijk and Zoll-Auktion.de for listings. New listings are sent as alerts via Telegram. Troostwijk and Zoll-Auktion support postcode + radius search."),
      spacer(),
      code("\"Search Raspberry Pi 5 on Kleinanzeigen near 22081, 30km radius\""),
      code("\"Find a used monitor under €100 on eBay in Hamburg\""),
      code("\"Search Kleinanzeigen and eBay for Lego Technic\""),
      code("\"Search Land Rover on Zoll-Auktion\""),
      code("\"Monitor Troostwijk auctions within 100km of postcode 21224\""),
      spacer(),
      h2("8.2 Recurring Search"),
      code("\"Monitor Kleinanzeigen for Raspberry Pi 5 and alert me on new listings\""),
      spacer(),
      infoBox("How the Search Works", [
        "1. Postal code (PLZ) is automatically extracted from the request",
        "2. Search query is cleaned of noise words",
        "3. Direct search when PLZ + query is recognized (fast path)",
        "4. New listings are flagged and reported",
        "5. Previously seen listings are not reported again",
      ]),
      spacer(),
      p("The file /etc/piclaw/marketplace_seen.json contains all previously reported listings. Delete to reset."),
      pageBreak(),

      // Ch 9: Messaging
      h1("9. Messaging & Notifications"),
      h2("9.1 Telegram (Recommended)"),
      code("piclaw setup   # 'Telegram' step in wizard"),
      code("# or directly:"),
      code("piclaw messaging setup telegram"),
      spacer(),
      twoCol([
        ["Create bot", "@BotFather on Telegram → /newbot"],
        ["Find chat ID", "Message @userinfobot on Telegram"],
        ["Configuration", "/etc/piclaw/config.toml → [telegram]"],
      ]),
      spacer(),
      h2("9.2 Test All Adapters"),
      code("piclaw messaging test    # sends test message to all configured channels"),
      code("piclaw messaging status  # shows active adapters"),
      pageBreak(),

      // Ch 10: Dashboard
      h1("10. Web Dashboard"),
      p("The web dashboard is accessible at http://piclaw.local:7842."),
      spacer(),
      twoCol([
        ["Dashboard", "CPU, RAM, temperature, uptime, services"],
        ["Memory", "Search memory (BM25 + vector)"],
        ["Agents", "Create, start, stop sub-agents"],
        ["Soul", "Edit personality directly in browser"],
        ["Hardware", "I2C scan, sensors, thermal routing"],
        ["Metrics", "Time-series charts for CPU, RAM, temperature"],
        ["Camera", "Take photos, AI image analysis"],
        ["Chat", "Direct AI chat in browser"],
      ]),
      spacer(),
      p("The API token is auto-generated and embedded in the HTML page. To view: piclaw config token"),
      pageBreak(),

      // Ch 11: Updates
      h1("11. Updates"),
      p("PiClaw updates itself via git pull — no root password needed, as permissions are set during installation."),
      spacer(),
      code("piclaw update check   # show pending commits"),
      code("piclaw update         # perform update + restart"),
      code("piclaw update system  # apt upgrade (system packages)"),
      spacer(),
      infoBox("Update Process", [
        "1. git pull origin main  — fetches new code from GitHub",
        "2. pip install -e .      — only if pyproject.toml changed",
        "3. sudo systemctl restart piclaw-api piclaw-agent",
        "→ Duration: ~10–30 seconds, config is preserved",
      ]),
      pageBreak(),

      // Ch 12: Watchdog
      h1("12. Watchdog & Security"),
      p("The Watchdog runs as a separate Linux user (piclaw-watchdog) and cannot be influenced by the main agent."),
      spacer(),
      h2("12.1 What the Watchdog Monitors"),
      bullet("Disk > 85% → Warning, > 95% → Critical"),
      bullet("CPU temperature > 75°C → Warning, > 80°C → Critical"),
      bullet("RAM > 90% → Warning"),
      bullet("Services down → Warning (3× → Critical)"),
      bullet("File integrity: config.toml, systemd services, sshd_config"),
      bullet("Main agent heartbeat (every 30s)"),
      bullet("Installer hang (lock file older than 15 min)"),
      spacer(),
      code("piclaw  →  watchdog_alerts    # in chat"),
      code("piclaw  →  watchdog_status    # overview"),
      spacer(),
      p("Watchdog logs are append-only (SQLite triggers) and cannot be modified after the fact."),
      pageBreak(),

      // Ch 13: Troubleshooting
      h1("13. Troubleshooting"),
      twoCol([
        ["piclaw.local not found", "Wait 90s after boot. Check IP in router."],
        ["'No LLM backends configured'", "piclaw setup → enter LLM key or piclaw model download"],
        ["Doctor shows default values", "CONFIG_DIR bug: /etc/piclaw/config.toml missing?"],
        ["API starts and stops immediately", "Check api.log: sudo journalctl -u piclaw-api -n 50"],
        ["Watchdog: Permission denied", "chmod 1777 /etc/piclaw/ipc/ && sudo usermod -aG piclaw piclaw-watchdog"],
        ["Marketplace: no results", "PLZ correct? Delete /etc/piclaw/marketplace_seen.json to reset"],
        ["piclaw update fails", "/etc/sudoers.d/piclaw present? Re-run sudo bash install.sh"],
      ]),
      spacer(),
      code("piclaw doctor                          # full check"),
      code("sudo systemctl status piclaw-api piclaw-agent piclaw-watchdog piclaw-crawler"),
      code("sudo tail -f /var/log/piclaw/api.log"),
      pageBreak(),

      // Ch 14: Configuration
      h1("14. Configuration File"),
      p("The main configuration is at /etc/piclaw/config.toml. Key sections:"),
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
      p("Change individual values:"),
      code("piclaw config set llm.api_key nvapi-YOUR-KEY"),
      code("piclaw config set agent_name Jarvis"),
      pageBreak(),

      // Ch 15: Roadmap
      h1("15. Roadmap"),
      twoCol([
        ["v0.15.0 (now)", "Multi-LLM router, marketplace fix, clean installer, git-update"],
        ["v0.16 — AgentMail", "Email inbox for Dameon via agentmail.to"],
        ["v0.17 — LLM Autonomy", "Dameon autonomously discovers free LLM backends. Troostwijk radius search (postcode + km). Zoll-Auktion.de platform. 4 security PRs merged."],
        ["v0.17 — Emergency", "Emergency shutdown via smart plug (modem cut)"],
        ["v0.18 — Security", "fail2ban integration, IP blocking, security reports"],
        ["v0.19 — Browser", "Tandem Browser: autonomous browsing and form filling"],
        ["v0.22 — Efficiency", "Single Gemma instance (saves ~2 GB RAM)"],
      ]),
      spacer(),
      infoBox("Project Repository", [
        "https://github.com/RainbowLabsInc/PiClawOS",
        "Issues, feature requests and pull requests welcome.",
      ], C.mid),

      spacer(), spacer(),
      new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: "PiClaw OS v0.15.0 — March 2026", font: "Arial", size: 18, color: C.gray, italics: true })] }),
    ]
  }]
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync('/home/claude/PiClaw-OS-Manual-v0.15-EN.docx', buffer);
  console.log('✅ Manual-EN created');
});
