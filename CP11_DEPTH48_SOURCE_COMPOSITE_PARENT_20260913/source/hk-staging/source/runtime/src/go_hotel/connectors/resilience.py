from __future__ import annotations
import asyncio, time
from dataclasses import dataclass
from collections import deque
from typing import Awaitable, Callable, TypeVar
import httpx

T=TypeVar('T')
class ConnectorTimeout(RuntimeError): pass
class CircuitOpen(RuntimeError): pass

@dataclass
class CircuitConfig:
    failure_threshold: int = 3
    recovery_seconds: float = 10.0
    rolling_window_seconds: float = 30.0

class CircuitBreaker:
    def __init__(self, config: CircuitConfig | None=None):
        self.config=config or CircuitConfig(); self.failures=deque(); self.opened_at: float | None=None
    def _trim(self):
        cutoff=time.monotonic()-self.config.rolling_window_seconds
        while self.failures and self.failures[0] < cutoff: self.failures.popleft()
    def allow(self):
        if self.opened_at is not None:
            if time.monotonic()-self.opened_at < self.config.recovery_seconds: raise CircuitOpen("connector circuit is open")
            self.opened_at=None; self.failures.clear()
    def success(self): self.failures.clear(); self.opened_at=None
    def failure(self):
        self.failures.append(time.monotonic()); self._trim()
        if len(self.failures) >= self.config.failure_threshold: self.opened_at=time.monotonic()

class ResilientConnector:
    def __init__(self, inner, *, timeout_seconds: float=4.0, retries: int=1, circuit: CircuitBreaker | None=None):
        self.inner=inner; self.metadata=inner.metadata; self.timeout_seconds=timeout_seconds; self.retries=retries; self.circuit=circuit or CircuitBreaker()
    async def _call(self, fn: Callable[[], Awaitable[T]], *, retryable: bool=True) -> T:
        self.circuit.allow(); last=None
        attempts=1+(self.retries if retryable else 0)
        for attempt in range(attempts):
            try:
                result=await asyncio.wait_for(fn(), timeout=self.timeout_seconds)
                self.circuit.success(); return result
            except asyncio.TimeoutError as exc:
                last=ConnectorTimeout("connector request timed out"); self.circuit.failure()
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last=exc; self.circuit.failure()
            if attempt + 1 < attempts: await asyncio.sleep(min(.25*(2**attempt),1.0))
        raise last or RuntimeError("connector request failed")
    async def search(self,*a,**k): return await self._call(lambda:self.inner.search(*a,**k), retryable=True)
    async def prebook(self,*a,**k): return await self._call(lambda:self.inner.prebook(*a,**k), retryable=True)
    async def book(self,*a,**k): return await self._call(lambda:self.inner.book(*a,**k), retryable=bool(self.metadata.capabilities.idempotent_book))
    async def status(self,*a,**k): return await self._call(lambda:self.inner.status(*a,**k), retryable=True)
    async def cancel(self,*a,**k): return await self._call(lambda:self.inner.cancel(*a,**k), retryable=False)
    async def change(self,*a,**k): return await self._call(lambda:self.inner.change(*a,**k), retryable=False)
    async def health(self): return await self._call(lambda:self.inner.health(), retryable=True)
