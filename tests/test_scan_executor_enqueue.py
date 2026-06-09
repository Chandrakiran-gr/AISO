"""Regression: the Procrastinate executor must open its async pool before defer.

Production bug: `default_scan_executor()` opened only the *sync* connector pool
(`app.open()`), but `enqueue` defers with `defer_async`, which needs the *async*
pool. Result was Procrastinate's "App was not open" -> HTTP 503 on every scan
enqueue. `enqueue` now lazily calls `open_async()` once before deferring.
"""

import asyncio
import unittest

from api.adapters.scan_execution import ProcrastinateScanExecutor


class _FakeApp:
    def __init__(self):
        self.async_opened = False
        self.open_async_calls = 0

    def open(self):  # the sync pool — what production opened, insufficient for defer_async
        pass

    async def open_async(self):
        self.open_async_calls += 1
        self.async_opened = True


class _FakeConfiguredTask:
    def __init__(self, app, recorder):
        self._app = app
        self._recorder = recorder

    async def defer_async(self, **kwargs):
        if not self._app.async_opened:
            # Mirrors Procrastinate's real failure mode.
            raise RuntimeError("App was not open")
        self._recorder.append(kwargs)


class _FakeTask:
    def __init__(self, app, recorder):
        self._app = app
        self._recorder = recorder

    def configure(self, **_kwargs):
        return _FakeConfiguredTask(self._app, self._recorder)


class ProcrastinateEnqueueTests(unittest.TestCase):
    def setUp(self):
        self.app = _FakeApp()
        self.deferred: list[dict] = []
        self.executor = ProcrastinateScanExecutor(
            app=self.app,
            orchestrator_task=_FakeTask(self.app, self.deferred),
        )

    def _enqueue(self, scan_run_id):
        return self.executor.enqueue(
            scan_run_id=scan_run_id,
            idempotency_key="11111111-1111-4111-8111-111111111111",
            client_id="aiso_global",
            methodology_version="AVS-1.0.0",
            cost_budget_usd=5.0,
        )

    def test_enqueue_opens_async_pool_before_deferring(self):
        # Production opens only the sync pool first; enqueue must still succeed.
        self.executor.open()
        handle = asyncio.run(self._enqueue("77777777-7777-4777-8777-777777777777"))
        self.assertTrue(self.app.async_opened)
        self.assertEqual(self.app.open_async_calls, 1)
        self.assertEqual(len(self.deferred), 1)
        self.assertEqual(str(handle.scan_run_id), "77777777-7777-4777-8777-777777777777")

    def test_async_pool_opened_only_once_across_enqueues(self):
        async def scenario():
            await self._enqueue("77777777-7777-4777-8777-777777777777")
            await self._enqueue("88888888-8888-4888-8888-888888888888")

        asyncio.run(scenario())
        self.assertEqual(self.app.open_async_calls, 1)  # open-once, reuse the pool
        self.assertEqual(len(self.deferred), 2)


if __name__ == "__main__":
    unittest.main()
