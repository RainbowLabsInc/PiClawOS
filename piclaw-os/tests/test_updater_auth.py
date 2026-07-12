"""Regressionstests für den Updater: Auth-Fehler-Hinweise, Credential-Cleanup
und Locale-feste git-Aufrufe.

Hintergrund (2026-07-12): Ein abgelaufener PAT in [updater] github_token wurde
bei jedem Lauf neu in ~/.git-credentials geschrieben und brach den Pull mit
"Invalid username or token" – nach Leeren des Tokens blieb der Fehler kryptisch
("could not read Username"), weil git ohne TTY nach Credentials fragen wollte.
Zusätzlich matchten die Substring-Checks ("Already up to date", "Saved") auf
deutschsprachigen Systemen nie, weil git lokalisierte Meldungen ausgibt.
"""

from pathlib import Path

from piclaw.config import UpdaterConfig
from piclaw.tools import updater
from piclaw.tools.updater import _GIT_ENV, _auth_hint, _configure_git_credentials


# ── _auth_hint ───────────────────────────────────────────────────────────


def test_auth_hint_detects_invalid_token():
    out = (
        "remote: Invalid username or token. "
        "Password authentication is not supported for Git operations."
    )
    hint = _auth_hint(out)
    assert "github_token" in hint
    assert "[updater]" in hint


def test_auth_hint_detects_username_prompt_failure():
    # Tritt auf, wenn der Server 401 liefert und git ohne TTY prompten will
    assert _auth_hint("fatal: could not read Username for 'https://github.com'")


def test_auth_hint_detects_terminal_prompts_disabled():
    assert _auth_hint(
        "fatal: could not read Username for 'https://github.com': "
        "terminal prompts disabled"
    )


def test_auth_hint_silent_on_non_auth_errors():
    assert _auth_hint("error: Your local changes would be overwritten by merge") == ""
    assert _auth_hint("Already up to date.") == ""
    assert _auth_hint("") == ""


# ── _configure_git_credentials ───────────────────────────────────────────


async def test_cleanup_removes_stale_host_entry_when_token_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    cred = tmp_path / ".git-credentials"
    cred.write_text(
        "https://x-access-token:DEAD_TOKEN@github.com\n"
        "https://user:pw@gitlab.example.com\n"
    )

    await _configure_git_credentials(UpdaterConfig(github_token=""))

    content = cred.read_text()
    assert "github.com" not in content, "toter github.com-Eintrag muss entfernt werden"
    assert "gitlab.example.com" in content, "fremde Hosts dürfen nicht angefasst werden"


async def test_cleanup_is_noop_without_credentials_file(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    # Datei existiert nicht → darf weder crashen noch eine anlegen
    await _configure_git_credentials(UpdaterConfig(github_token=""))
    assert not (tmp_path / ".git-credentials").exists()


async def test_token_written_and_old_entry_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    run_calls: list[str] = []

    async def fake_run(cmd: str, timeout: int = 120):
        run_calls.append(cmd)
        return 0, ""

    # git config --global darf im Test nie wirklich laufen
    monkeypatch.setattr(updater, "_run", fake_run)

    cred = tmp_path / ".git-credentials"
    cred.write_text("https://x-access-token:OLD_TOKEN@github.com\n")

    cfg = UpdaterConfig(
        github_token="NEW_TOKEN",
        repo_url="https://github.com/RainbowLabsInc/PiClawOS.git",
    )
    await _configure_git_credentials(cfg)

    content = cred.read_text()
    assert "NEW_TOKEN" in content
    assert "OLD_TOKEN" not in content, "alter Eintrag muss ersetzt, nicht ergänzt werden"
    assert content.count("github.com") == 1
    assert any("credential.helper store" in c for c in run_calls)


# ── Locale-feste git-Aufrufe ─────────────────────────────────────────────


def test_git_env_forces_english_and_no_prompt():
    # Die Substring-Checks im Updater ("Already up to date", "Saved") sind nur
    # mit englischer Locale zuverlässig; ohne GIT_TERMINAL_PROMPT=0 hängt git
    # ohne TTY bei 401-Antworten.
    assert "LC_ALL=C" in _GIT_ENV
    assert "GIT_TERMINAL_PROMPT=0" in _GIT_ENV
