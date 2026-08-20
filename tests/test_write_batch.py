from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from server.write_batch import SQLiteBatchWriter, SQLiteWriteQueueFull


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


def test_low_priority_burst_cannot_consume_reserved_selection_capacity(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "priority-reserve.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE events (value TEXT)")
    writer = SQLiteBatchWriter(
        database_path,
        batch_size=2,
        queue_limit=4,
        batch_window_seconds=0,
        priority_reserve=1,
    )
    slow_started = threading.Event()
    release_slow = threading.Event()

    def insert(value: str, *, slow: bool = False):
        def callback(connection: sqlite3.Connection) -> str:
            if slow:
                slow_started.set()
                assert release_slow.wait(timeout=10)
            connection.execute("INSERT INTO events VALUES (?)", (value,))
            return value

        return callback

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            slow = pool.submit(writer.submit, insert("slow", slow=True), priority=10)
            assert slow_started.wait(timeout=10)
            low_one = pool.submit(writer.submit, insert("low-1"), priority=10)
            low_two = pool.submit(writer.submit, insert("low-2"), priority=10)
            deadline = time.monotonic() + 10
            while writer.stats()["pending_jobs"] < 3 and time.monotonic() < deadline:
                time.sleep(0.005)
            assert writer.stats()["pending_jobs"] == 3
            with pytest.raises(SQLiteWriteQueueFull):
                writer.submit(insert("rejected-low"), priority=10)
            critical = pool.submit(writer.submit, insert("selection"), priority=0)
            deadline = time.monotonic() + 10
            while writer.stats()["pending_jobs"] < 4 and time.monotonic() < deadline:
                time.sleep(0.005)
            assert writer.stats()["pending_jobs"] == 4
            release_slow.set()
            assert slow.result(timeout=10) == "slow"
            assert low_one.result(timeout=10) == "low-1"
            assert low_two.result(timeout=10) == "low-2"
            assert critical.result(timeout=10) == "selection"
        with sqlite3.connect(database_path) as connection:
            values = {row[0] for row in connection.execute("SELECT value FROM events")}
        assert values == {"slow", "low-1", "low-2", "selection"}
    finally:
        release_slow.set()
        writer.close()


def test_default_writer_reserves_one_thousand_selection_slots(tmp_path: Path) -> None:
    writer = SQLiteBatchWriter(tmp_path / "default-reserve.db")
    try:
        assert writer.stats()["priority_reserve"] == 1_000
    finally:
        writer.close()


def test_small_writer_preserves_low_priority_capacity(tmp_path: Path) -> None:
    writer = SQLiteBatchWriter(
        tmp_path / "small-reserve.db",
        batch_size=32,
        queue_limit=256,
    )
    try:
        stats = writer.stats()
        assert stats["priority_reserve"] == 64
        assert 256 - stats["priority_reserve"] == 192
    finally:
        writer.close()


def test_critical_burst_displaces_queued_low_priority_jobs(tmp_path: Path) -> None:
    database_path = tmp_path / "priority-displacement.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE events (value TEXT)")
    writer = SQLiteBatchWriter(
        database_path,
        batch_size=2,
        queue_limit=8,
        batch_window_seconds=0,
        priority_reserve=2,
    )
    slow_started = threading.Event()
    release_slow = threading.Event()

    def insert(value: str, *, slow: bool = False):
        def callback(connection: sqlite3.Connection) -> str:
            if slow:
                slow_started.set()
                assert release_slow.wait(timeout=10)
            connection.execute("INSERT INTO events VALUES (?)", (value,))
            return value

        return callback

    try:
        with ThreadPoolExecutor(max_workers=10) as pool:
            slow = pool.submit(writer.submit, insert("slow", slow=True), priority=10)
            assert slow_started.wait(timeout=10)
            low_futures = [
                pool.submit(writer.submit, insert(f"low-{index}"), priority=10)
                for index in range(5)
            ]
            deadline = time.monotonic() + 10
            while writer.stats()["pending_jobs"] < 6 and time.monotonic() < deadline:
                time.sleep(0.005)
            assert writer.stats()["pending_jobs"] == 6
            critical_futures = [
                pool.submit(writer.submit, insert(f"selection-{index}"), priority=0)
                for index in range(4)
            ]
            deadline = time.monotonic() + 10
            while writer.stats()["pending_jobs"] < 8 and time.monotonic() < deadline:
                time.sleep(0.005)
            assert writer.stats()["pending_jobs"] == 8
            release_slow.set()
            assert slow.result(timeout=10) == "slow"
            low_results: list[str | BaseException] = []
            for future in low_futures:
                try:
                    low_results.append(future.result(timeout=10))
                except BaseException as exc:
                    low_results.append(exc)
            assert sum(isinstance(value, SQLiteWriteQueueFull) for value in low_results) == 2
            assert sorted(future.result(timeout=10) for future in critical_futures) == [
                f"selection-{index}" for index in range(4)
            ]
        stats = writer.stats()
        assert stats["jobs_evicted"] == 2
        with sqlite3.connect(database_path) as connection:
            values = {row[0] for row in connection.execute("SELECT value FROM events")}
        assert {f"selection-{index}" for index in range(4)} <= values
        assert len({value for value in values if value.startswith("low-")}) == 3
    finally:
        release_slow.set()
        writer.close()


def test_async_submission_is_admitted_before_awaiting_commit(tmp_path: Path) -> None:
    database_path = tmp_path / "async-submit.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE events (value INTEGER)")
    writer = SQLiteBatchWriter(database_path, batch_window_seconds=0)

    async def submit() -> int:
        return await writer.submit_async(
            lambda connection: connection.execute(
                "INSERT INTO events VALUES (7)"
            ).rowcount,
            priority=0,
        )

    try:
        assert asyncio.run(submit()) == 1
        with sqlite3.connect(database_path) as connection:
            assert connection.execute("SELECT value FROM events").fetchall() == [(7,)]
    finally:
        writer.close()
