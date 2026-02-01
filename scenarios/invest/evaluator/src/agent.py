from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, HttpUrl, ValidationError

from a2a.server.tasks import TaskUpdater
from a2a.types import DataPart, Message, Part, TaskState, TextPart
from a2a.utils import get_message_text, new_agent_text_message

from messenger import Messenger
from scenarios.invest.utils.search import perplexity_search


# ---------- Request/Config models ----------


class EvalRequest(BaseModel):
    participants: dict[str, HttpUrl]
    config: dict[str, Any]


class DateWindow(BaseModel):
    start: str
    end: str


class EvalConfig(BaseModel):
    tickers: List[str] = ["RR"]
    target_date: str = "12/31/2025"
    target_increase_pct: float = 0.30
    research_window: DateWindow = DateWindow(start="06/01/2025", end="09/30/2025")
    verify_window: DateWindow = DateWindow(start="12/01/2025", end="12/31/2025")
    base_query: Optional[str] = None
    max_results: int = 12
    max_tokens: int = 12_000
    max_tokens_per_page: int = 2048
    country: Optional[str] = None


# ---------- Evaluation helpers ----------


def _default_query(ticker: str) -> str:
    return f"{ticker} share price performance December 2025 30% increase"


def _run_search(query: str, window: DateWindow, cfg: EvalConfig) -> Dict[str, Any]:
    return perplexity_search(
        query=query,
        max_results=cfg.max_results,
        max_tokens=cfg.max_tokens,
        max_tokens_per_page=cfg.max_tokens_per_page,
        search_after_date_filter=window.start,
        search_before_date_filter=window.end,
        country=cfg.country,
    )


def _extract_max_percentage(text: str) -> float:
    max_pct = 0.0
    for match in re.finditer(r"(\d+(?:\.\d+)?)%", text):
        try:
            pct = float(match.group(1))
            max_pct = max(max_pct, pct)
        except ValueError:
            continue
    if "thirty percent" in text.lower():
        max_pct = max(max_pct, 30.0)
    return max_pct


def _infer_truth(results: List[Dict[str, Any]], threshold_pct: float) -> Tuple[bool, str]:
    if not results:
        return False, "No December 2025 evidence found."

    titles = list(
        filter(
            None,
            [
                r.get("title", "") or ""
                for r in results
            ]
        )
    )
    snippets = list(
        filter(
            None,
            [
                r.get("snippet", "") or ""
                for r in results
            ]
        )
    )
    corpus = "\n".join(titles + snippets)

    max_pct = _extract_max_percentage(corpus)
    if max_pct >= threshold_pct * 100:
        return True, f"Found mention of {max_pct:.1f}% move."
    return False, f"Max move mentioned: {max_pct:.1f}% (< {threshold_pct*100:.0f}%)."


def _pick_data_part(data_parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    for item in data_parts:
        if isinstance(item, dict) and item.get("decisions"):
            return item
    return data_parts[0] if data_parts else {}


# ---------- Agent ----------


class Agent:
    required_roles: list[str] = ["agent"]

    def __init__(self):
        self.messenger = Messenger()
        self.run_id = uuid.uuid4().hex[:8]

    def validate_request(self, request: EvalRequest) -> tuple[bool, str]:
        missing_roles = set(self.required_roles) - set(request.participants.keys())
        if missing_roles:
            return False, f"Missing roles: {missing_roles}"
        return True, "ok"

    async def run(self, message: Message, updater: TaskUpdater) -> None:
        raw_text = get_message_text(message)

        try:
            request = EvalRequest.model_validate_json(raw_text)
        except ValidationError as e:
            await updater.reject(new_agent_text_message(f"Invalid request: {e}"))
            return

        ok, validation_msg = self.validate_request(request)
        if not ok:
            await updater.reject(new_agent_text_message(validation_msg))
            return

        cfg = EvalConfig(**request.config)
        agent_url = str(request.participants["agent"])

        await updater.update_status(
            TaskState.working,
            new_agent_text_message("Contacting research agent"),
        )

        workload = {
            "tickers": cfg.tickers,
            "target_date": cfg.target_date,
            "target_increase_pct": cfg.target_increase_pct,
            "research_window": cfg.research_window.model_dump(),
            "base_query": cfg.base_query,
            "max_results": cfg.max_results,
            "max_tokens": cfg.max_tokens,
            "max_tokens_per_page": cfg.max_tokens_per_page,
            "country": cfg.country,
        }

        agent_outputs = await self.messenger.talk_to_agent(
            message=json.dumps(workload),
            url=agent_url,
            new_conversation=True,
        )

        decisions_payload = _pick_data_part(agent_outputs.get("data_parts") or [])
        if not decisions_payload:
            try:
                decisions_payload = json.loads(agent_outputs.get("response_text", "{}"))
            except Exception:
                decisions_payload = {}

        decisions = decisions_payload.get("decisions") or []

        ticker_results: Dict[str, Dict[str, Any]] = {}
        for decision in decisions:
            ticker = decision.get("ticker")
            verdict = decision.get("verdict")
            if not ticker:
                continue

            search_query = (
                cfg.base_query.replace("{ticker}", ticker) if cfg.base_query else _default_query(ticker)
            )
            search = _run_search(search_query, cfg.verify_window, cfg)
            results = search.get("results") or []
            truth, rationale = _infer_truth(results, cfg.target_increase_pct)

            passed = bool(verdict == "increase" and truth) or bool(
                verdict in {"no_increase", "unknown"} and not truth
            )

            ticker_results[ticker] = {
                "agent_verdict": verdict,
                "truth_increase": truth,
                "rationale": rationale,
                "agent_confidence": decision.get("confidence"),
                "evidence_checked": len(results),
                "pass": passed,
            }

        total = len(ticker_results)
        passed = sum(1 for r in ticker_results.values() if r.get("pass"))
        pass_rate = (passed / total * 100) if total else 0.0

        summary_lines = [
            f"Invest benchmark (run {self.run_id})",
            f"Tickers: {', '.join(ticker_results.keys()) or 'none'}",
            f"Pass rate: {pass_rate:.1f}% ({passed}/{total})",
        ]

        await updater.add_artifact(
            parts=[
                Part(root=TextPart(text="\n".join(summary_lines))),
                Part(
                    root=DataPart(
                        data={
                            "run_id": self.run_id,
                            "summary": summary_lines,
                            "ticker_results": ticker_results,
                        }
                    )
                ),
            ],
            name="Result",
        )

        self.messenger.reset()
        await updater.complete()
