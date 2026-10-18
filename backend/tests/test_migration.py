import json
import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import settings


def test_existing_accounts_reports_and_sources_survive(monkeypatch, tmp_path):
    path = tmp_path / "old.sqlite"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(path))
    settings.cache_clear()
    config = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parent.parent / "alembic"))
    try:
        command.upgrade(config, "1f9ea52e9d4b")
        with sqlite3.connect(path) as db:
            for suffix in ("a", "b"):
                db.execute(
                    "INSERT INTO users(id,email,password_hash,created_at) VALUES (?,?,?,?)",
                    (
                        "12345678-1234-1234-1234-" + "0" * 11 + suffix,
                        suffix + "@example.com",
                        "keep-hash",
                        "2026-10-01",
                    ),
                )
            db.execute(
                "INSERT INTO investigations(id,user_id,domain,mode,depth,status,progress,report,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    "report",
                    "12345678-1234-1234-1234-00000000000a",
                    "example.com",
                    "demo",
                    "standard",
                    "completed",
                    100,
                    json.dumps({"keep": "unchanged"}),
                    "2026-10-01",
                    "2026-10-01",
                ),
            )
            db.execute(
                "INSERT INTO evidence(id,investigation_id,source_url,source_type,category,content,content_hash,signals,provenance,collection_method,collected_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "source",
                    "report",
                    "local:test",
                    "text",
                    "documentation",
                    "existing content",
                    "a" * 64,
                    "{}",
                    "original attribution",
                    "versioned_fixture",
                    "2026-10-01",
                ),
            )
        command.upgrade(config, "head")
        with sqlite3.connect(path) as db:
            names = db.execute("SELECT username,password_hash FROM users ORDER BY id").fetchall()
            assert len({name for name, _ in names}) == 2
            assert all(name.startswith("user_") and password == "keep-hash" for name, password in names)
            assert json.loads(db.execute("SELECT report FROM investigations").fetchone()[0]) == {
                "keep": "unchanged"
            }
            assert db.execute("SELECT content,original_content FROM evidence").fetchone() == (
                "existing content",
                None,
            )
            assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "4c17a862be39"
            assert "processing_options" in {row[1] for row in db.execute("PRAGMA table_info(report_questions)")}
            assert not db.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        settings.cache_clear()


def test_existing_questions_backfill_to_chats_and_keep_answers(monkeypatch, tmp_path):
    path=tmp_path/'questions.sqlite'
    monkeypatch.setenv('DATABASE_URL','sqlite:///'+str(path));settings.cache_clear()
    config=Config(str(Path(__file__).parent.parent/'alembic.ini'))
    config.set_main_option('script_location',str(Path(__file__).parent.parent/'alembic'))
    try:
        command.upgrade(config,'3a08d51ef927')
        with sqlite3.connect(path) as db:
            db.execute("INSERT INTO users(id,email,username,password_hash,created_at) VALUES ('owner','owner@example.com','owner','keep','2026-10-01')")
            db.execute("INSERT INTO investigations(id,user_id,domain,mode,depth,status,progress,created_at,updated_at) VALUES ('report','owner','example.com','saved','standard','completed',100,'2026-10-01','2026-10-01')")
            db.execute("INSERT INTO report_questions(id,investigation_id,question,status,answer,created_at,updated_at) VALUES ('q','report','Explain the application.','completed','{\"statements\":[]}','2026-10-01','2026-10-01')")
        command.upgrade(config,'head')
        with sqlite3.connect(path) as db:
            assert db.execute('SELECT title FROM research_chats').fetchone()==('Explain the application.',)
            question=db.execute('SELECT chat_id,answer FROM report_questions').fetchone()
            assert question[0] and question[1]=='{"statements":[]}'
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
            db.execute('PRAGMA foreign_keys=ON');db.execute('DELETE FROM investigations')
            assert db.execute('SELECT count(*) FROM research_chats').fetchone()[0]==0
            assert db.execute('SELECT count(*) FROM report_questions').fetchone()[0]==0
    finally:settings.cache_clear()
