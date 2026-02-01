# Invest Benchmark Scenario

This scenario tests an agent that uses Perplexity search to decide whether a ticker is likely to rise by **30% or more by a target date**. The agent only looks at fundamentals published between **June 1, 2025** and **September 30, 2025**. The evaluator reruns a December 2025 fact-check to judge the agent’s call.

## Setup

1. Install dependencies:
   ```bash
   uv sync
   ```

2. Set your API key in `.env`:
   ```
   PERPLEXITY_API_KEY=your-key-here
   ```


## Run

Start evaluator (green) and agent (purple) services automatically via the scenario:
```bash
uv run agentbeats-run scenarios/invest/scenario.toml
```

## Configuration (`scenario.toml`)

Key fields under `[config]`:
- `tickers`: list of tickers to evaluate (default `["RR"]`)
- `target_date`: date we care about (MM/DD/YYYY)
- `target_increase_pct`: required lift as a decimal (0.30 = 30%)
- `research_window`: date window the agent must use for fundamentals (default Jun–Sep 2025)
- `verify_window`: date window the evaluator uses to fact-check (default Dec 2025)

Agent/evaluator endpoints and commands are defined under `[green_agent]` and `[[participants]]`.
