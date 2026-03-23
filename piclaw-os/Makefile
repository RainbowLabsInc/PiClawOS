# PiClaw OS – Build & Sync
# make sync     → sync piclaw/ source into boot/piclaw/piclaw-src/
# make sdcard   → build SD card ZIP for offline installation
# make release  → sync + build + validate ZIP

PICLAW_SRC  := piclaw
BOOT_SRC    := boot/piclaw/piclaw-src
VERSION     := $(shell grep '^version' pyproject.toml | cut -d'"' -f2)

.PHONY: sync sdcard release clean

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
		piclaw-os/boot/piclaw/piclaw-src/pyproject.toml | grep "0.15.1" && echo "✅ Version OK"

clean:
	@rm -f piclaw-sdcard-v*.zip
	@find . -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Clean done"
