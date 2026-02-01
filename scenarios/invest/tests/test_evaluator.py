"""
Exercise the Invest evaluator in isolation using the recorded agent output.

The test avoids real network calls by mocking the evaluator's messenger and
search helpers. It feeds the saved agent artifact (agent_output.json) and
prints the evaluation summary so running the file directly mirrors the
workflow from test_agent.py.
"""

import asyncio
import contextlib
import json
import sys
from pathlib import Path
from typing import Any, List, Tuple
from unittest.mock import patch

try:
    import pytest
except ModuleNotFoundError:  # Allow running as a plain script without pytest installed.
    pytest = None

from a2a.types import DataPart, Message, Part, Role, TextPart

# Allow running directly (uv run scenarios/invest/tests/test_evaluator.py) without installing.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scenarios.invest.evaluator.src import agent as evaluator_agent  # noqa: E402


class FakeUpdater:
    def __init__(self):
        self.status_updates: List[Any] = []
        self.artifacts: List[dict[str, Any]] = []
        self._terminal_state_reached = False

    async def update_status(self, state, message):
        self.status_updates.append((state, message))

    async def add_artifact(self, parts, name):
        # Preserve the original Part objects so downstream code can introspect them.
        self.artifacts.append({"name": name, "parts": parts})

    async def complete(self):
        self._terminal_state_reached = True

    async def reject(self, msg):
        self._terminal_state_reached = True
        self.status_updates.append(("rejected", msg))

    async def failed(self, msg):
        self._terminal_state_reached = True
        self.status_updates.append(("failed", msg))


def _make_message(payload: str) -> Message:
    return Message(
        kind="message",
        role=Role.user,
        parts=[Part(TextPart(kind="text", text=payload))],
        message_id="test-msg",
        context_id="ctx-eval",
    )


def _unwrap_parts(parts: List[Part]) -> Tuple[List[str], List[dict[str, Any]]]:
    texts: List[str] = []
    data: List[dict[str, Any]] = []
    for part in parts:
        if isinstance(part.root, TextPart):
            texts.append(part.root.text)
        elif isinstance(part.root, DataPart):
            # Copy to detach from Pydantic classes, keeping test output JSON friendly.
            data.append(json.loads(json.dumps(part.root.data)))
    return texts, data


def load_recorded_decisions() -> dict[str, Any]:
    """Load the saved agent artifact and pull out the decisions payload."""
    path = Path(__file__).with_name("agent_output.json")
    payload = json.loads(path.read_text())
    if isinstance(payload, dict) and "parts" in payload:
        for item in payload["parts"]:
            if isinstance(item, dict) and item.get("decisions"):
                return item
    return payload


async def exercise_evaluator(monkeypatch=None, capfd=None) -> dict[str, Any]:
    """Run the evaluator agent with mocked dependencies and return the data artifact."""
    decisions_payload = load_recorded_decisions()

    async def fake_talk_to_agent(self, message, url, new_conversation=False, timeout=300):
        # Simulate the research agent response that the evaluator expects.
        return {
            "data_parts": [decisions_payload],
            "response_text": "",
            "status": "completed",
            "context_id": "ctx-mocked",
        }

    def fake_run_search(query, window, cfg):
        # Pretend December 2025 evidence confirms a >30% move.
        return {
            "results": [
                {
                    "title": "RR share price jumped 33% in Dec 2025",
                    "snippet": "RR gained roughly 33% between Dec 1 and Dec 20, 2025 on bullish guidance.",
                }
            ]
        }

    cleanup: contextlib.AbstractContextManager
    if monkeypatch:
        monkeypatch.setattr(evaluator_agent.Messenger, "talk_to_agent", fake_talk_to_agent)
        monkeypatch.setattr(evaluator_agent, "_run_search", fake_run_search)
        cleanup = contextlib.nullcontext()
    else:
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(evaluator_agent.Messenger, "talk_to_agent", fake_talk_to_agent))
        stack.enter_context(patch.object(evaluator_agent, "_run_search", fake_run_search))
        cleanup = stack

    with cleanup:
        agent = evaluator_agent.Agent()
        updater = FakeUpdater()
        msg = _make_message(
            json.dumps(
                {
                    "participants": {"agent": "http://localhost:9119"},
                    "config": {},  # Use evaluator defaults to mirror the original task.
                }
            )
        )
        await agent.run(msg, updater)

    assert updater.artifacts, "Evaluator did not emit artifacts"
    artifact = updater.artifacts[-1]
    text_parts, data_parts = _unwrap_parts(artifact["parts"])

    print(
        json.dumps(
            {
                "name": artifact["name"],
                "text": text_parts,
                "data": data_parts,
            },
            indent=2,
        )
    )

    if capfd is not None:
        captured = capfd.readouterr()
        assert "Pass rate" in captured.out

    return data_parts[0]


if pytest:

    @pytest.mark.asyncio
    async def test_evaluator_validates_recorded_output(monkeypatch, capfd):
        data = await exercise_evaluator(monkeypatch, capfd)
        ticker_result = data["ticker_results"]["RR"]
        assert ticker_result["agent_verdict"] == "increase"
        assert ticker_result["pass"] is True
        assert ticker_result["truth_increase"] is True
        assert data["summary"], "Summary should contain evaluation lines"


def main():
    asyncio.run(exercise_evaluator())


if __name__ == "__main__":
    main()
