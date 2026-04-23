# Migration Issues Log
## Project: E-Commerce SQL Analytics Platform
**Tech Stack:** Python 3.13 · SQL Server 2025 Developer Edition · pyodbc · Pandas · REST API
**Dataset:** Brazilian E-Commerce (Olist) — 112,650 rows
**Date:** April 2026
**Status:** All issues resolved ✓

---

## Issue #1 — UnicodeEncodeError: Emoji in Windows Terminal (cp1252)

**Severity:** High (pipeline crashed on every DQ check log line)
**Phase:** dq_framework.py — _save() method logging
**Error message:**
```
UnicodeEncodeError: 'charmap' codec can't encode character
'\u2705' in position 33: character maps to <undefined>
```

**What happened:**
The DQ framework pipeline crashed on every single rule check
because the logger was trying to print ✅ and ❌ emoji to the
Windows terminal. All 19 DQ checks triggered this error
sequentially — the logging error appeared before every check
result, flooding the terminal output.

The DQ checks themselves were actually running and passing
correctly — the crash was purely in the logging layer.

**Root cause:**
Windows terminal uses cp1252 (Windows-1252) encoding by default.
cp1252 is a single-byte encoding that cannot represent Unicode
characters outside the Latin-1 range. The ✅ emoji (U+2705) and
❌ emoji (U+274C) are outside this range — cp1252 has no mapping
for them and raises UnicodeEncodeError when the logging stream
handler tries to write them to stdout.

This does not affect file handlers that are opened with
explicit utf-8 encoding — only the StreamHandler writing
to the Windows terminal.

**Fix applied:**
Two-part fix:

1. Added explicit utf-8 encoding to the file handler:
```python
file_handler = logging.FileHandler(
    'logs/dq_framework.log',
    encoding='utf-8'    # supports emoji in log file
)
```

2. Replaced emoji with ASCII-safe text in the stream output:
```python
# BROKEN — emoji crashes cp1252 terminal
icon = '✅' if status == 'PASS' else '❌'
logger.info(f"{icon} {table}.{col} [{rule}]...")

# FIXED — ASCII safe, works on all Windows terminals
icon = 'PASS' if status == 'PASS' else 'FAIL'
logger.info(f"[{icon}] {table}.{col} [{rule}]...")
```

**Lesson learned:**
Never use emoji in Python logging unless you explicitly control
the terminal encoding. In production ETL pipelines running on
Windows servers, always use ASCII-safe characters in log output.
Use utf-8 encoding for log files explicitly — never rely on the
system default. On Linux/Mac this issue doesn't occur as the
default encoding is utf-8 — making it a common cross-platform
portability issue.

---

## Issue #2 — AttributeError: resultd Typo in _save() Method

**Severity:** Critical (all DQ results lost, pipeline crashed)
**Phase:** dq_framework.py — DataQualityChecker._save()
**Error message:**
```
AttributeError: 'DataQualityChecker' object has no attribute
'resultd'. Did you mean: 'results'?
```

**What happened:**
The first DQ pipeline run crashed with an AttributeError after
the very first rule check passed. No results were saved to the
in-memory list — meaning the dq_run_summary INSERT at the end
would have received an empty DataFrame even if the pipeline
had continued.

**Root cause:**
A single character typo in the `_save()` method:
```python
# BROKEN — 'd' appended to attribute name
self.resultd.append({...})

# CORRECT
self.results.append({...})
```

Python's AttributeError message actually suggested the fix —
"Did you mean: 'results'?" — which is a good reminder to read
error messages carefully before debugging.

**Fix applied:**
```python
# Single character fix in _save() method
self.results.append({
    'table': self.table_name,
    'column': col,
    'rule': rule,
    ...
})
```

**Lesson learned:**
Attribute typos in Python only surface at runtime — there is no
compile-time check. For production pipelines, add a unit test
that instantiates DataQualityChecker and calls _save() with mock
data to catch this class of error before deployment. Python's
error messages are often more helpful than they appear — the
"Did you mean" suggestion directly identified the fix.

---

## Issue #3 — dq_run_summary Table Not Found

**Severity:** Critical (monitoring dashboard crashed)
**Phase:** monitoring_dashboard.py — get_dq_summary()
**Error message:**
```
pyodbc.ProgrammingError: ('42S02', "[42S02] [Microsoft][ODBC
Driver 17 for SQL Server][SQL Server]Invalid object name
'dq_run_summary'. (208) (SQLExecDirectW)")
```

**What happened:**
The DQ framework ran successfully and logged results to dq_audit.
But when the monitoring dashboard tried to query dq_run_summary
for the run summary, SQL Server returned "Invalid object name" —
the table did not exist in Ecommerce_Analytics database.

**Root cause:**
The DQ table creation SQL (`DQ_SETUP_SQL` constant in
dq_framework.py) was defined as a string but never executed
against the database. The code assumed the tables would be
created on first run via an `IF NOT EXISTS` guard — but the
execution call was missing from the `__init__` method.

The dq_audit table was also missing but the error surfaced on
dq_run_summary first because that query ran earlier.

**Fix applied:**
Ran the table creation SQL manually in SSMS:
```sql
USE Ecommerce_Analytics;

IF NOT EXISTS (
    SELECT 1 FROM sys.tables WHERE name = 'dq_audit'
)
CREATE TABLE dq_audit (
    audit_id      INT IDENTITY(1,1) PRIMARY KEY,
    run_id        NVARCHAR(50),
    run_date      DATETIME2 DEFAULT GETDATE(),
    table_name    NVARCHAR(100),
    ...
);

IF NOT EXISTS (
    SELECT 1 FROM sys.tables WHERE name = 'dq_run_summary'
)
CREATE TABLE dq_run_summary (
    run_id         NVARCHAR(50) PRIMARY KEY,
    run_date       DATETIME2 DEFAULT GETDATE(),
    total_checks   INT DEFAULT 0,
    ...
);
```

**Lesson learned:**
Never assume setup SQL runs automatically from a string constant.
Either execute setup SQL explicitly in __init__ with a guard
check, or include it in a dedicated setup script that runs
before the pipeline. In production, database object creation
belongs in a versioned migration script — not embedded in
application code strings.

---

## Issue #4 — pd.read_sql Incompatibility with pyodbc Connection

**Severity:** High (monitoring dashboard crashed with warning + error)
**Phase:** monitoring_dashboard.py — get_dq_summary(), get_job_history()
**Error message:**
```
UserWarning: pandas only supports SQLAlchemy connectable
(engine/connection) or database string URI or sqlite3 DBAPI2
connection. Other DBAPI2 objects are not tested.

pyodbc.ProgrammingError: cursor.execute() — query failed
```

**What happened:**
The monitoring dashboard crashed when trying to read DQ summary
data into a Pandas DataFrame using pd.read_sql() with a raw
pyodbc connection object.

Pandas showed a UserWarning on the first call and then raised a
ProgrammingError on the second call — the behaviour was
inconsistent across queries, making it harder to diagnose.

**Root cause:**
Newer versions of Pandas (2.0+) deprecated support for raw
DBAPI2 connection objects in pd.read_sql(). Pandas now officially
supports only SQLAlchemy engine objects, database URI strings,
or sqlite3 connections. A raw pyodbc connection object is a
DBAPI2 object — Pandas warns about it and the behaviour is
undefined (works for some queries, fails for others).

**Fix applied:**
Replaced all pd.read_sql() calls with explicit cursor-based
reads that are fully compatible with pyodbc:

```python
# BROKEN — pd.read_sql with raw pyodbc connection
df = pd.read_sql("SELECT * FROM dq_run_summary", conn)

# FIXED — cursor-based read, always works with pyodbc
cursor = conn.cursor()
cursor.execute("SELECT * FROM dq_run_summary ORDER BY run_date DESC")
cols = [d[0] for d in cursor.description]
df = pd.DataFrame(cursor.fetchall(), columns=cols)
```

**Lesson learned:**
When using pyodbc directly (without SQLAlchemy), always use
cursor-based reads for Pandas DataFrames. If pd.read_sql() is
preferred, use SQLAlchemy's create_engine() as the connection:
```python
from sqlalchemy import create_engine
engine = create_engine(
    "mssql+pyodbc://localhost/DB?driver=ODBC+Driver+17..."
)
df = pd.read_sql("SELECT ...", engine)
```
This is the cleanest long-term solution for mixed pyodbc/Pandas
pipelines.

---

## Issue #5 — Small Denominator Distortion in Growth % Query

**Severity:** Medium (incorrect analytical output, no crash)
**Phase:** sql/analytics_queries.sql — Q3 Month-over-month growth
**Symptom:**
```
year=2016, month=10, revenue=746,014, 
previous_month=2,496, growth_pct=29,776%
```

**What happened:**
The month-over-month revenue growth query produced a 29,776%
growth figure for October 2016 — clearly unrealistic for any
business. The query itself executed without error.

**Root cause:**
Two compounding problems:

1. The Brazilian Olist dataset started in September 2016 with
   only a handful of orders (revenue = 2,496 INR). October 2016
   had normal volume (746,014 INR). The percentage formula:
   (746,014 - 2,496) / 2,496 * 100 = 29,776%
   is mathematically correct but analytically meaningless
   because the base is a ramp-up period, not steady-state.

2. November 2016 had zero delivered orders in the dataset —
   so it was absent from the CTE. LAG then compared December
   directly to October, skipping a month and producing a
   -99.97% drop that was also misleading.

**Fix applied:**
Two-part fix:

1. Filter to stable data period starting 2017:
```sql
WHERE year >= 2017
```

2. Use dim_date as the base to fill missing months with zero:
```sql
WITH all_months AS (
    SELECT DISTINCT year, month
    FROM dim_date
    WHERE year BETWEEN 2016 AND 2018
),
monthly_revenue AS (
    SELECT d.year, d.month,
           ISNULL(SUM(f.price_inr), 0) AS revenue
    FROM all_months d
    LEFT JOIN dim_date dd
        ON dd.year = d.year AND dd.month = d.month
    LEFT JOIN fact_orders f
        ON f.date_sk = dd.date_sk
        AND f.order_status = 'delivered'
    GROUP BY d.year, d.month
)
```

3. Added CASE guard for zero-base divisions:
```sql
CASE
    WHEN LAG(revenue) OVER (ORDER BY year, month) = 0
    THEN NULL
    ELSE ROUND(...)
END AS growth_pct
```

**Lesson learned:**
This is a classic problem called small denominator distortion —
when the base value is very small, percentage changes become
mathematically correct but analytically meaningless. Production
SQL analytics should always include:
- A minimum threshold check for the denominator
- Ramp-up period exclusion for new datasets
- NULL handling for zero-base scenarios
Always validate time-series query output visually before
including it in a report or dashboard.

---

## Issue #6 — Missing Months in Time-Series (Sparse Data Gap)

**Severity:** Medium (silent data quality issue in output)
**Phase:** sql/analytics_queries.sql — all time-series queries
**Symptom:**
Month 10 (October) jumped directly to month 12 (December) in
the monthly revenue CTE — November 2016 was completely absent.
LAG() compared December to October, producing incorrect
month-over-month deltas across multiple queries.

**Root cause:**
The monthly CTE was built by grouping fact_orders — which only
contains months where at least one delivered order existed.
November 2016 had zero delivered orders in the Olist dataset,
so it produced no rows in the GROUP BY and was silently excluded.

This is a fundamental sparse data problem in time-series SQL —
aggregation on fact data will always skip periods with no
activity unless a date spine is used as the base.

**Fix applied:**
Rebuilt all time-series CTEs using dim_date as the LEFT JOIN
base — ensuring every month in the date range appears in the
result even with zero revenue:

```sql
-- BROKEN: fact-based CTE skips empty months
WITH monthly AS (
    SELECT d.year, d.month, SUM(f.price_inr) AS revenue
    FROM fact_orders f
    JOIN dim_date d ON f.date_sk = d.date_sk
    GROUP BY d.year, d.month
)

-- FIXED: date-spine base ensures no gaps
WITH monthly AS (
    SELECT d.year, d.month,
           ISNULL(SUM(f.price_inr), 0) AS revenue
    FROM (SELECT DISTINCT year, month FROM dim_date
          WHERE year BETWEEN 2017 AND 2018) d
    LEFT JOIN dim_date dd
        ON dd.year = d.year AND dd.month = d.month
    LEFT JOIN fact_orders f
        ON f.date_sk = dd.date_sk
        AND f.order_status = 'delivered'
    GROUP BY d.year, d.month
)
```

**Lesson learned:**
Always use a date dimension as the LEFT JOIN base for any
time-series query. Never GROUP BY on fact data alone — it will
silently drop periods with no activity. The dim_date table
exists specifically to solve this problem. This pattern applies
to any time-series analysis: daily sales, weekly signups,
monthly revenue — always anchor to the date spine.

---

## Summary Table

| # | Issue | Phase | Severity | Type |
|---|---|---|---|---|
| 1 | Emoji UnicodeEncodeError on Windows | Logging | High | Encoding |
| 2 | AttributeError: resultd typo | DQ Engine | Critical | Typo |
| 3 | dq_run_summary table not created | Setup | Critical | Missing setup |
| 4 | pd.read_sql pyodbc incompatibility | Dashboard | High | API version |
| 5 | Small denominator distortion in growth % | SQL Analytics | Medium | Data quality |
| 6 | Missing months in time-series (sparse data) | SQL Analytics | Medium | Sparse data |

---

## What This Project Taught Me

1. **Always specify encoding explicitly** — never rely on system
   default encoding in logging or file I/O. Windows servers use
   cp1252 by default which breaks on any Unicode outside Latin-1.

2. **Attribute typos surface only at runtime in Python** — add
   unit tests for critical class methods to catch these before
   running against real data. Python's error messages often
   contain the fix — read them fully before debugging.

3. **Database setup SQL must be executed, not just defined** —
   embedding setup SQL as a string constant is not the same as
   running it. Always use versioned migration scripts with
   IF NOT EXISTS guards for database object creation.

4. **pd.read_sql() requires SQLAlchemy in Pandas 2.0+** — raw
   pyodbc connections are deprecated. Use cursor-based reads
   for pure pyodbc pipelines, or SQLAlchemy create_engine()
   for pd.read_sql() compatibility.

5. **Sparse data silently breaks time-series queries** — GROUP BY
   on fact data skips empty periods. Always use a date dimension
   as the LEFT JOIN base. This is non-negotiable for any
   production analytics query involving time.

6. **Small denominators make percentages meaningless** — always
   validate time-series output visually. Ramp-up periods in new
   datasets should be excluded or flagged, never reported as
   legitimate growth metrics.
