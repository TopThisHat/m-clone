import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Coroutine

import httpx
import yfinance as yf
from rank_bm25 import BM25Okapi

from app.agent.clarification import clarification_store
from app.dependencies import AgentDeps

FINANCIAL_DOMAINS = [
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com",
    "sec.gov", "investopedia.com", "marketwatch.com",
]
NOISE_DOMAINS = ["pinterest.com", "quora.com"]

# Matches numeric financial claims: $380B, 12.5%, $1,234
_CLAIM_PATTERN = re.compile(r'\$[\d,]+\.?\d*[BMTKbmtk]?|\d+\.?\d*%')


# ── Tool registry ────────────────────────────────────────────────────────────

@dataclass
class ToolDef:
    func: Callable[..., Coroutine]
    schema: dict[str, Any]


TOOL_REGISTRY: dict[str, ToolDef] = {}


def _register(name: str, description: str, parameters: dict[str, Any]):
    """Decorator: register a tool function with its OpenAI function-calling schema."""
    def decorator(fn: Callable[..., Coroutine]):
        TOOL_REGISTRY[name] = ToolDef(
            func=fn,
            schema={
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            },
        )
        return fn
    return decorator


def get_openai_tools() -> list[dict[str, Any]]:
    """Return the list of tool schemas for OpenAI chat completions."""
    return [td.schema for td in TOOL_REGISTRY.values()]


async def execute_tool(name: str, args: dict[str, Any], deps: AgentDeps) -> str:
    """Look up and execute a registered tool by name."""
    tool_def = TOOL_REGISTRY.get(name)
    if tool_def is None:
        return f"Unknown tool: {name}"
    return await tool_def.func(deps=deps, **args)


# ── Tool implementations ─────────────────────────────────────────────────────

@_register(
    "ask_clarification",
    "Ask the user a clarifying question before beginning research. "
    "Use ONLY when the top-level query is genuinely ambiguous in a way that changes "
    "the entire research direction. Call at most ONCE, as the very first action — "
    "before create_research_plan. Never call mid-research.",
    {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The clarifying question to ask the user."},
            "context": {"type": "string", "description": "Optional additional context or instructions for the user."},
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of suggested answer choices.",
            },
        },
        "required": ["question"],
    },
)
async def ask_clarification(
    deps: AgentDeps,
    question: str,
    context: str | None = None,
    options: list[str] | None = None,
) -> str:
    """Ask the user a clarifying question before beginning research."""
    clarification_id = deps.pending_clarification_id
    if not clarification_id:
        return "No clarification available in this context — proceed with best assumptions."

    deps.pending_clarification_id = None  # consume it

    pending = clarification_store.get_pending(clarification_id)
    if pending is None:
        return "Clarification request not found — proceed with best assumptions."

    answer = await pending.future

    if answer.startswith("__CANCELLED__:"):
        reason = answer.split(":", 1)[1]
        return f"Clarification timed out ({reason}) — proceed with best assumptions."

    return f"User clarification: {answer}"


@_register(
    "create_research_plan",
    "Create a structured research plan before starting information gathering. "
    "MUST be called as the very first action for any research query.",
    {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "The central research topic or question."},
            "research_angles": {
                "type": "array",
                "items": {"type": "string"},
                "description": "4-6 specific sub-questions or angles to investigate.",
            },
            "initial_hypotheses": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Initial assumptions or hypotheses to validate or refute.",
            },
            "complexity": {
                "type": "string",
                "enum": ["simple", "standard", "deep"],
                "description": "Research depth.",
            },
        },
        "required": ["topic", "research_angles", "initial_hypotheses"],
    },
)
async def create_research_plan(
    deps: AgentDeps,
    topic: str,
    research_angles: list[str],
    initial_hypotheses: list[str],
    complexity: str = "standard",
) -> str:
    deps.research_plan = research_angles
    deps.query_complexity = complexity
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


@_register(
    "evaluate_research_completeness",
    "Evaluate whether enough research has been done before writing the final report. "
    "Call this after completing a batch of research tool calls.",
    {
        "type": "object",
        "properties": {
            "findings_summary": {"type": "string", "description": "A concise summary of what has been found so far."},
            "identified_gaps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of unanswered questions or missing information.",
            },
            "confidence_pct": {
                "type": "integer",
                "description": "Self-assessed confidence level 0-100 that research is complete.",
            },
            "items_found": {
                "type": "integer",
                "description": "For comprehensive list queries: count of unique items found so far. Use 0 if not a list query.",
            },
        },
        "required": ["findings_summary", "identified_gaps", "confidence_pct"],
    },
)
async def evaluate_research_completeness(
    deps: AgentDeps,
    findings_summary: str,
    identified_gaps: list[str],
    confidence_pct: int,
    items_found: int = 0,
) -> str:
    deps.evaluation_count += 1
    deps.progress_history.append(items_found)

    recommended_queries = identified_gaps[:3] if identified_gaps else []

    # Comprehensive/deep queries get more evaluation rounds
    max_evals = 5 if deps.query_complexity == "deep" else 3

    # Detect stalled progress: same items_found for last 2 evaluations
    progress_stalled = (
        len(deps.progress_history) >= 2
        and items_found > 0
        and deps.progress_history[-1] == deps.progress_history[-2]
    )

    # SUFFICIENT when: confident enough, hit max evals, OR progress stalled
    if confidence_pct >= 85 or deps.evaluation_count >= max_evals or progress_stalled:
        result = {
            "decision": "SUFFICIENT",
            "evaluation_number": deps.evaluation_count,
            "max_evaluations": max_evals,
            "confidence_pct": confidence_pct,
            "items_found": items_found,
            "progress_stalled": progress_stalled,
            "gaps": identified_gaps,
            "recommended_queries": [],
        }
    else:
        result = {
            "decision": "CONTINUE",
            "evaluation_number": deps.evaluation_count,
            "max_evaluations": max_evals,
            "confidence_pct": confidence_pct,
            "items_found": items_found,
            "gaps": identified_gaps,
            "recommended_queries": recommended_queries,
        }

    return json.dumps(result)


@_register(
    "web_search",
    "Search the web for current information, news, and online sources using Tavily.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query string. Be specific and include relevant context."},
        },
        "required": ["query"],
    },
)
async def web_search(deps: AgentDeps, query: str) -> str:
    from tavily import AsyncTavilyClient

    cache_key = ("web_search", query.strip().lower())
    if cache_key in deps.tool_cache:
        return deps.tool_cache[cache_key]

    is_financial = any(
        kw in " ".join(deps.research_plan).lower()
        for kw in ["stock", "revenue", "earnings", "market cap", "valuation"]
    )
    kwargs: dict = {"exclude_domains": NOISE_DOMAINS}
    if is_financial:
        kwargs["include_domains"] = FINANCIAL_DOMAINS

    client = AsyncTavilyClient(api_key=deps.tavily_api_key)
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
        deps.tool_cache[cache_key] = result
        return result

    formatted = []
    for i, item in enumerate(items, 1):
        title = item.get("title", "No title")
        url = item.get("url", "")
        content = item.get("content", "")[:400]
        score = item.get("score", 0)
        if url:
            deps.source_urls.add(url)
            deps.source_titles[url] = title
            claims = _CLAIM_PATTERN.findall(content)
            if claims:
                deps.source_claims.setdefault(url, []).extend(claims)
        formatted.append(
            f"**{i}. {title}**\n"
            f"URL: {url}\n"
            f"Relevance: {score:.2f}\n"
            f"{content}"
        )

    result = "\n\n---\n\n".join(formatted)
    deps.tool_cache[cache_key] = result
    return result


@_register(
    "wiki_lookup",
    "Look up a topic on Wikipedia for encyclopedic background information.",
    {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "The Wikipedia article title or search term to look up."},
        },
        "required": ["topic"],
    },
)
async def wiki_lookup(deps: AgentDeps, topic: str) -> str:
    loop = asyncio.get_running_loop()

    cache_key = ("wiki_lookup", topic.strip().lower())
    if cache_key in deps.tool_cache:
        return deps.tool_cache[cache_key]

    page = await loop.run_in_executor(None, lambda: deps.wiki.page(topic))

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

    deps.source_urls.add(page.fullurl)
    deps.tool_cache[cache_key] = result
    return result


@_register(
    "get_financials",
    "Retrieve financial market data for a publicly traded company via Yahoo Finance.",
    {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Stock ticker symbol (e.g. AAPL, MSFT, TSLA, NVDA)."},
            "data_type": {
                "type": "string",
                "enum": ["overview", "history_1y", "history_5y", "income_stmt", "balance_sheet"],
                "description": "Type of data to retrieve.",
            },
        },
        "required": ["ticker"],
    },
)
async def get_financials(
    deps: AgentDeps,
    ticker: str,
    data_type: str = "overview",
) -> str:
    loop = asyncio.get_running_loop()

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

            chart = {
                "ticker": ticker.upper(),
                "period": period,
                "type": "price_history",
                "labels": [str(d.date()) for d in hist.index],
                "values": [round(float(v), 2) for v in hist["Close"].tolist()],
                "pct_change": round(float(pct_change), 2),
            }
            deps.chart_payloads.append(chart)

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


@_register(
    "sec_edgar_search",
    "Search SEC EDGAR full-text search for public company filings.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Company name, ticker, or topic to search for."},
            "form_type": {
                "type": "string",
                "description": 'Optional — "10-K", "10-Q", "8-K". Empty = all forms.',
            },
        },
        "required": ["query"],
    },
)
async def sec_edgar_search(
    deps: AgentDeps,
    query: str,
    form_type: str = "",
) -> str:
    cache_key = ("sec_edgar_search", query.strip().lower(), form_type.strip().upper())
    if cache_key in deps.tool_cache:
        return deps.tool_cache[cache_key]

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
        deps.tool_cache[cache_key] = result
        return result

    formatted = []
    for hit in hits[:5]:
        src = hit.get("_source", {})
        company = src.get("entity_name", "Unknown")
        form = src.get("file_type", "")
        filed = src.get("file_date", "")
        filing_url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&filenum={src.get('accession_no', '')}"
        description = src.get("period_of_report", "")
        formatted.append(
            f"**{company}** — {form} ({filed})\n"
            f"Period: {description}\n"
            f"URL: {filing_url}"
        )
        deps.source_urls.add(filing_url)

    result = "\n\n---\n\n".join(formatted)
    deps.tool_cache[cache_key] = result
    return result


@_register(
    "search_uploaded_documents",
    "Search through text extracted from documents the user uploaded (PDF, DOCX, Excel, CSV, images, etc.). "
    "Use the optional 'filename' parameter to restrict search to a specific file when the user "
    "references a particular document by name or type.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keywords or a question to search for in the uploaded documents."},
            "filename": {
                "type": "string",
                "description": "Optional exact filename to restrict search to (e.g. 'sports.csv'). "
                "Use when the user references a specific file.",
            },
        },
        "required": ["query"],
    },
)
async def search_uploaded_documents(deps: AgentDeps, query: str, filename: str | None = None) -> str:
    _RESPONSE_CAP = 15_000

    if not deps.doc_context and not deps.doc_texts:
        return "No documents have been uploaded for this research session."

    # Try chunk-based search when doc_texts is available
    if deps.doc_texts and deps.uploaded_doc_metadata:
        cache_key = "chunked_docs"
        if cache_key in deps.tool_cache:
            chunk_dicts = deps.tool_cache[cache_key]
        else:
            from app.document_chunking import chunk_session
            chunk_dicts = chunk_session(deps.doc_texts, deps.uploaded_doc_metadata)
            deps.tool_cache[cache_key] = chunk_dicts

        if not chunk_dicts:
            return f"No relevant passages found in uploaded documents for: '{query}'"

        # Filter to a specific file when filename is provided
        if filename:
            target = filename.lower()
            chunk_dicts = [c for c in chunk_dicts if c.get("filename", "").lower() == target]
            if not chunk_dicts:
                return f"No document found with filename '{filename}'."

        chunk_texts = [c["text"] for c in chunk_dicts]

        # Short-circuit: if <=3 chunks, return them all
        if len(chunk_texts) <= 3:
            formatted = []
            for c in chunk_dicts:
                label = _chunk_label(c)
                formatted.append(f"{label}\n{c['text']}")
            result = "\n\n---\n\n".join(formatted)
            return result[:_RESPONSE_CAP]

        # BM25 search over chunks (cache only when not filename-filtered)
        bm25_key = f"chunked_bm25:{filename or ''}"
        if bm25_key in deps.tool_cache:
            bm25 = deps.tool_cache[bm25_key]
        else:
            bm25 = BM25Okapi([t.lower().split() for t in chunk_texts])
            deps.tool_cache[bm25_key] = bm25

        scores = bm25.get_scores(query.lower().split())
        top_indices = sorted(range(len(chunk_texts)), key=lambda i: scores[i], reverse=True)[:5]
        relevant = [(chunk_dicts[i], scores[i]) for i in top_indices if scores[i] > 0]

        if not relevant:
            return f"No relevant passages found in uploaded documents for: '{query}'"

        formatted = []
        for c, _score in relevant:
            label = _chunk_label(c)
            formatted.append(f"{label}\n{c['text']}")
        result = "\n\n---\n\n".join(formatted)
        return result[:_RESPONSE_CAP]

    # Fallback: old doc_context.split approach
    chunks = [c.strip() for c in deps.doc_context.split("\n\n") if c.strip()]
    if not chunks:
        return f"No relevant passages found in uploaded documents for: '{query}'"

    bm25 = BM25Okapi([c.lower().split() for c in chunks])
    scores = bm25.get_scores(query.lower().split())
    top_indices = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)[:5]
    relevant = [chunks[i] for i in top_indices if scores[i] > 0]

    if not relevant:
        return f"No relevant passages found in uploaded documents for: '{query}'"

    result = "\n\n---\n\n".join(relevant)
    filenames = ", ".join(deps.uploaded_filenames) if deps.uploaded_filenames else "uploaded document"
    return f"**From {filenames}:**\n\n{result}"[:_RESPONSE_CAP]


def _chunk_label(chunk: dict) -> str:
    """Build a human-readable attribution label for a chunk."""
    filename = chunk.get("filename", "document")
    page = chunk.get("page")
    if isinstance(page, int) and page > 0:
        return f"**[{filename}, Page {page}]**"
    if isinstance(page, str):
        return f"**[{filename}, {page}]**"
    return f"**[{filename}]**"


@_register(
    "lookup_client",
    "Look up a client's GWM ID by name. Searches the client directory and priority queue "
    "using fuzzy matching, then resolves the best match using LLM adjudication.",
    {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The client name to look up (e.g. 'John Smith').",
            },
            "company": {
                "type": "string",
                "description": "Optional company name for disambiguation (e.g. 'Goldman Sachs').",
            },
        },
        "required": ["name"],
    },
)
async def lookup_client(deps: AgentDeps, name: str, company: str | None = None) -> str:
    from app.agent.client_resolver import resolve_client
    result = await resolve_client(name=name, company=company)
    lines = []
    if result.match_found:
        lines.append(f"**Match Found:** {result.matched_name}")
        lines.append(f"- GWM ID: {result.gwm_id}")
        lines.append(f"- Source: {result.source}")
        lines.append(f"- Confidence: {result.confidence:.0%}")
        lines.append(f"- Method: {result.adjudication.value}")
    else:
        lines.append("**No match found.**")
        if result.ambiguous:
            lines.append("Multiple potential matches — provide company or additional context.")
        if result.conflict:
            lines.append("Conflicting GWM IDs detected — manual verification needed.")

    if result.candidates:
        lines.append("\n**Candidates:**")
        for c in result.candidates[:5]:
            lines.append(f"- {c.name} (gwm_id: {c.gwm_id}, source: {c.source}, score: {c.db_score:.2f})")

    if result.resolution_factors:
        lines.append("\n**Resolution Factors:**")
        for f in result.resolution_factors:
            lines.append(f"- {f}")

    if result.warnings:
        lines.append("\n**Warnings:**")
        for w in result.warnings:
            lines.append(f"- {w}")

    return "\n".join(lines)


@_register(
    "query_knowledge_graph",
    "Search the internal knowledge graph for entities and relationships. "
    "Use this to answer questions about known people, companies, deals, and relationships. "
    "Searches both the master graph and the user's team graph, and reports which source "
    "provided each result.",
    {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The entity name, keyword, or question to search the knowledge graph for.",
            },
        },
        "required": ["query"],
    },
)
async def query_knowledge_graph(deps: AgentDeps, query: str) -> str:
    """Search the knowledge graph for entities and their relationships."""
    try:
        from app.db import db_query_kg

        team_ids = getattr(deps, "team_ids", [])
        include_master = getattr(deps, "include_master", False)

        if not team_ids and not include_master:
            return "No knowledge graph available — join a team or select one in Scout to search team graphs."

        # Query each team graph and merge results with deduplication
        all_entities: dict[str, dict] = {}
        all_rels: dict[str, dict] = {}
        sources_used: set[str] = set()

        if not team_ids and include_master:
            # Super admin with no teams — search master only
            r = await db_query_kg(query, team_id=None, include_master=True)
            for e in r["entities"]:
                all_entities[e["id"]] = e
            for rel in r["relationships"]:
                all_rels[rel["id"]] = rel
            sources_used.update(r["sources_used"])
        else:
            for i, tid in enumerate(team_ids):
                r = await db_query_kg(query, team_id=tid, include_master=(include_master and i == 0))
                for e in r["entities"]:
                    all_entities[e["id"]] = e
                for rel in r["relationships"]:
                    all_rels[rel["id"]] = rel
                sources_used.update(r["sources_used"])

        entities = list(all_entities.values())
        relationships = list(all_rels.values())

        if not entities and not relationships:
            return f"No knowledge graph results found for: '{query}'"

        sources_str = ", ".join(sources_used) if sources_used else "none"
        parts = [f"**Knowledge Graph Results** (sources: {sources_str})\n"]

        if entities:
            parts.append("### Entities Found")
            for e in entities[:10]:
                aliases = f" (aka: {', '.join(e.get('aliases', [])[:3])})" if e.get("aliases") else ""
                desc = f" — {e['description']}" if e.get("description") else ""
                team_tag = e.get("team_id", "")
                if e.get("graph_source") == "master":
                    source_tag = " [master]"
                elif team_tag:
                    source_tag = f" [team:{str(team_tag)[:8]}]"
                else:
                    source_tag = f" [{e.get('graph_source', 'unknown')}]"
                parts.append(f"- **{e['name']}** ({e.get('entity_type', 'unknown')}){aliases}{desc}{source_tag}")

        if relationships:
            parts.append("\n### Relationships")
            for r in relationships[:15]:
                team_tag = r.get("team_id", "")
                if r.get("graph_source") == "master":
                    source_tag = " [master]"
                elif team_tag:
                    source_tag = f" [team:{str(team_tag)[:8]}]"
                else:
                    source_tag = f" [{r.get('graph_source', 'unknown')}]"
                conf = f" ({int(r.get('confidence', 1) * 100)}%)" if r.get("confidence", 1) < 1 else ""
                parts.append(
                    f"- {r.get('subject_name', '?')} **{r.get('predicate', '?')}** "
                    f"{r.get('object_name', '?')}{conf}{source_tag}"
                )

        return "\n".join(parts)
    except Exception as exc:
        return f"Knowledge graph query failed: {exc}"
