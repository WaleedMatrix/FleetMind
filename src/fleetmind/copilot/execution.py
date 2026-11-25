"""Bound tool concurrency, read-only PostgreSQL transactions, and async waiting."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import BoundedSemaphore
from time import perf_counter

from sqlalchemy import func, select, text

from fleetmind.copilot.tools import REGISTRY, ToolFailure
from fleetmind.db.database import SessionLocal
from fleetmind.observability import TOOLS, event, span

_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="fleetmind-copilot")
_SLOTS = BoundedSemaphore(4)


class ToolExecutor:
    def __init__(self, session_factory=SessionLocal):
        self.session_factory = session_factory

    def _read(self, tool, args, context, timeout):
        with self.session_factory() as db, db.begin():
            if db.get_bind().dialect.name == "postgresql":
                db.execute(text("SET TRANSACTION READ ONLY"))
                db.execute(
                    select(
                        func.set_config(
                            "statement_timeout", str(int(timeout * 1000)), True
                        )
                    )
                )
            return tool.invoke(db, args, context)

    async def run(self, tool, args, context, timeout):
        name = next(
            (name for name, entry in REGISTRY.items() if entry is tool), "other"
        )
        started = perf_counter()
        outcome = "ok"
        with span("copilot_tool"):
            try:
                return await self._run(tool, args, context, timeout)
            except BaseException:
                outcome = "error"
                raise
            finally:
                elapsed = perf_counter() - started
                TOOLS.labels(name, outcome).observe(elapsed)
                event("copilot_tool", outcome=outcome, duration=elapsed, category=name)

    async def _run(self, tool, args, context, timeout):
        if not _SLOTS.acquire(blocking=False):
            raise ToolFailure("tool_concurrency_limit")
        try:
            future = _POOL.submit(
                copy_context().run, self._read, tool, args, context, timeout
            )
        except RuntimeError:
            _SLOTS.release()
            raise ToolFailure("tool_unavailable") from None
        future.add_done_callback(lambda _: _SLOTS.release())
        try:
            return await asyncio.wait_for(asyncio.wrap_future(future), timeout)
        except TimeoutError:
            raise ToolFailure("tool_timeout") from None
