"""
backend/agent/tracer.py
────────────────────────
LangSmith tracing shim for Python 3.8.

The official langsmith SDK requires Python ≥ 3.9, so we implement the same
interface directly via the LangSmith REST API.

Usage:
    with Tracer.run("planner", run_id=state_id, inputs={"question": q}) as span:
        ...
        span.set_outputs({"plan": plan})

When LANGSMITH_TRACING != "true" or LANGSMITH_API_KEY is empty, all operations
are no-ops so the agent code never needs conditional guards.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Generator, Optional

import httpx

from backend.config import settings

logger = logging.getLogger("atlas.agent.tracer")

_BASE = "https://api.smith.langchain.com"
_ENABLED = (
    settings.LANGSMITH_TRACING.lower() == "true"
    and bool(settings.LANGSMITH_API_KEY)
)


def _headers() -> dict:
    return {
        "x-api-key": settings.LANGSMITH_API_KEY,
        "Content-Type": "application/json",
    }


def _post(path: str, body: dict) -> None:
    if not _ENABLED:
        return
    try:
        httpx.post(
            f"{_BASE}{path}",
            headers=_headers(),
            json=body,
            timeout=10,
        )
    except Exception as exc:
        logger.debug("LangSmith POST failed (non-fatal): %s", exc)


def _patch(path: str, body: dict) -> None:
    if not _ENABLED:
        return
    try:
        httpx.patch(
            f"{_BASE}{path}",
            headers=_headers(),
            json=body,
            timeout=10,
        )
    except Exception as exc:
        logger.debug("LangSmith PATCH failed (non-fatal): %s", exc)


class RunSpan:
    """A single LangSmith run span. Created by Tracer.run()."""

    def __init__(
        self,
        name: str,
        run_type: str,
        parent_run_id: Optional[str],
        trace_id: str,
        inputs: dict,
    ) -> None:
        self.run_id = str(uuid.uuid4())
        self.name = name
        self.run_type = run_type
        self.parent_run_id = parent_run_id
        self.trace_id = trace_id
        self._start = time.time()
        self._outputs: dict = {}
        self._error: Optional[str] = None

        _post("/runs", {
            "id": self.run_id,
            "name": name,
            "run_type": run_type,
            "parent_run_id": parent_run_id,
            "trace_id": trace_id,
            "project_name": settings.LANGSMITH_PROJECT,
            "start_time": self._start,
            "inputs": inputs,
        })

    def set_outputs(self, outputs: dict) -> None:
        self._outputs = outputs

    def set_error(self, error: str) -> None:
        self._error = error

    def end(self) -> None:
        elapsed = time.time() - self._start
        body: Dict[str, Any] = {
            "end_time": time.time(),
            "outputs": self._outputs,
            "extra": {"latency_s": round(elapsed, 3)},
        }
        if self._error:
            body["error"] = self._error
        _patch(f"/runs/{self.run_id}", body)


class Tracer:
    """
    Manages a top-level LangSmith trace for one agent invocation.

    Usage:
        tracer = Tracer()
        with tracer.run("planner", inputs={"q": question}) as span:
            result = do_work()
            span.set_outputs({"result": result})
        tracer.finish()
    """

    def __init__(self) -> None:
        self.trace_id = str(uuid.uuid4())
        self._root_span: Optional[RunSpan] = None

    def start_root(self, question: str) -> None:
        """Open the root chain span for this agent invocation."""
        self._root_span = RunSpan(
            name="atlas-agent",
            run_type="chain",
            parent_run_id=None,
            trace_id=self.trace_id,
            inputs={"question": question},
        )

    def finish_root(self, answer: str, error: Optional[str] = None) -> None:
        if self._root_span:
            self._root_span.set_outputs({"answer": answer})
            if error:
                self._root_span.set_error(error)
            self._root_span.end()

    @contextmanager
    def run(
        self,
        name: str,
        inputs: dict,
        run_type: str = "chain",
    ) -> Generator[RunSpan, None, None]:
        """Context manager that opens/closes a child span."""
        span = RunSpan(
            name=name,
            run_type=run_type,
            parent_run_id=self._root_span.run_id if self._root_span else None,
            trace_id=self.trace_id,
            inputs=inputs,
        )
        try:
            yield span
        except Exception as exc:
            span.set_error(str(exc))
            raise
        finally:
            span.end()
