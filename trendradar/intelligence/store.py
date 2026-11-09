"""Source records live separately from daily rankings and RSS history."""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit, urlunsplit


def normalize_url(value: str) -> str:
    """Normalize transport identity without discarding meaningful query parameters."""
    parts = urlsplit(value.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError("Source URL must be an absolute HTTP(S) URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("Source URLs must not contain credentials")
    host = parts.hostname.encode("idna").decode("ascii").lower()
    if ":" in host:
        host = f"[{host}]"
    port = parts.port
    if port and (parts.scheme.lower(), port) not in {("http", 80), ("https", 443)}:
        host += f":{port}"
    return urlunsplit((parts.scheme.lower(), host, parts.path or "/", parts.query, ""))


def timestamp(value: str | datetime) -> str:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timestamps must include an explicit timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class SourceDocument:
    original_url: str
    title: str
    source_kind: str
    first_seen_at: str | datetime
    fetched_at: str | datetime
    published_at: str | datetime | None = None
    summary: str = ""


class IntelligenceStore:
    """Explicit-path SQLite store; refuses unrelated or newer databases."""

    APPLICATION_ID = 0x54524941
    VERSION = 5

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            app = db.execute("PRAGMA application_id").fetchone()[0]
            version = db.execute("PRAGMA user_version").fetchone()[0]
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if app not in (0, self.APPLICATION_ID) or (app == 0 and (tables or version)):
                raise ValueError("Refusing to migrate an unrelated database")
            if version > self.VERSION:
                raise ValueError("Database requires a newer application")
            if version == 0:
                db.execute("""CREATE TABLE source_documents (
                    id INTEGER PRIMARY KEY,
                    canonical_url TEXT NOT NULL UNIQUE,
                    original_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    published_at TEXT,
                    first_seen_at TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    summary TEXT NOT NULL
                )""")
                db.execute(f"PRAGMA application_id={self.APPLICATION_ID}")
                db.execute("PRAGMA user_version=1")
            if version < 2:
                db.execute("""CREATE TABLE article_reads (
                    id INTEGER PRIMARY KEY,
                    source_id INTEGER NOT NULL REFERENCES source_documents(id),
                    fetched_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('read', 'failed')),
                    content TEXT,
                    error_code TEXT,
                    CHECK ((status='read' AND content IS NOT NULL AND error_code IS NULL)
                        OR (status='failed' AND content IS NULL AND error_code IS NOT NULL))
                )""")
                db.execute("PRAGMA user_version=2")
            if version < 3:
                db.execute("""CREATE TABLE event_versions (
                    id INTEGER PRIMARY KEY, event_key TEXT NOT NULL,
                    change_key TEXT NOT NULL, UNIQUE(event_key, change_key))""")
                db.execute("""CREATE TABLE analyses (
                    id INTEGER PRIMARY KEY,
                    read_id INTEGER NOT NULL UNIQUE REFERENCES article_reads(id),
                    version_id INTEGER REFERENCES event_versions(id),
                    payload TEXT NOT NULL)""")
                db.execute("PRAGMA user_version=3")
            if version < 4:
                db.execute("""CREATE TABLE briefings (
                    id INTEGER PRIMARY KEY, day TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL, html TEXT NOT NULL,
                    delivery TEXT NOT NULL DEFAULT 'pending'
                    CHECK(delivery IN ('pending','sending','uncertain','sent')))""")
                db.execute("""CREATE TABLE briefing_items (
                    briefing_id INTEGER NOT NULL REFERENCES briefings(id),
                    version_id INTEGER NOT NULL REFERENCES event_versions(id),
                    PRIMARY KEY(briefing_id, version_id))""")
                db.execute("PRAGMA user_version=4")
            if version < 5:
                db.execute('''CREATE TABLE chat_turns (
                    id INTEGER PRIMARY KEY, session TEXT NOT NULL,
                    question TEXT NOT NULL, answer TEXT NOT NULL)''')
                db.execute('CREATE INDEX chat_session ON chat_turns(session,id)')
                db.execute('PRAGMA user_version=5')

    def _connect(self):
        # Connection context managers commit/rollback, but do not close connections.
        from contextlib import contextmanager

        @contextmanager
        def connection():
            db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            try:
                with db:
                    yield db
            finally:
                db.close()
        return connection()

    def ingest(self, source: SourceDocument) -> int:
        if source.source_kind not in {"official", "community", "personal", "unknown"}:
            raise ValueError("Invalid source kind")
        seen, fetched = timestamp(source.first_seen_at), timestamp(source.fetched_at)
        if seen > fetched:
            raise ValueError("Discovery cannot occur after fetching")
        published = timestamp(source.published_at) if source.published_at else None
        canonical = normalize_url(source.original_url)
        with self._connect() as db:
            row = db.execute("""INSERT INTO source_documents
                (canonical_url, original_url, title, source_kind, published_at,
                 first_seen_at, fetched_at, summary) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_url) DO UPDATE SET
                    first_seen_at=min(first_seen_at, excluded.first_seen_at),
                    published_at=coalesce(published_at, excluded.published_at),
                    title=CASE WHEN excluded.fetched_at > fetched_at THEN excluded.title ELSE title END,
                    summary=CASE WHEN excluded.fetched_at > fetched_at THEN excluded.summary ELSE summary END,
                    fetched_at=max(fetched_at, excluded.fetched_at)
                RETURNING id""", (canonical, source.original_url, source.title,
                    source.source_kind, published, seen, fetched, source.summary)).fetchone()
            return row[0]

    def get_source(self, source_id: int) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM source_documents WHERE id=?", (source_id,)).fetchone()
            return dict(row) if row else None

    def record_read(self, source_id: int, fetched_at: str | datetime,
                    content: str | None = None, error_code: str | None = None) -> int:
        if (content is None) == (error_code is None) or (content is not None and not content.strip()):
            raise ValueError("Supply nonempty content or an error code, never both")
        with self._connect() as db:
            row = db.execute("""INSERT INTO article_reads
                (source_id, fetched_at, status, content, error_code) VALUES (?, ?, ?, ?, ?)
                RETURNING id""", (source_id, timestamp(fetched_at),
                    "read" if content is not None else "failed", content, error_code)).fetchone()
            return row[0]

    def get_reads(self, source_id: int) -> list[dict]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM article_reads WHERE source_id=? ORDER BY fetched_at, id", (source_id,))]
