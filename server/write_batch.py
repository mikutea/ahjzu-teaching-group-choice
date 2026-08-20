from __future__ import annotations

import heapq
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar, cast

from .database import connect


ResultT = TypeVar("ResultT")


class SQLiteWriteQueueFull(RuntimeError):
    """Raised before a write is accepted when the bounded queue is full."""


class SQLiteWriteQueueClosed(RuntimeError):
    """Raised when a caller submits after application shutdown has begun."""


@dataclass(order=True)
class _QueuedWrite(Generic[ResultT]):
    priority: int
    sequence: int
    callback: Callable[[sqlite3.Connection], ResultT] = field(compare=False)
    completed: threading.Event = field(default_factory=threading.Event, compare=False)
    result: ResultT | None = field(default=None, compare=False)
    error: BaseException | None = field(default=None, compare=False)


class SQLiteBatchWriter:
    """Serialize burst writes and commit several independent jobs together.

    SQLite permits one writer at a time. Letting every request open its own
    ``BEGIN IMMEDIATE`` transaction turns a classroom-wide click into hundreds
    of competing fsyncs and busy timeouts. This coordinator keeps a bounded,
    priority-aware FIFO and runs each job under a savepoint inside a shared
    transaction. A rejected job rolls back only its own savepoint; successful
    jobs are acknowledged only after the whole batch commits.
    """

    def __init__(
        self,
        database_path: Path,
        *,
        batch_size: int = 64,
        queue_limit: int = 4_096,
        batch_window_seconds: float = 0.004,
        connect_factory: Callable[[Path], sqlite3.Connection] = connect,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if queue_limit < batch_size:
            raise ValueError("queue_limit must be at least batch_size")
        if batch_window_seconds < 0:
            raise ValueError("batch_window_seconds must not be negative")
        self._database_path = database_path
        self._batch_size = batch_size
        self._queue_limit = queue_limit
        self._batch_window_seconds = batch_window_seconds
        self._connect_factory = connect_factory
        self._condition = threading.Condition()
        self._queue: list[_QueuedWrite[Any]] = []
        self._sequence = 0
        self._accepting = True
        self._thread: threading.Thread | None = None
        self._active_jobs = 0
        self._stats = {
            "batches": 0,
            "commits": 0,
            "jobs_succeeded": 0,
            "jobs_failed": 0,
            "max_batch_size": 0,
            "max_queue_depth": 0,
        }

    def submit(
        self,
        callback: Callable[[sqlite3.Connection], ResultT],
        *,
        priority: int = 0,
    ) -> ResultT:
        with self._condition:
            if not self._accepting:
                raise SQLiteWriteQueueClosed("SQLite write queue is closed")
            if len(self._queue) >= self._queue_limit:
                raise SQLiteWriteQueueFull("SQLite write queue is full")
            self._sequence += 1
            job = _QueuedWrite(
                priority=priority,
                sequence=self._sequence,
                callback=callback,
            )
            heapq.heappush(self._queue, job)
            self._stats["max_queue_depth"] = max(
                self._stats["max_queue_depth"], len(self._queue)
            )
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run,
                    name="sqlite-batch-writer",
                    daemon=True,
                )
                self._thread.start()
            self._condition.notify()

        job.completed.wait()
        if job.error is not None:
            raise job.error
        return cast(ResultT, job.result)

    def stats(self) -> dict[str, int]:
        with self._condition:
            return {
                **self._stats,
                "queued_jobs": len(self._queue),
                "active_jobs": self._active_jobs,
            }

    def open(self) -> None:
        """Allow a fully stopped writer to serve a new application lifespan."""

        with self._condition:
            if self._accepting:
                return
            if self._thread is not None:
                raise RuntimeError("SQLite write queue is still stopping")
            self._accepting = True

    def close(self, *, timeout_seconds: float = 30.0) -> None:
        with self._condition:
            self._accepting = False
            self._condition.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout_seconds)
            if thread.is_alive():
                raise RuntimeError("SQLite write queue did not stop cleanly")
            with self._condition:
                self._thread = None

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._queue and self._accepting:
                    self._condition.wait()
                if not self._queue and not self._accepting:
                    return
                if self._batch_window_seconds:
                    deadline = time.monotonic() + self._batch_window_seconds
                    while len(self._queue) < self._batch_size:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        self._condition.wait(timeout=remaining)
                batch = [
                    heapq.heappop(self._queue)
                    for _ in range(min(self._batch_size, len(self._queue)))
                ]
                self._active_jobs += len(batch)
                self._stats["max_batch_size"] = max(
                    self._stats["max_batch_size"], len(batch)
                )
            try:
                self._process_batch(batch)
            finally:
                with self._condition:
                    self._active_jobs -= len(batch)
                    self._condition.notify_all()

    def _process_batch(self, batch: list[_QueuedWrite[Any]]) -> None:
        connection: sqlite3.Connection | None = None
        outcomes: list[tuple[bool, Any]] = []
        batch_error: BaseException | None = None
        try:
            connection = self._connect_factory(self._database_path)
            connection.execute("BEGIN IMMEDIATE")
            for index, job in enumerate(batch):
                savepoint = f"batch_job_{index}"
                connection.execute(f"SAVEPOINT {savepoint}")
                try:
                    result = job.callback(connection)
                except BaseException as exc:
                    connection.execute(f"ROLLBACK TO {savepoint}")
                    connection.execute(f"RELEASE {savepoint}")
                    outcomes.append((False, exc))
                else:
                    connection.execute(f"RELEASE {savepoint}")
                    outcomes.append((True, result))
            connection.commit()
            with self._condition:
                self._stats["commits"] += 1
        except BaseException as exc:
            batch_error = exc
            if connection is not None:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
        finally:
            if connection is not None:
                connection.close()

        with self._condition:
            self._stats["batches"] += 1
        for index, job in enumerate(batch):
            if batch_error is not None:
                job.error = batch_error
            elif outcomes[index][0]:
                job.result = outcomes[index][1]
            else:
                job.error = outcomes[index][1]
            with self._condition:
                counter = "jobs_failed" if job.error is not None else "jobs_succeeded"
                self._stats[counter] += 1
            job.completed.set()
