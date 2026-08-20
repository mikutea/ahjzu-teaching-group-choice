from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from server.write_batch import SQLiteBatchWriter


def test_batch_writer_commits_a_classroom_burst_in_few_transactions(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "batch.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, value INTEGER UNIQUE)")

    writer = SQLiteBatchWriter(
        database_path,
        batch_size=64,
        queue_limit=256,
        batch_window_seconds=0.05,
    )
    barrier = threading.Barrier(101)

    def submit(value: int) -> int:
        barrier.wait(timeout=10)

        def insert(connection: sqlite3.Connection) -> int:
            connection.execute("INSERT INTO events(value) VALUES (?)", (value,))
            return value

        return writer.submit(insert)

    try:
        with ThreadPoolExecutor(max_workers=100) as pool:
            futures = [pool.submit(submit, value) for value in range(100)]
            barrier.wait(timeout=10)
            results = [future.result(timeout=20) for future in futures]
        assert sorted(results) == list(range(100))
        with sqlite3.connect(database_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 100
        stats = writer.stats()
        assert stats["commits"] <= 3
        assert stats["max_batch_size"] >= 32
        assert stats["jobs_succeeded"] == 100
        assert stats["jobs_failed"] == 0
    finally:
        writer.close()


def test_one_rejected_job_rolls_back_only_its_savepoint(tmp_path: Path) -> None:
    database_path = tmp_path / "savepoint.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE events (value INTEGER UNIQUE)")

    writer = SQLiteBatchWriter(
        database_path,
        batch_size=8,
        queue_limit=16,
        batch_window_seconds=0.05,
    )
    barrier = threading.Barrier(4)

    def submit(value: int) -> int:
        barrier.wait(timeout=10)

        def insert(connection: sqlite3.Connection) -> int:
            connection.execute("INSERT INTO events(value) VALUES (?)", (value,))
            return value

        return writer.submit(insert)

    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(submit, value) for value in (7, 7, 8)]
            barrier.wait(timeout=10)
            outcomes: list[int | BaseException] = []
            for future in futures:
                try:
                    outcomes.append(future.result(timeout=20))
                except BaseException as exc:
                    outcomes.append(exc)
        assert sorted(value for value in outcomes if isinstance(value, int)) == [7, 8]
        failures = [value for value in outcomes if isinstance(value, BaseException)]
        assert len(failures) == 1
        assert isinstance(failures[0], sqlite3.IntegrityError)
        with sqlite3.connect(database_path) as connection:
            assert connection.execute("SELECT value FROM events ORDER BY value").fetchall() == [
                (7,),
                (8,),
            ]
        stats = writer.stats()
        assert stats["commits"] == 1
        assert stats["jobs_succeeded"] == 2
        assert stats["jobs_failed"] == 1
    finally:
        writer.close()


def test_batch_writer_rejects_invalid_capacity_configuration(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="queue_limit"):
        SQLiteBatchWriter(tmp_path / "invalid.db", batch_size=8, queue_limit=7)


def test_fully_stopped_writer_can_serve_a_new_application_lifespan(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "restart.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE events (value INTEGER)")
    writer = SQLiteBatchWriter(database_path, batch_window_seconds=0)
    writer.submit(lambda connection: connection.execute("INSERT INTO events VALUES (1)"))
    writer.close()
    writer.open()
    writer.submit(lambda connection: connection.execute("INSERT INTO events VALUES (2)"))
    writer.close()
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT value FROM events ORDER BY value").fetchall() == [
            (1,),
            (2,),
        ]
