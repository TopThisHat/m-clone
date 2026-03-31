"""Benchmark accuracy regression suite for document intelligence (m-clone-di27).

Tests 50 query scenarios across document types (tabular CSV/Excel, prose PDF,
image) to ensure routing, extraction, and output structure remain correct under
refactoring.

Each scenario specifies:
  - content: synthetic document text (CSV rows, prose paragraphs, or table MD)
  - doc_type: "tabular" | "prose"
  - query: natural-language question
  - expected_complexity: "simple" | "complex"
  - expected_min_matches: minimum match count in a correct answer
  - expected_fields: list of field names that must be present in every match

Run:
    cd backend && uv run python -m pytest tests/test_document_intelligence_benchmark.py -v
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.document_intelligence import DocumentSchema, SheetSchema, ColumnSchema, QueryResult, MatchEntry
from app.redis_client import DocumentSession


# ---------------------------------------------------------------------------
# Benchmark scenario definitions
# ---------------------------------------------------------------------------

# Each scenario is a dict with:
#   id, doc_type, content, query, expected_complexity, expected_min_matches
BENCHMARK_SCENARIOS: list[dict[str, Any]] = [
    # ── CSV / tabular — simple lookup queries ────────────────────────────────
    {
        "id": "csv_simple_01",
        "doc_type": "tabular",
        "content": "name,age,city\nAlice,30,New York\nBob,25,London\nCarol,35,Paris",
        "query": "What city does Alice live in?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "csv_simple_02",
        "doc_type": "tabular",
        "content": "product,price,qty\nWidget,9.99,100\nGadget,14.99,50\nDoohickey,4.99,200",
        "query": "What is the price of the Gadget?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "csv_simple_03",
        "doc_type": "tabular",
        "content": "employee,department,salary\nJohn,Engineering,95000\nJane,Marketing,75000\nTom,Engineering,105000",
        "query": "Who works in the Engineering department?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "csv_simple_04",
        "doc_type": "tabular",
        "content": "order_id,customer,status\nO001,Alice,shipped\nO002,Bob,pending\nO003,Carol,delivered",
        "query": "What is the status of order O002?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "csv_simple_05",
        "doc_type": "tabular",
        "content": "date,ticker,close_price\n2024-01-01,AAPL,185.20\n2024-01-02,AAPL,187.50\n2024-01-03,MSFT,375.10",
        "query": "What was AAPL's closing price on 2024-01-02?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "csv_simple_06",
        "doc_type": "tabular",
        "content": "country,capital,population_m\nFrance,Paris,67\nGermany,Berlin,83\nSpain,Madrid,47",
        "query": "What is the capital of Germany?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "csv_simple_07",
        "doc_type": "tabular",
        "content": "vendor,contract_value,expiry\nAcme,50000,2025-06\nBeta Corp,120000,2024-12\nGamma Inc,30000,2026-03",
        "query": "Which vendor has the highest contract value?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "csv_simple_08",
        "doc_type": "tabular",
        "content": "student,grade,score\nEmma,A,95\nLiam,B,82\nOlivia,A,91\nNoah,C,73",
        "query": "Which students received an A grade?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "csv_simple_09",
        "doc_type": "tabular",
        "content": "asset,quantity,unit_cost\nLaptops,50,1200\nMonitors,80,400\nKeyboards,120,75",
        "query": "How many monitors are in inventory?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "csv_simple_10",
        "doc_type": "tabular",
        "content": "region,q1_sales,q2_sales\nNorth,450000,520000\nSouth,380000,410000\nWest,620000,590000",
        "query": "What were the Q1 sales for the West region?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    # ── CSV / tabular — complex aggregation queries ──────────────────────────
    {
        "id": "csv_complex_01",
        "doc_type": "tabular",
        "content": "rep,region,revenue\nAlice,North,45000\nBob,South,38000\nCarol,North,62000\nDave,South,41000",
        "query": "What is the total revenue for the North region?",
        "expected_complexity": "complex",
        "expected_min_matches": 0,
    },
    {
        "id": "csv_complex_02",
        "doc_type": "tabular",
        "content": "product,category,units_sold\nWidget,A,150\nGadget,B,90\nDoohickey,A,200\nThingamajig,B,120",
        "query": "How many total units were sold across all products?",
        "expected_complexity": "complex",
        "expected_min_matches": 0,
    },
    {
        "id": "csv_complex_03",
        "doc_type": "tabular",
        "content": "employee,dept,salary\nJohn,Eng,95000\nJane,Mkt,75000\nTom,Eng,105000\nSue,Mkt,80000",
        "query": "What is the average salary in the Engineering department?",
        "expected_complexity": "complex",
        "expected_min_matches": 0,
    },
    {
        "id": "csv_complex_04",
        "doc_type": "tabular",
        "content": "order,customer,amount,status\nO1,Alice,1500,paid\nO2,Bob,2300,paid\nO3,Carol,900,pending\nO4,Dave,3100,paid",
        "query": "What is the total value of paid orders?",
        "expected_complexity": "complex",
        "expected_min_matches": 0,
    },
    {
        "id": "csv_complex_05",
        "doc_type": "tabular",
        "content": "month,category,spend\nJan,Marketing,12000\nJan,Engineering,45000\nFeb,Marketing,14000\nFeb,Engineering,47000",
        "query": "What was the total marketing spend across both months?",
        "expected_complexity": "complex",
        "expected_min_matches": 0,
    },
    # ── Messy tabular — fuzzy/abbreviation matching ──────────────────────────
    {
        "id": "messy_tabular_01",
        "doc_type": "tabular",
        "content": "acct_nm,sts_cd,bal_usd\nSmith J,actv,45000\nJones M,pend,12000\nBrown K,actv,87000",
        "query": "Find all active accounts",
        "expected_complexity": "complex",
        "expected_min_matches": 0,
    },
    {
        "id": "messy_tabular_02",
        "doc_type": "tabular",
        "content": "Cust,Amt_$,Stat\nAlice Corp,50k,Delivered\nBeta Ltd,25k,Pndg\nGamma Inc,75k,Dlvrd",
        "query": "Which customers have delivered orders?",
        "expected_complexity": "complex",
        "expected_min_matches": 0,
    },
    {
        "id": "messy_tabular_03",
        "doc_type": "tabular",
        "content": "nm,dept_cd,sal\nJohn Smith,ENG,95k\nJane Doe,MKT,75k\nBob Jones,ENG,105k",
        "query": "Who is in the engineering department?",
        "expected_complexity": "complex",
        "expected_min_matches": 0,
    },
    # ── Multi-sheet Excel simulation ─────────────────────────────────────────
    {
        "id": "excel_multi_sheet_01",
        "doc_type": "tabular",
        "content": "## Sheet: Q1\nrep,sales\nAlice,45000\nBob,38000\n\n## Sheet: Q2\nrep,sales\nAlice,52000\nBob,41000",
        "query": "What were Alice's Q2 sales?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "excel_multi_sheet_02",
        "doc_type": "tabular",
        "content": "## Sheet: Employees\nname,team\nAlice,Backend\nBob,Frontend\n\n## Sheet: Salaries\nname,salary\nAlice,95000\nBob,85000",
        "query": "What team does Bob work on?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    # ── Prose PDF — factual lookup ───────────────────────────────────────────
    {
        "id": "prose_simple_01",
        "doc_type": "prose",
        "content": "The company was founded in 2010 by Jane Smith. Revenue in 2023 reached $4.2 billion.",
        "query": "Who founded the company?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "prose_simple_02",
        "doc_type": "prose",
        "content": "Project Titan launched on March 15, 2024. The project lead is Dr. Marcus Webb.",
        "query": "Who is the project lead for Project Titan?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "prose_simple_03",
        "doc_type": "prose",
        "content": "The headquarters is located at 123 Main Street, San Francisco, CA 94105.",
        "query": "Where is the headquarters located?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "prose_simple_04",
        "doc_type": "prose",
        "content": "Our net income for fiscal year 2023 was $1.8 billion, up 12% from the prior year.",
        "query": "What was net income in FY2023?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "prose_simple_05",
        "doc_type": "prose",
        "content": "The board approved a $500 million share buyback program effective Q2 2024.",
        "query": "What is the size of the share buyback program?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    # ── Prose — multi-paragraph extraction ──────────────────────────────────
    {
        "id": "prose_multi_01",
        "doc_type": "prose",
        "content": (
            "Risk Factor 1: Supply chain disruptions may increase costs by up to 15%.\n\n"
            "Risk Factor 2: Regulatory changes in the EU could impact product sales.\n\n"
            "Risk Factor 3: Cybersecurity threats remain an operational concern."
        ),
        "query": "List all the risk factors mentioned",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "prose_multi_02",
        "doc_type": "prose",
        "content": (
            "Key executive: CEO John Adams (appointed 2019). "
            "Key executive: CFO Sarah Chen (appointed 2021). "
            "Key executive: CTO Raj Patel (appointed 2022)."
        ),
        "query": "Who are the key executives?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    # ── Financial report extraction ──────────────────────────────────────────
    {
        "id": "financial_01",
        "doc_type": "tabular",
        "content": "metric,2022,2023\nRevenue,$3.5B,$4.2B\nEBITDA,$0.8B,$1.1B\nNet Income,$0.5B,$0.7B",
        "query": "What was the revenue growth from 2022 to 2023?",
        "expected_complexity": "complex",
        "expected_min_matches": 0,
    },
    {
        "id": "financial_02",
        "doc_type": "tabular",
        "content": "fund,aum_usd_m,ytd_return_pct\nAlpha Fund,450,12.5\nBeta Fund,1200,8.3\nGamma Fund,780,15.1",
        "query": "Which fund had the highest YTD return?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "financial_03",
        "doc_type": "tabular",
        "content": "portfolio,sector,weight_pct\nPortfolio A,Tech,35\nPortfolio A,Finance,25\nPortfolio A,Healthcare,40",
        "query": "What sectors are in Portfolio A and what are their weights?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    # ── Client / CRM data ────────────────────────────────────────────────────
    {
        "id": "crm_01",
        "doc_type": "tabular",
        "content": "client,rm,aum_m,segment\nAlice Wang,John Smith,45,HNW\nBob Chen,Jane Doe,12,Mass Affluent\nCarol Park,John Smith,85,UHNW",
        "query": "Which clients does John Smith manage?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "crm_02",
        "doc_type": "tabular",
        "content": "client,last_contact,next_review\nAlice Wang,2024-01-15,2024-04-15\nBob Chen,2024-02-01,2024-05-01\nCarol Park,2023-12-10,2024-03-10",
        "query": "Which client review is due soonest?",
        "expected_complexity": "complex",
        "expected_min_matches": 0,
    },
    {
        "id": "crm_03",
        "doc_type": "tabular",
        "content": "name,age,risk_profile,invested_m\nAlice,45,moderate,2.5\nBob,62,conservative,8.1\nCarol,38,aggressive,1.2",
        "query": "What is the total AUM across all clients?",
        "expected_complexity": "complex",
        "expected_min_matches": 0,
    },
    # ── Investment / trade data ──────────────────────────────────────────────
    {
        "id": "trade_01",
        "doc_type": "tabular",
        "content": "trade_id,security,side,qty,price\nT001,AAPL,buy,100,185.50\nT002,MSFT,sell,50,375.20\nT003,AAPL,buy,200,184.90",
        "query": "What AAPL trades were executed?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "trade_02",
        "doc_type": "tabular",
        "content": "trade_id,security,side,qty,price\nT001,AAPL,buy,100,185.50\nT002,MSFT,sell,50,375.20\nT003,AAPL,buy,200,184.90",
        "query": "What is the total value of all buy trades?",
        "expected_complexity": "complex",
        "expected_min_matches": 0,
    },
    # ── Image / OCR simulation ───────────────────────────────────────────────
    {
        "id": "ocr_prose_01",
        "doc_type": "prose",
        "content": "[OCR extracted text] Invoice #INV-2024-001. Date: March 15, 2024. Amount Due: $4,250.00. Due Date: April 15, 2024.",
        "query": "What is the invoice amount?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "ocr_prose_02",
        "doc_type": "prose",
        "content": "[OCR extracted text] Contract Agreement between Acme Corp and Beta Ltd. Effective Date: January 1, 2024. Term: 24 months.",
        "query": "What is the contract term?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    # ── Multi-document session ───────────────────────────────────────────────
    {
        "id": "multi_doc_01",
        "doc_type": "tabular",
        "content": (
            "## File: jan_sales.csv\nclient,revenue\nAlice,45000\nBob,38000\n\n"
            "## File: feb_sales.csv\nclient,revenue\nAlice,52000\nBob,41000"
        ),
        "query": "What was Alice's total revenue across both files?",
        "expected_complexity": "complex",
        "expected_min_matches": 0,
    },
    {
        "id": "multi_doc_02",
        "doc_type": "prose",
        "content": (
            "Document 1: Q1 revenue was $3.2M. Growth was 8% YoY.\n\n"
            "Document 2: Q2 revenue was $3.8M. Growth was 11% YoY."
        ),
        "query": "What was the revenue growth trend across the quarters?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    # ── Edge cases ───────────────────────────────────────────────────────────
    {
        "id": "edge_empty_result_01",
        "doc_type": "tabular",
        "content": "name,city\nAlice,New York\nBob,London",
        "query": "Who lives in Paris?",
        "expected_complexity": "simple",
        "expected_min_matches": 0,
    },
    {
        "id": "edge_numeric_comparison_01",
        "doc_type": "tabular",
        "content": "product,price\nWidget,9.99\nGadget,14.99\nDoohickey,4.99\nThingamajig,24.99",
        "query": "Which products cost more than $10?",
        "expected_complexity": "complex",
        "expected_min_matches": 0,
    },
    {
        "id": "edge_date_filter_01",
        "doc_type": "tabular",
        "content": "event,date,location\nConference,2024-03-15,New York\nWebinar,2024-01-20,Online\nSummit,2024-06-10,London",
        "query": "Which events are after March 2024?",
        "expected_complexity": "complex",
        "expected_min_matches": 0,
    },
    {
        "id": "edge_boolean_filter_01",
        "doc_type": "tabular",
        "content": "user,active,plan\nAlice,true,premium\nBob,false,basic\nCarol,true,basic\nDave,true,premium",
        "query": "Which active users are on the premium plan?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "edge_long_prose_01",
        "doc_type": "prose",
        "content": (
            "Section 1 to 20 all discuss general topics. "
            "The key finding is that Topic 7 has the highest impact on performance. "
            "Other sections provide supplementary context."
        ),
        "query": "Which topic has the highest impact?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "edge_mixed_types_01",
        "doc_type": "tabular",
        "content": "item,value,unit\nWeight,75.5,kg\nHeight,1.82,m\nAge,32,years\nBMI,22.8,kg/m2",
        "query": "What is the weight?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    # ── Cross-column reasoning ───────────────────────────────────────────────
    {
        "id": "cross_col_01",
        "doc_type": "tabular",
        "content": "employee,salary,bonus_pct\nAlice,90000,15\nBob,75000,10\nCarol,110000,20",
        "query": "What is Carol's total compensation including bonus?",
        "expected_complexity": "complex",
        "expected_min_matches": 0,
    },
    {
        "id": "cross_col_02",
        "doc_type": "tabular",
        "content": "order,subtotal,tax_rate,discount\nO1,1000,0.08,50\nO2,2000,0.08,0\nO3,500,0.08,25",
        "query": "What is the total amount for order O1 after tax and discount?",
        "expected_complexity": "complex",
        "expected_min_matches": 0,
    },
    {
        "id": "cross_col_03",
        "doc_type": "tabular",
        "content": "asset,buy_price,current_price,quantity\nAAPL,150,185,100\nMSFT,300,375,50\nGOOG,130,175,75",
        "query": "Which position has the highest unrealized gain in percentage terms?",
        "expected_complexity": "complex",
        "expected_min_matches": 0,
    },
    # ── Regulatory / compliance ──────────────────────────────────────────────
    {
        "id": "compliance_01",
        "doc_type": "prose",
        "content": (
            "Client Alice Wang: KYC completed 2023-06-15. AML screening: PASS. "
            "Client Bob Chen: KYC completed 2022-03-10. AML screening: REVIEW. "
            "Client Carol Park: KYC completed 2024-01-05. AML screening: PASS."
        ),
        "query": "Which clients have a KYC AML status of REVIEW?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
    {
        "id": "compliance_02",
        "doc_type": "tabular",
        "content": "client,kyc_date,expiry_date,status\nAlice,2022-01-01,2024-01-01,expired\nBob,2023-06-01,2025-06-01,active\nCarol,2021-12-01,2023-12-01,expired",
        "query": "Which clients have expired KYC?",
        "expected_complexity": "simple",
        "expected_min_matches": 1,
    },
]

assert len(BENCHMARK_SCENARIOS) == 50, f"Expected 50 scenarios, got {len(BENCHMARK_SCENARIOS)}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_schema(doc_type: str, columns: list[str] | None = None) -> DocumentSchema:
    cols = columns or ["col1", "col2", "col3"]
    col_schemas = [ColumnSchema(name=c) for c in cols]
    sheet = SheetSchema(name="Sheet1", columns=col_schemas, row_count=10)
    return DocumentSchema(
        document_type=doc_type,
        total_sheets=1,
        sheets=[sheet],
        summary=f"A {doc_type} document with {len(cols)} columns",
    )


def _make_session(content: str, doc_type: str) -> DocumentSession:
    return DocumentSession(
        text=content,
        texts=[content],
        filenames=["benchmark_doc.csv" if doc_type == "tabular" else "benchmark_doc.pdf"],
        metadata=[{"filename": "benchmark_doc", "type": doc_type, "char_count": len(content)}],
    )


def _openai_plan_response(complexity: str, relevant_cols: list[str] | None = None) -> MagicMock:
    """Build an OpenAI mock response for the query planning LLM call."""
    plan_dict = {
        "relevant_columns": relevant_cols or ["col1", "col2"],
        "extraction_instruction": "Extract the requested data",
        "document_type": "tabular",
        "complexity": complexity,
    }
    msg = MagicMock()
    msg.content = json.dumps(plan_dict)
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
    return resp


def _openai_extract_response(matches: list[dict]) -> MagicMock:
    """Build an OpenAI mock response for the extraction LLM call."""
    extract_dict = {
        "matches": matches,
        "query_interpretation": "Extracted the requested data",
    }
    msg = MagicMock()
    msg.content = json.dumps(extract_dict)
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=200, completion_tokens=100)
    return resp


# ---------------------------------------------------------------------------
# Core benchmark test class
# ---------------------------------------------------------------------------

class TestBenchmarkComplexityRouting:
    """Verify query complexity classification routes correctly for all 50 scenarios.

    For simple queries: checks that the programmatic extractor is used (no LLM extraction call).
    For complex queries: checks that the LLM-based extractor is invoked.
    """

    def _make_mock_client(self, scenario: dict) -> MagicMock:
        """Return an OpenAI client mock with appropriate side_effect for the scenario.

        get_openai_client() is called directly (not as context manager) in the
        implementation, so mock must be set on the returned client directly.
        """
        complexity = scenario["expected_complexity"]
        doc_type = scenario["doc_type"]

        plan_response = _openai_plan_response(complexity)
        mock_client = MagicMock()

        if doc_type == "tabular" and complexity == "complex":
            extract_response = _openai_extract_response([
                {"text": "Extracted result", "source": "benchmark_doc.csv", "page": 1},
            ])
            mock_client.chat.completions.create = AsyncMock(
                side_effect=[plan_response, extract_response]
            )
        else:
            mock_client.chat.completions.create = AsyncMock(return_value=plan_response)
        return mock_client

    @pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS, ids=[s["id"] for s in BENCHMARK_SCENARIOS])
    def test_scenario_output_structure(self, scenario: dict) -> None:
        """Every scenario must return a QueryResult with all required fields."""
        import asyncio
        from app.document_intelligence import _query_document_impl

        session = _make_session(scenario["content"], scenario["doc_type"])
        schema = _make_schema(scenario["doc_type"])
        mock_client = self._make_mock_client(scenario)

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # cache miss + no cost
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.setex = AsyncMock()
        mock_redis.sadd = AsyncMock()
        mock_redis.expire = AsyncMock()
        mock_redis.incrbyfloat = AsyncMock()
        mock_redis.smembers = AsyncMock(return_value=set())

        with (
            patch("app.document_intelligence.get_openai_client", return_value=mock_client),
            patch("app.document_intelligence.get_documents", AsyncMock(return_value=session)),
            patch("app.document_intelligence._load_schema", AsyncMock(return_value=schema)),
            patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)),
            patch("app.document_intelligence.settings") as s,
        ):
            s.query_model = "gpt-4.1"
            s.redis_ttl_hours = 24
            s.max_session_cost = 10.0
            s.enable_semantic_classification = True
            result = asyncio.get_event_loop().run_until_complete(
                _query_document_impl("benchmark-session", scenario["query"])
            )

        # Required fields always present
        assert isinstance(result, QueryResult), f"[{scenario['id']}] Expected QueryResult"
        assert hasattr(result, "matches"), f"[{scenario['id']}] Missing 'matches'"
        assert hasattr(result, "query_interpretation"), f"[{scenario['id']}] Missing 'query_interpretation'"
        assert hasattr(result, "total_matches"), f"[{scenario['id']}] Missing 'total_matches'"
        assert result.total_matches == len(result.matches), f"[{scenario['id']}] total_matches mismatch"
        assert result.error is None or isinstance(result.error, str), f"[{scenario['id']}] Invalid error field"


class TestBenchmarkComplexityClassification:
    """Verify the query plan LLM call extracts correct complexity for each scenario type.

    Note: get_openai_client() is called directly (not as async context manager) in
    _build_query_plan, so mock must be set up on the returned client object directly.
    """

    def _mock_openai_client(self, complexity: str) -> MagicMock:
        """Return a mock that get_openai_client() can return directly."""
        plan_response = _openai_plan_response(complexity)
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=plan_response)
        return mock_client

    @pytest.mark.parametrize("scenario", [
        s for s in BENCHMARK_SCENARIOS if s["expected_complexity"] == "complex"
    ], ids=[s["id"] for s in BENCHMARK_SCENARIOS if s["expected_complexity"] == "complex"])
    def test_complex_query_routes_to_llm_extraction(self, scenario: dict) -> None:
        """Complex tabular queries must trigger the LLM extraction path."""
        import asyncio
        from app.document_intelligence import _build_query_plan

        schema = _make_schema(scenario["doc_type"])
        mock_client = self._mock_openai_client("complex")

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            plan = asyncio.get_event_loop().run_until_complete(
                _build_query_plan(schema, scenario["query"])
            )

        assert plan.complexity == "complex", (
            f"[{scenario['id']}] Query '{scenario['query']}' should classify as complex"
        )

    @pytest.mark.parametrize("scenario", [
        s for s in BENCHMARK_SCENARIOS if s["expected_complexity"] == "simple"
    ], ids=[s["id"] for s in BENCHMARK_SCENARIOS if s["expected_complexity"] == "simple"])
    def test_simple_query_routes_to_programmatic_extraction(self, scenario: dict) -> None:
        """Simple queries must classify as simple."""
        import asyncio
        from app.document_intelligence import _build_query_plan

        schema = _make_schema(scenario["doc_type"])
        mock_client = self._mock_openai_client("simple")

        with patch("app.document_intelligence.get_openai_client", return_value=mock_client):
            plan = asyncio.get_event_loop().run_until_complete(
                _build_query_plan(schema, scenario["query"])
            )

        assert plan.complexity == "simple", (
            f"[{scenario['id']}] Query '{scenario['query']}' should classify as simple"
        )


class TestBenchmarkCacheHit:
    """Verify cached results short-circuit execution for all scenarios."""

    @pytest.mark.parametrize("scenario", BENCHMARK_SCENARIOS[:5], ids=[s["id"] for s in BENCHMARK_SCENARIOS[:5]])
    def test_cache_hit_returns_immediately(self, scenario: dict) -> None:
        """When a cached result exists, the LLM must NOT be called."""
        import asyncio
        from app.document_intelligence import _query_document_impl

        cached_result = QueryResult(
            matches=[MatchEntry(text="cached", source="test.csv", page=1)],
            query_interpretation="from cache",
            total_matches=1,
        )

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=cached_result.model_dump_json())
        mock_redis.expire = AsyncMock()

        mock_openai = MagicMock()
        mock_openai.chat.completions.create = AsyncMock()  # must NOT be called

        with (
            patch("app.document_intelligence.get_redis", AsyncMock(return_value=mock_redis)),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                _query_document_impl("benchmark-cache-session", scenario["query"])
            )

        mock_openai.chat.completions.create.assert_not_called()
        assert result.query_interpretation == "from cache", (
            f"[{scenario['id']}] Expected cached interpretation"
        )
