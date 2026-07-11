"""
Regressionstests für den gehärteten Parcel-Store (_modify_parcels).

Vorher: nackter PARCELS_FILE.write_text ohne Lock/Re-Read – der Monitor-
Sub-Agent im Daemon und die parcel_*-Tools im API-Prozess konnten sich
gegenseitig Updates überschreiben; eine korrupte Datei wurde vom nächsten
Save endgültig plattgemacht.
"""

import pytest


@pytest.fixture
def parcels_file(tmp_path, monkeypatch):
    import piclaw.tools.parcel_tracking as pt
    monkeypatch.setattr(pt, "PARCELS_FILE", tmp_path / "parcels.json")
    return tmp_path / "parcels.json"


def _add_parcel(pt, tn: str, **extra):
    def _mut(d):
        d["parcels"][tn] = {"tracking_number": tn, "status": "in_transit", **extra}
        return True
    return pt._modify_parcels(_mut)


def test_interleaved_writers_lose_nothing(parcels_file):
    import piclaw.tools.parcel_tracking as pt

    # Writer A liest einen Snapshot (wie der Monitor vor seinen Netzwerk-Calls)
    snapshot_a = pt._load_parcels()
    assert snapshot_a["parcels"] == {}

    # Writer B (anderer Prozess) fügt währenddessen Paket Y hinzu
    _add_parcel(pt, "YYYYYYYYYY")

    # Writer A wendet sein Delta an – auf Basis des STALE Snapshots berechnet,
    # aber via _modify_parcels gegen den frischen Stand gemerged
    _add_parcel(pt, "XXXXXXXXXX")

    data = pt._load_parcels()
    assert set(data["parcels"]) == {"XXXXXXXXXX", "YYYYYYYYYY"}


def test_monitor_delta_does_not_resurrect_removed_parcel(parcels_file):
    import piclaw.tools.parcel_tracking as pt

    _add_parcel(pt, "AAAAAAAAAA")

    # Monitor-Delta wie in parcel_monitor_check._apply: Update nur wenn
    # das Paket noch existiert
    updates = {"AAAAAAAAAA": {"status": "delivered"}}

    # Paket wird parallel entfernt
    def _remove(d):
        d["parcels"].pop("AAAAAAAAAA", None)
        return True
    pt._modify_parcels(_remove)

    def _apply(d):
        changed = False
        for tn, upd in updates.items():
            cur = d["parcels"].get(tn)
            if cur is None:
                continue
            cur.update(upd)
            changed = True
        return changed

    assert pt._modify_parcels(_apply) is False
    assert pt._load_parcels()["parcels"] == {}


def test_mutate_returning_false_writes_nothing(parcels_file):
    import piclaw.tools.parcel_tracking as pt

    pt._modify_parcels(lambda d: False)
    assert not parcels_file.exists()


def test_corrupt_parcels_file_is_quarantined(parcels_file, tmp_path):
    import piclaw.tools.parcel_tracking as pt

    corrupt_content = '{"parcels": {kaputt'
    parcels_file.write_text(corrupt_content, encoding="utf-8")

    data = pt._load_parcels()
    assert data == {"parcels": {}, "archive": {}}

    quarantined = list(tmp_path.glob("parcels.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == corrupt_content
    assert not parcels_file.exists()

    # Nächster Save überschreibt die korrupten (geretteten) Daten nicht mehr
    _add_parcel(pt, "ZZZZZZZZZZ")
    assert quarantined[0].read_text(encoding="utf-8") == corrupt_content
    assert "ZZZZZZZZZZ" in pt._load_parcels()["parcels"]
