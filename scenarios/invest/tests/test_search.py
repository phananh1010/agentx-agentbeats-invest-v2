# requires: pip install perplexity
# requires: .env with PERPLEXITY_API_KEY

import sys
from pathlib import Path

# Allow running this file directly without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scenarios.invest.utils.search import perplexity_search

QUERY = "what is fundamental of RR ticker"
DATE_AFTER = "06/01/2025"   # %m/%d/%Y
DATE_BEFORE = "09/30/2025"  # %m/%d/%Y

search = perplexity_search(
    query=QUERY,
    max_results=20,
    max_tokens=12_500,
    max_tokens_per_page=2048,
    search_after_date_filter=DATE_AFTER,
    search_before_date_filter=DATE_BEFORE,
)

for r in search.get("results", []) or []:
    print("-" * 80)
    #print("title:", r.get("title"))
    print("url:", r.get("url"))
    print("date:", r.get("date"))
    print("last_updated:", r.get("last_updated"))
    #print("snippet:", r.get("snippet"))
