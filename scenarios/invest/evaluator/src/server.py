import argparse
import sys
from pathlib import Path

# Ensure project root is on sys.path so `scenarios` imports resolve when run as a script.
ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from executor import Executor


def main():
    parser = argparse.ArgumentParser(description="Run the invest evaluator (green agent).")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind the server")
    parser.add_argument("--port", type=int, default=9109, help="Port to bind the server")
    parser.add_argument("--card-url", type=str, help="URL to advertise in the agent card")
    args = parser.parse_args()

    skill = AgentSkill(
        id="invest_evaluation",
        name="Invest Benchmark Evaluation",
        description="Evaluates whether the research agent correctly predicts 30%+ price moves.",
        tags=["benchmark", "evaluation", "investing"],
        examples=[
            '{"participants": {"agent": "http://localhost:9119"}, "config": {"tickers": ["RR"]}}'
        ],
    )

    agent_card = AgentCard(
        name="invest_evaluator",
        description="Evaluator that double-checks predictions using December 2025 evidence.",
        url=args.card_url or f"http://{args.host}:{args.port}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )

    request_handler = DefaultRequestHandler(
        agent_executor=Executor(),
        task_store=InMemoryTaskStore(),
    )

    app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    uvicorn.run(
        app.build(),
        host=args.host,
        port=args.port,
        timeout_keep_alive=300,
    )


if __name__ == "__main__":
    main()
