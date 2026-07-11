# PiClaw OS – Build & Sync
# make sync     → sync piclaw/ source into boot/piclaw/piclaw-src/
# make sdcard   → build SD card ZIP for offline installation
# make release  → sync + build + validate ZIP
# make test     → run both pytest suites (ohne Live-Netzwerk-Debugtests)
# make lint     → ruff check
#
# Windows-Dev: benötigt Git Bash / make + coreutils; Rezepte POSIX halten.

PICLAW_SRC  := piclaw
BOOT_SRC    := boot/piclaw/piclaw-src
VERSION     := $(shell grep '^version' pyproject.toml | cut -d'"' -f2)

.PHONY: sync sdcard release clean test lint

sync:
	@echo "→ Syncing $(PICLAW_SRC)/ → $(BOOT_SRC)/piclaw/ ..."
	@rm -rf $(BOOT_SRC)/piclaw
	@cp -r $(PICLAW_SRC) $(BOOT_SRC)/piclaw
	@cp pyproject.toml $(BOOT_SRC)/pyproject.toml
	@echo "✅ Sync done (v$(VERSION))"

sdcard: sync
	@echo "→ Building SD card ZIP (v$(VERSION)) ..."
	@cd .. && zip -r piclaw-os/piclaw-sdcard-v$(VERSION).zip piclaw-os/boot/ \
		--exclude "*/piclaw-src/piclaw/*/__pycache__/*" \
		--exclude "*/.git/*"
	@echo "✅ piclaw-sdcard-v$(VERSION).zip"

release: sync sdcard
	@echo "→ Validating ZIP ..."
	@unzip -p piclaw-sdcard-v$(VERSION).zip \
		piclaw-os/boot/piclaw/piclaw-src/pyproject.toml | grep -F 'version = "$(VERSION)"' \
		&& echo "✅ Version OK ($(VERSION))"

test:
	@python -m pytest tests piclaw/tests --ignore=tests/debug

lint:
	@ruff check piclaw tests

clean:
	@rm -f piclaw-sdcard-v*.zip
	@find . -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Clean done"
