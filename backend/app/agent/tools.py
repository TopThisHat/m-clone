import asyncio
import json
import re

import httpx
import yfinance as yf
from pydantic_ai import RunContext
from rank_bm25 import BM25Okapi

from app.agent.agent import research_agent
from app.agent.clarification import clarification_store
from app.dependencies import AgentDeps

FINANCIAL_DOMAINS = [
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com",
    "sec.gov", "investopedia.com", "marketwatch.com",
]
NOISE_DOMAINS = ["pinterest.com", "quora.com"]

# Matches numeric financial claims: $380B, 12.5%, $1,234
_CLAIM_PATTERN = re.compile(r'\$[\d,]+\.?\d*[BMTKbmtk]?|\d+\.?\d*%')


@research_agent.tool
async def ask_clarification(
    ctx: RunContext[AgentDeps],
    question: str,
    context: str | None = None,
    options: list[str] | None = None,
) -> str:
    """Ask the user a clarifying question before beginning research.

    Use ONLY when the top-level query is genuinely ambiguous in a way that changes
    the entire research direction. Call at most ONCE, as the very first action —
    before create_research_plan. Never call mid-research.

    The streaming layer intercepts this call via FunctionToolCallEvent and emits
    the clarification_needed SSE before this function body even runs.

    Args:
        question: The clarifying question to ask the user.
        context: Optional additional context or instructions for the user.
        options: Optional list of suggested answer choices.
    """
    clarification_id = ctx.deps.pending_clarification_id
    if not clarification_id:
        return "No clarification available in this context — proceed with best assumptions."

    ctx.deps.pending_clarification_id = None  # consume it

    pending = clarification_store.get_pending(clarification_id)
    if pending is None:
        return "Clarification request not found — proceed with best assumptions."

    answer = await pending.future

    if answer.startswith("__CANCELLED__:"):
        reason = answer.split(":", 1)[1]
        return f"Clarification timed out ({reason}) — proceed with best assumptions."

    return f"User clarification: {answer}"


@research_agent.tool
async def create_research_plan(
    ctx: RunContext[AgentDeps],
    topic: str,
    research_angles: list[str],
    initial_hypotheses: list[str],
    complexity: str = "standard",
) -> str:
    """Create a structured research plan before starting information gathering.

    MUST be called as the very first action for any research query.
    Defines the research angles to pursue and working hypotheses to test.

    Args:
        topic: The central research topic or question.
        research_angles: 4–6 specific sub-questions or angles to investigate.
        initial_hypotheses: Initial assumptions or hypotheses to validate or refute.
        complexity: Research depth — "simple" (1-2 tools), "standard" (4+ tools, default),
            "deep" (6+ tools, all angles before evaluation).
    """
    ctx.deps.research_plan = research_angles
    ctx.deps.query_complexity = complexity
    angles_md = "\n".join(f"{i+1}. {a}" for i, a in enumerate(research_angles))
    hypo_md = "\n".join(f"- {h}" for h in initial_hypotheses)

    if complexity == "simple":
        depth_instruction = "**Complexity: SIMPLE** — 1–2 tool calls sufficient. No formal evaluation phase required."
    elif complexity == "deep":
        depth_instruction = "**Complexity: DEEP** — 6+ tool calls required. Must cover all angles before first evaluation."
    else:
        depth_instruction = "**Complexity: STANDARD** — minimum 4 tool calls before evaluation."

    return (
        f"## Research Plan: {topic}\n\n"
        f"**Complexity:** {complexity}\n\n"
        f"### Research Angles\n{angles_md}\n\n"
        f"### Working Hypotheses\n{hypo_md}\n\n"
        f"{depth_instruction}"
    )


@research_agent.tool
async def evaluate_research_completeness(
    ctx: RunContext[AgentDeps],
    findings_summary: str,
    identified_gaps: list[str],
    confidence_pct: int,
) -> str:
    """Evaluate whether enough research has been done before writing the final report.

    Call this after completing a batch of research tool calls. The return value is a
    JSON object — parse `decision` to determine next step.

    Args:
        findings_summary: A concise summary of what has been found so far.
        identified_gaps: List of unanswered questions or missing information.
        confidence_pct: Self-assessed confidence level 0–100 that research is complete.
    """
    ctx.deps.evaluation_count += 1

    recommended_queries = identified_gaps[:3] if identified_gaps else []

    if confidence_pct >= 85 or ctx.deps.evaluation_count >= 3:
        result = {
            "decision": "SUFFICIENT",
            "evaluation_number": ctx.deps.evaluation_count,
            "confidence_pct": confidence_pct,
            "gaps": identified_gaps,
            "recommended_queries": [],
        }
    else:
        result = {
            "decision": "CONTINUE",
            "evaluation_number": ctx.deps.evaluation_count,
            "confidence_pct": confidence_pct,
            "gaps": identified_gaps,
            "recommended_queries": recommended_queries,
        }

    return json.dumps(result)


@research_agent.tool
async def web_search(ctx: RunContext[AgentDeps], query: str) -> str:
    """Search the web for current information, news, and online sources using Tavily.

    Use this to find recent news, market developments, company announcements,
    research articles, or any information that requires real-time web data.

    Args:
        query: The search query string. Be specific and include relevant context.
    """
    from tavily import AsyncTavilyClient

    cache_key = ("web_search", query.strip().lower())
    if cache_key in ctx.deps.tool_cache:
        return ctx.deps.tool_cache[cache_key]

    is_financial = any(
        kw in " ".join(ctx.deps.research_plan).lower()
        for kw in ["stock", "revenue", "earnings", "market cap", "valuation"]
    )
    kwargs: dict = {"exclude_domains": NOISE_DOMAINS}
    if is_financial:
        kwargs["include_domains"] = FINANCIAL_DOMAINS

    client = AsyncTavilyClient(api_key=ctx.deps.tavily_api_key)
    results = {}
    for attempt in range(3):
        try:
            results = await client.search(
                query=query,
                search_depth="advanced",
                max_results=5,
                **kwargs,
            )
            break
        except Exception as e:
            if attempt == 2:
                return f"Web search unavailable after 3 attempts: {e}. Use wiki_lookup or get_financials."
            await asyncio.sleep(2 ** attempt)

    items = results.get("results", [])
    if not items:
        result = f"No results found for query: '{query}'"
        ctx.deps.tool_cache[cache_key] = result
        return result

    formatted = []
    for i, item in enumerate(items, 1):
        title = item.get("title", "No title")
        url = item.get("url", "")
        content = item.get("content", "")[:400]
        score = item.get("score", 0)
        if url:
            ctx.deps.source_urls.add(url)
            ctx.deps.source_titles[url] = title
            # Extract numeric claims for conflict detection
            claims = _CLAIM_PATTERN.findall(content)
            if claims:
                ctx.deps.source_claims.setdefault(url, []).extend(claims)
        formatted.append(
            f"**{i}. {title}**\n"
            f"URL: {url}\n"
            f"Relevance: {score:.2f}\n"
            f"{content}"
        )

    result = "\n\n---\n\n".join(formatted)
    ctx.deps.tool_cache[cache_key] = result
    return result


@research_agent.tool
async def wiki_lookup(ctx: RunContext[AgentDeps], topic: str) -> str:
    """Look up a topic on Wikipedia for encyclopedic background information.

    Returns the summary and key sections of the Wikipedia article.

    Args:
        topic: The Wikipedia article title or search term to look up.
    """
    loop = asyncio.get_event_loop()

    cache_key = ("wiki_lookup", topic.strip().lower())
    if cache_key in ctx.deps.tool_cache:
        return ctx.deps.tool_cache[cache_key]

    page = await loop.run_in_executor(None, lambda: ctx.deps.wiki.page(topic))

    if not page.exists():
        return f"No Wikipedia article found for '{topic}'. Try a more specific or differently spelled term."

    sections = []
    for section in page.sections[:6]:
        if section.text and len(section.text.strip()) > 50:
            sections.append(f"### {section.title}\n{section.text[:600]}")

    result = f"# {page.title}\n\n**Summary:** {page.summary[:1000]}\n"
    if sections:
        result += "\n" + "\n\n".join(sections)
    result += f"\n\n**Source:** {page.fullurl}"

    ctx.deps.source_urls.add(page.fullurl)
    ctx.deps.tool_cache[cache_key] = result
    return result


@research_agent.tool
async def get_financials(
    ctx: RunContext[AgentDeps],
    ticker: str,
    data_type: str = "overview",
) -> str:
    """Retrieve financial market data for a publicly traded company via Yahoo Finance.

    Args:
        ticker: Stock ticker symbol (e.g. AAPL, MSFT, TSLA, NVDA).
        data_type: Type of data to retrieve. Options:
            - 'overview': Key metrics, market cap, P/E, 52-week range, analyst targets
            - 'history_1y': 1-year price history with performance summary
            - 'history_5y': 5-year price history with performance summary
            - 'income_stmt': Recent annual income statement highlights
            - 'balance_sheet': Recent annual balance sheet highlights
    """
    loop = asyncio.get_event_loop()

    def _fetch() -> str:
        t = yf.Ticker(ticker.upper())

        if data_type == "overview":
            info = t.info
            name = info.get("longName", ticker.upper())
            sector = info.get("sector", "N/A")
            industry = info.get("industry", "N/A")
            market_cap = info.get("marketCap", 0)
            market_cap_str = (
                f"${market_cap / 1e12:.2f}T"
                if market_cap >= 1e12
                else f"${market_cap / 1e9:.2f}B"
                if market_cap >= 1e9
                else f"${market_cap / 1e6:.0f}M"
            )
            return (
                f"**{name}** ({ticker.upper()})\n"
                f"- Sector: {sector} / {industry}\n"
                f"- Market Cap: {market_cap_str}\n"
                f"- Current Price: ${info.get('currentPrice', info.get('regularMarketPrice', 'N/A'))}\n"
                f"- P/E Ratio (TTM): {info.get('trailingPE', 'N/A')}\n"
                f"- Forward P/E: {info.get('forwardPE', 'N/A')}\n"
                f"- P/S Ratio: {info.get('priceToSalesTrailing12Months', 'N/A')}\n"
                f"- EPS (TTM): ${info.get('trailingEps', 'N/A')}\n"
                f"- Revenue (TTM): ${info.get('totalRevenue', 0) / 1e9:.1f}B\n"
                f"- Gross Margin: {info.get('grossMargins', 0) * 100:.1f}%\n"
                f"- 52W High: ${info.get('fiftyTwoWeekHigh', 'N/A')}\n"
                f"- 52W Low: ${info.get('fiftyTwoWeekLow', 'N/A')}\n"
                f"- Analyst Mean Target: ${info.get('targetMeanPrice', 'N/A')}\n"
                f"- Analyst Recommendation: {info.get('recommendationKey', 'N/A').replace('_', ' ').title()}\n"
                f"\n**Business:** {info.get('longBusinessSummary', 'N/A')[:500]}"
            )

        elif data_type in ("history_1y", "history_5y"):
            period = "1y" if data_type == "history_1y" else "5y"
            hist = t.history(period=period)
            if hist.empty:
                return f"No price history available for {ticker.upper()}."
            first_price = hist["Close"].iloc[0]
            last_price = hist["Close"].iloc[-1]
            pct_change = ((last_price - first_price) / first_price) * 100
            max_price = hist["High"].max()
            min_price = hist["Low"].min()
            avg_volume = hist["Volume"].mean()

            # Build chart payload
            chart = {
                "ticker": ticker.upper(),
                "period": period,
                "type": "price_history",
                "labels": [str(d.date()) for d in hist.index],
                "values": [round(float(v), 2) for v in hist["Close"].tolist()],
                "pct_change": round(float(pct_change), 2),
            }
            ctx.deps.chart_payloads.append(chart)

            return (
                f"**{ticker.upper()} Price History ({period.upper()})**\n"
                f"- Period Start: ${first_price:.2f}\n"
                f"- Period End: ${last_price:.2f}\n"
                f"- Total Return: {pct_change:+.1f}%\n"
                f"- Period High: ${max_price:.2f}\n"
                f"- Period Low: ${min_price:.2f}\n"
                f"- Avg Daily Volume: {avg_volume:,.0f} shares"
            )

        elif data_type == "income_stmt":
            income = t.income_stmt
            if income is None or income.empty:
                return f"Income statement data not available for {ticker.upper()}."
            latest = income.iloc[:, 0]
            col_name = str(income.columns[0])[:10]
            revenue = latest.get("Total Revenue", 0)
            gross = latest.get("Gross Profit", 0)
            operating = latest.get("Operating Income", 0)
            net = latest.get("Net Income", 0)
            return (
                f"**{ticker.upper()} Income Statement ({col_name})**\n"
                f"- Total Revenue: ${revenue / 1e9:.2f}B\n"
                f"- Gross Profit: ${gross / 1e9:.2f}B (margin: {gross/revenue*100:.1f}%)\n"
                f"- Operating Income: ${operating / 1e9:.2f}B\n"
                f"- Net Income: ${net / 1e9:.2f}B"
            )

        elif data_type == "balance_sheet":
            bs = t.balance_sheet
            if bs is None or bs.empty:
                return f"Balance sheet data not available for {ticker.upper()}."
            latest = bs.iloc[:, 0]
            col_name = str(bs.columns[0])[:10]
            total_assets = latest.get("Total Assets", 0)
            total_liab = latest.get("Total Liabilities Net Minority Interest", 0)
            equity = latest.get("Stockholders Equity", 0)
            cash = latest.get("Cash And Cash Equivalents", 0)
            debt = latest.get("Long Term Debt", 0)
            return (
                f"**{ticker.upper()} Balance Sheet ({col_name})**\n"
                f"- Total Assets: ${total_assets / 1e9:.2f}B\n"
                f"- Total Liabilities: ${total_liab / 1e9:.2f}B\n"
                f"- Stockholders Equity: ${equity / 1e9:.2f}B\n"
                f"- Cash & Equivalents: ${cash / 1e9:.2f}B\n"
                f"- Long-Term Debt: ${debt / 1e9:.2f}B"
            )

        return f"Unknown data_type '{data_type}'. Use: overview, history_1y, history_5y, income_stmt, balance_sheet."

    return await loop.run_in_executor(None, _fetch)


@research_agent.tool
async def sec_edgar_search(
    ctx: RunContext[AgentDeps],
    query: str,
    form_type: str = "",
) -> str:
    """Search SEC EDGAR full-text search for public company filings.

    Args:
        query: Company name, ticker, or topic to search for.
        form_type: Optional — "10-K", "10-Q", "8-K". Empty = all forms.
    """
    cache_key = ("sec_edgar_search", query.strip().lower(), form_type.strip().upper())
    if cache_key in ctx.deps.tool_cache:
        return ctx.deps.tool_cache[cache_key]

    params: dict = {"q": query, "dateRange": "custom", "startdt": "2020-01-01"}
    if form_type:
        params["forms"] = form_type.upper()

    url = "https://efts.sec.gov/LATEST/search-index"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://efts.sec.gov/LATEST/search-index",
                params={"q": f'"{query}"', "forms": form_type or "10-K,10-Q,8-K"},
                headers={"User-Agent": "m-clone-research-agent research@example.com"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return f"SEC EDGAR search failed: {exc}"

    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        # Fall back to the EDGAR full-text search API
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp2 = await client.get(
                    "https://efts.sec.gov/LATEST/search-index",
                    params={"q": query, "forms": form_type or ""},
                    headers={"User-Agent": "m-clone-research-agent research@example.com"},
                )
                resp2.raise_for_status()
                data = resp2.json()
                hits = data.get("hits", {}).get("hits", [])
        except Exception:
            pass

    if not hits:
        result = f"No SEC filings found for query: '{query}'"
        ctx.deps.tool_cache[cache_key] = result
        return result

    formatted = []
    for hit in hits[:5]:
        src = hit.get("_source", {})
        company = src.get("entity_name", "Unknown")
        form = src.get("file_type", "")
        filed = src.get("file_date", "")
        doc_id = src.get("accession_no", "").replace("-", "")
        filing_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&filenum={src.get('accession_no', '')}"
        description = src.get("period_of_report", "")
        formatted.append(
            f"**{company}** — {form} ({filed})\n"
            f"Period: {description}\n"
            f"URL: {filing_url}"
        )
        ctx.deps.source_urls.add(filing_url)

    result = "\n\n---\n\n".join(formatted)
    ctx.deps.tool_cache[cache_key] = result
    return result


@research_agent.tool
async def search_uploaded_documents(ctx: RunContext[AgentDeps], query: str) -> str:
    """Search through text extracted from PDFs that the user uploaded.

    Returns relevant passages from the uploaded documents that match the query.
    Use this to cross-reference client-provided materials like annual reports,
    research papers, or regulatory filings.

    Args:
        query: Keywords or a question to search for in the uploaded documents.
    """
    if not ctx.deps.pdf_context:
        return "No documents have been uploaded for this research session."

    chunks = [c.strip() for c in ctx.deps.pdf_context.split("\n\n") if c.strip()]
    if not chunks:
        return f"No relevant passages found in uploaded documents for: '{query}'"

    bm25 = BM25Okapi([c.lower().split() for c in chunks])
    scores = bm25.get_scores(query.lower().split())
    top_indices = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)[:5]
    relevant = [chunks[i] for i in top_indices if scores[i] > 0]

    if not relevant:
        return f"No relevant passages found in uploaded documents for: '{query}'"

    result = "\n\n---\n\n".join(relevant)
    filenames = ", ".join(ctx.deps.uploaded_filenames) if ctx.deps.uploaded_filenames else "uploaded document"
    return f"**From {filenames}:**\n\n{result}"
