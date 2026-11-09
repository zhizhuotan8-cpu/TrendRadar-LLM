from dataclasses import replace
import sqlite3

import pytest

from trendradar.intelligence.store import IntelligenceStore, SourceDocument, normalize_url


def document(**changes):
    source = SourceDocument("https://EXAMPLE.com:443/article#section", "Release", "official",
                            "2026-11-09T09:00:00+08:00", "2026-11-09T09:00:00+08:00")
    return replace(source, **changes)


def test_idempotence_reopen_and_time_separation(tmp_path):
    path = tmp_path / "intelligence.db"
    store = IntelligenceStore(path)
    key = store.ingest(document())
    assert store.ingest(document()) == key
    store = IntelligenceStore(path)
    assert store.ingest(document(original_url="https://example.com/article",
                                 fetched_at="2026-11-10T00:00:00Z",
                                 published_at="2025-01-01T00:00:00Z")) == key
    row = store.get_source(key)
    assert row["first_seen_at"] == "2026-11-09T01:00:00.000000+00:00"
    assert row["published_at"].startswith("2025-01-01")
    assert row["original_url"] == document().original_url
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM source_documents").fetchone()[0] == 1
        assert db.execute("PRAGMA user_version").fetchone()[0] == IntelligenceStore.VERSION


def test_unknown_publication_and_out_of_order_ingestion(tmp_path):
    store = IntelligenceStore(tmp_path / "domain.db")
    key = store.ingest(document(title="New", fetched_at="2026-11-11T00:00:00Z"))
    store.ingest(document(title="Old"))
    assert store.get_source(key)["title"] == "New"
    assert store.get_source(key)["published_at"] is None


def test_preserves_query_identity():
    assert normalize_url("https://EXAMPLE.com:443#x") == "https://example.com/"
    assert normalize_url("https://example.com/?id=1") != normalize_url("https://example.com/?id=2")


@pytest.mark.parametrize("url", ["file:///tmp/a", "relative", "https://user:secret@example.com"])
def test_invalid_urls(url):
    with pytest.raises(ValueError):
        normalize_url(url)


def test_rejects_ambiguous_time(tmp_path):
    store = IntelligenceStore(tmp_path / "domain.db")
    with pytest.raises(ValueError):
        store.ingest(document(published_at="2026-11-09T00:00:00"))
    assert store.get_source(1) is None


@pytest.mark.parametrize("foreign", [True, False])
def test_does_not_modify_foreign_or_future_database(tmp_path, foreign):
    path = tmp_path / "existing.db"
    with sqlite3.connect(path) as db:
        if foreign:
            db.execute("CREATE TABLE history (title TEXT)")
        else:
            db.execute(f"PRAGMA application_id={IntelligenceStore.APPLICATION_ID}")
            db.execute("PRAGMA user_version=999")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        IntelligenceStore(path)
    assert path.read_bytes() == before
