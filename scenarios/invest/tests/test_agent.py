"""
Lightweight test that exercises the Invest Agent core logic without starting the A2A server.

It builds the same payload the evaluator would send, invokes Agent.run with a fake
TaskUpdater, and prints the emitted artifact so you can eyeball the decision JSON.
"""

import asyncio
import os
import sys
import json
from pathlib import Path
from typing import Any, List

import pytest
from dotenv import load_dotenv

from a2a.types import Message, Part, Role, TextPart

# Allow running directly (uv run scenarios/invest/tests/test_agent.py) without installing.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scenarios.invest.agent.src.agent import Agent, AgentWorkload, ResearchWindow  # noqa: E402


class FakeUpdater:
    def __init__(self):
        self.status_updates: List[Any] = []
        self.artifacts: List[Any] = []
        self._terminal_state_reached = False

    async def update_status(self, state, message):
        self.status_updates.append((state, message))

    async def add_artifact(self, parts, name):
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
        context_id="ctx-1",
    )


@pytest.mark.asyncio
async def test_agent_runs_and_outputs_artifact(capfd=None):
    # Load .env at repo root so PERPLEXITY_API_KEY is available when run via uv.
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        pytest.skip(".env not found at repository root")

    load_dotenv(env_path, override=True)

    if not os.getenv("PERPLEXITY_API_KEY"):
        pytest.skip("PERPLEXITY_API_KEY not set; skipping live Perplexity call")

    workload = AgentWorkload(
        tickers=["RR"],
        target_date="12/31/2025",
        research_window=ResearchWindow(start="06/01/2025", end="09/30/2025"),
        target_increase_pct=0.30,
    )

    agent = Agent()
    updater = FakeUpdater()
    msg = _make_message(workload.model_dump_json())

    await agent.run(msg, updater)

    # Print artifacts so the CLI output matches the user's request.
    for artifact in updater.artifacts:
        print(
            json.dumps(
                {"name": artifact["name"], "parts": [p.root.data for p in artifact["parts"]]},
                indent=2,
            )
        )

    if capfd is not None:
        captured = capfd.readouterr()
        assert "decisions" in captured.out

    assert updater.artifacts, "Agent did not emit artifacts"


def main():
    asyncio.run(test_agent_runs_and_outputs_artifact())


if __name__ == "__main__":
    main()
