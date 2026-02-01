from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError

from a2a.server.tasks import TaskUpdater
from a2a.types import DataPart, Message, Part, TaskState, TextPart
from a2a.utils import get_message_text, new_agent_text_message

from scenarios.invest.utils.search import perplexity_search

logger = logging.getLogger(__name__)


# ---------- Data models ----------


class ResearchWindow(BaseModel):
    start: str = Field(..., description="Start date (MM/DD/YYYY) for research window")
    end: str = Field(..., description="End date (MM/DD/YYYY) for research window")


class AgentWorkload(BaseModel):
    """Payload sent to the invest agent.

    Fields are intentionally generic so multiple tickers can be evaluated without
    changing the code. Only the tickers list is mandatory.
    """

    tickers: List[str] = Field(..., description="List of ticker symbols to evaluate")
    target_date: str = Field(..., description="Date we care about (MM/DD/YYYY)")
    target_increase_pct: float = Field(
        0.30, description="Required percentage increase expressed as decimal (0.30 = 30%)"
    )
    research_window: ResearchWindow = Field(
        ..., description="Date window to pull fundamentals from Perplexity"
    )
    base_query: Optional[str] = Field(
        None, description="Optional custom search query template. {ticker} will be replaced."
    )
    max_results: int = 12
    max_tokens: int = 12_000
    max_tokens_per_page: int = 2048
    country: Optional[str] = None


class Evidence(BaseModel):
    title: Optional[str]
    url: Optional[str]
    date: Optional[str]
    snippet: Optional[str]


class TickerDecision(BaseModel):
    ticker: str
    verdict: str = Field(..., description="increase | no_increase | unknown")
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str
    evidence: List[Evidence] = Field(default_factory=list)


class AgentResponse(BaseModel):
    run_id: str
    target_date: str
    target_increase_pct: float
    decisions: List[TickerDecision]


# ---------- Simple scoring helpers ----------


POSITIVE_KEYWORDS = {
    "beat",
    "record",
    "profit",
    "profitability",
    "growth",
    "upgrade",
    "raise",
    "surge",
    "soar",
    "rally",
    "strong",
    "bullish",
    "momentum",
    "guidance",
}

NEGATIVE_KEYWORDS = {
    "loss",
    "decline",
    "downgrade",
    "cut",
    "plunge",
    "slump",
    "warning",
    "bearish",
    "drop",
    "falls",
    "weak",
    "miss",
}


def _score_sentiment(text: str) -> int:
    text_lower = text.lower()
    score = 0
    for word in POSITIVE_KEYWORDS:
        score += text_lower.count(word)
    for word in NEGATIVE_KEYWORDS:
        score -= text_lower.count(word)
    return score


def _default_query(ticker: str) -> str:
    return f"{ticker} stock fundamentals outlook 2025 profitability backlog order intake"


def _windowed_perplexity_search(
    *,
    query: str,
    window: ResearchWindow,
    max_results: int,
    max_tokens: int,
    max_tokens_per_page: int,
    country: Optional[str],
) -> Dict[str, Any]:
    return perplexity_search(
        query=query,
        max_results=max_results,
        max_tokens=max_tokens,
        max_tokens_per_page=max_tokens_per_page,
        search_after_date_filter=window.start,
        search_before_date_filter=window.end,
        country=country,
    )


def _infer_verdict(results: List[Dict[str, Any]], target_increase_pct: float) -> tuple[str, float, str]:
    """Heuristic verdict based on keyword balance.

    The goal is to produce a deterministic yes/no/unknown decision without any
    LLM dependency so that evaluation remains reproducible.
    """

    if not results:
        return "unknown", 0.2, "No search results available in the research window."

    # Concatenate titles and snippets for simple keyword counting.
    text_blob = "\n".join(
        filter(
            None,
            [
                f"{(res or {}).get('title', '')}\n{(res or {}).get('snippet', '')}"
                for res in results
            ],
        )
    )
    score = _score_sentiment(text_blob)

    if score > 0:
        return "increase", min(0.9, 0.55 + 0.1 * score), "Positive sentiment dominates fundamentals."
    if score < 0:
        return "no_increase", min(0.9, 0.55 + 0.1 * abs(score)), "Negative or cautious sentiment dominates."
    return "unknown", 0.35, "Mixed or neutral fundamentals; unable to project 30%+ gain."


def _summarize_evidence(results: List[Dict[str, Any]], limit: int = 3) -> List[Evidence]:
    trimmed = (results or [])[:limit]
    return [
        Evidence(
            title=r.get("title"),
            url=r.get("url"),
            date=r.get("date"),
            snippet=r.get("snippet"),
        )
        for r in trimmed
    ]


# ---------- Agent implementation ----------


class Agent:
    """Lightweight investing agent that relies solely on Perplexity search.

    The agent is deliberately non-LLM to keep benchmark results deterministic and
    cheap to run. It consumes a JSON payload (`AgentWorkload`) and returns a JSON
    structure (`AgentResponse`) describing its verdicts.
    """

    def __init__(self):
        self.run_id = uuid.uuid4().hex[:8]

    async def run(self, message: Message, updater: TaskUpdater) -> None:
        raw_text = get_message_text(message)

        try:
            workload = AgentWorkload.model_validate_json(raw_text)
        except ValidationError as e:
            await updater.reject(new_agent_text_message(f"Invalid request: {e}"))
            return

        logger.info(
            "INVEST AGENT - run start: run_id=%s tickers=%s target_date=%s pct=%.2f window=%s-%s",
            self.run_id,
            workload.tickers,
            workload.target_date,
            workload.target_increase_pct,
            workload.research_window.start,
            workload.research_window.end,
        )

        await updater.update_status(TaskState.working, new_agent_text_message("Running analysis"))

        decisions: List[TickerDecision] = []

        for ticker in workload.tickers:
            search_query = (
                workload.base_query.replace("{ticker}", ticker)
                if workload.base_query
                else _default_query(ticker)
            )

            search = _windowed_perplexity_search(
                query=search_query,
                window=workload.research_window,
                max_results=workload.max_results,
                max_tokens=workload.max_tokens,
                max_tokens_per_page=workload.max_tokens_per_page,
                country=workload.country,
            )

            results = search.get("results") or []
            logger.info(
                "INVEST AGENT - Ticker %s: query=%r results=%d",
                ticker,
                search_query,
                len(results),
            )
            verdict, confidence, rationale = _infer_verdict(
                results, workload.target_increase_pct
            )

            decisions.append(
                TickerDecision(
                    ticker=ticker,
                    verdict=verdict,
                    confidence=round(confidence, 3),
                    rationale=rationale,
                    evidence=_summarize_evidence(results),
                )
            )

        response = AgentResponse(
            run_id=self.run_id,
            target_date=workload.target_date,
            target_increase_pct=workload.target_increase_pct,
            decisions=decisions,
        )

        await updater.add_artifact(
            parts=[Part(root=DataPart(data=json.loads(response.model_dump_json())))],
            name="Decisions",
        )

        await updater.complete()

        logger.info(
            "INVEST AGENT - run complete: run_id=%s tickers=%s decisions=%d",
            self.run_id,
            workload.tickers,
            len(decisions),
        )
