# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

```bash
# Primary entry point (uses Streamlit Pages API v1.41+)
streamlit run app.py

# Public (demo) mode only
streamlit run public_app.py

# Private (authenticated) mode only
streamlit run private_app.py
```

No build step, test suite, or linter is configured — development relies on Streamlit's hot reload.

## Architecture Overview

The app has two runtime modes: **Public** (demo with static portfolio) and **Private** (Google Sheets-backed, password-authenticated). The mode is determined at startup by which entry point is used.

### Layer structure

```
pages_app/          ← thin Streamlit page renderers
       ↓
app_context_runtime.py  ← builds a single context dict with ALL computed data
       ↓
app_core.py         ← all business logic: calculations, market data, charts, Sheets
       ↓
utils.py            ← raw market data fetching via yfinance
```

**`app_context_runtime.py`** is the critical integration point. `build_app_context_runtime(app_scope)` returns a large dict passed to every page — it contains the portfolio DataFrame, efficient frontier results, rebalancing suggestions, rolling metrics, and all user settings from session state. Pages should read from this dict rather than recompute.

**`app_core.py`** (~2630 lines) is where almost all logic lives:
- Portfolio construction and valuation (`build_portfolio_df`, `build_current_portfolio`)
- Multi-currency FX conversion (`build_fx_data`, `convert_historical_to_base`)
- Efficient frontier via Monte Carlo (`simulate_constrained_efficient_frontier`, N=8000)
- Rebalancing trade suggestions with TC estimation (`build_rebalancing_table`, `estimate_transaction_cost`)
- Google Sheets I/O with 30s TTL caching (`load_private_positions_from_sheets`, etc.)
- Bloomberg dark-theme CSS and all UI helper components

**`utils.py`** handles yfinance downloads with fallback from bulk to single-ticker, forward-fill, and MultiIndex flattening.

### Page routing

`app.py` registers pages using Streamlit's native Pages API. Each file in `pages_app/` exports a `render(ctx)` function that receives the context dict.

### Public vs Private distinction

- **Public:** portfolio defined statically in `portfolio.py`; user adjusts share counts via sidebar sliders; no persistence.
- **Private:** base portfolio in `private_portfolio.py` (gitignored) merged with live Google Sheets data; transactions stored in Sheets; snapshots can be saved.

## Key Constants (in app_core.py)

```python
DEFAULT_RISK_FREE_RATE = 0.02
N_SIMULATIONS = 8000                    # efficient frontier portfolios
GOOGLE_SHEETS_CACHE_TTL = 30            # seconds
SUPPORTED_BASE_CCY = ["USD", "EUR", "GBP", "COP", "CHF", "AUD"]
```

## Private Mode Setup

Create `.streamlit/secrets.toml` (gitignored):
```toml
[auth]
password = "your_password"

[gcp]
type = "service_account"
project_id = "..."
# full GCP service account JSON fields
```

## Theme

Bloomberg dark theme defined in `.streamlit/config.toml`: dark background `#0b0f14`, gold accent `#f3a712`, IBM Plex Mono font. The `apply_bloomberg_style()` function in `app_core.py` injects additional CSS at page load.
