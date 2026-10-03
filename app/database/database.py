from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import Base


class Database:
    def __init__(self, url: str = "sqlite:///data/bot.db") -> None:
        if not url.startswith("sqlite:///"):
            raise ValueError("only local SQLite databases are supported")
        raw_path = url.removeprefix("sqlite:///")
        if raw_path != ":memory:":
            Path(raw_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )
        if raw_path != ":memory:":
            event.listen(self.engine, "connect", self._set_sqlite_pragmas)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False, class_=Session)

    @staticmethod
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    def initialize(self) -> None:
        Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        return self.session_factory()

    def close(self) -> None:
        self.engine.dispose()
