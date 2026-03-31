from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_core import info_metric, info_section, render_page_title


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_ohlcv(ticker: str) -> pd.DataFrame:
    import yfinance as yf
    return yf.Ticker(ticker).history(period="3y", auto_adjust=True)


def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    close = df["Close"]
    feat = pd.DataFrame(index=df.index)

    feat["ret_1d"] = close.pct_change(1)
    feat["ret_5d"] = close.pct_change(5)
    feat["ret_21d"] = close.pct_change(21)

    # RSI-14
    delta = close.diff()
    avg_gain = delta.clip(lower=0).rolling(14).mean()
    avg_loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    feat["rsi_14"] = 100 - 100 / (1 + rs)

    # MACD histogram (MACD minus signal line)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    feat["macd_hist"] = macd - macd.ewm(span=9, adjust=False).mean()

    # SMA ratios (price relative to moving averages)
    feat["sma20_ratio"] = close / close.rolling(20).mean()
    feat["sma50_ratio"] = close / close.rolling(50).mean()

    # Realized volatility (21d)
    feat["vol_21d"] = close.pct_change().rolling(21).std()

    # Target: will price be higher in 5 trading days?
    feat["target"] = (close.shift(-5) > close).astype(int)

    return feat.dropna()


FEATURE_COLS = ["ret_1d", "ret_5d", "ret_21d", "rsi_14", "macd_hist",
                "sma20_ratio", "sma50_ratio", "vol_21d"]
TRAIN_WINDOW = 252
TEST_WINDOW = 63
MIN_BARS = TRAIN_WINDOW + TEST_WINDOW  # 315


@st.cache_data(ttl=3600, show_spinner=False)
def _run_ml_pipeline(ticker: str) -> dict:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score

    df = _fetch_ohlcv(ticker)
    if df is None or df.empty:
        return {"error": f"No data returned for {ticker}"}

    feat = _build_features(df)
    if len(feat) < MIN_BARS:
        return {"error": f"Need {MIN_BARS}+ clean bars, got {len(feat)} for {ticker}"}

    X = feat[FEATURE_COLS].values
    y = feat["target"].values

    all_preds, all_actuals, all_probas = [], [], []
    importance_sum = np.zeros(len(FEATURE_COLS))
    num_folds = 0

    for i in range(0, len(X) - TRAIN_WINDOW - TEST_WINDOW, TEST_WINDOW):
        X_train = X[i: i + TRAIN_WINDOW]
        y_train = y[i: i + TRAIN_WINDOW]
        X_test = X[i + TRAIN_WINDOW: i + TRAIN_WINDOW + TEST_WINDOW]
        y_test = y[i + TRAIN_WINDOW: i + TRAIN_WINDOW + TEST_WINDOW]

        if len(np.unique(y_train)) < 2:
            continue

        clf = RandomForestClassifier(
            n_estimators=100,
            max_depth=4,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )
        clf.fit(X_train, y_train)

        preds = clf.predict(X_test)
        probas = clf.predict_proba(X_test)[:, 1]

        all_preds.extend(preds.tolist())
        all_actuals.extend(y_test.tolist())
        all_probas.extend(probas.tolist())
        importance_sum += clf.feature_importances_
        num_folds += 1

    if num_folds == 0:
        return {"error": f"Walk-forward validation failed for {ticker} — insufficient class diversity"}

    oos_accuracy = accuracy_score(all_actuals, all_preds) * 100
    last_proba = float(all_probas[-1])
    importances = dict(zip(FEATURE_COLS, (importance_sum / num_folds).tolist()))

    if last_proba >= 0.6:
        signal = "BULLISH"
    elif last_proba <= 0.4:
        signal = "BEARISH"
    else:
        signal = "NEUTRAL"

    confidence = abs(last_proba - 0.5) * 200

    last_date = feat.index[-1]
    last_date_str = last_date.date().isoformat() if hasattr(last_date, "date") else str(last_date)

    return {
        "ticker": ticker,
        "signal": signal,
        "confidence": round(confidence, 1),
        "last_proba": round(last_proba, 3),
        "oos_accuracy": round(oos_accuracy, 1),
        "importances": importances,
        "num_folds": num_folds,
        "last_fold_date": last_date_str,
    }


def _signal_badge(signal: str, confidence: float) -> str:
    colors = {
        "BULLISH": ("#00e676", "#0d3d0d"),
        "BEARISH": ("#f44336", "#3d0d0d"),
        "NEUTRAL": ("#f3a712", "#3d2e0d"),
    }
    fg, bg = colors.get(signal, ("#888888", "#1a1f2e"))
    return (
        f'<span style="background:{bg};color:{fg};border:1px solid {fg};'
        f'padding:5px 16px;border-radius:12px;font-size:14px;'
        f"font-family:'IBM Plex Mono',monospace;font-weight:700;\">"
        f"{signal}&nbsp;·&nbsp;{confidence:.0f}% confidence</span>"
    )


def _build_importance_chart(importances: dict, ticker: str) -> go.Figure:
    sorted_items = sorted(importances.items(), key=lambda x: x[1])
    labels = [k.replace("_", " ").upper() for k, _ in sorted_items]
    values = [v for _, v in sorted_items]

    fig = go.Figure(go.Bar(
        x=values, y=labels,
        orientation="h",
        marker_color="#f3a712",
        text=[f"{v:.1%}" for v in values],
        textposition="outside",
        textfont=dict(color="#e6e6e6", size=11),
    ))
    fig.update_layout(
        paper_bgcolor="#0b0f14", plot_bgcolor="#0b0f14",
        font=dict(color="#e6e6e6"), height=290,
        margin=dict(t=20, b=20, l=130, r=80),
        xaxis=dict(tickformat=".0%", title="Avg importance across folds"),
        title=dict(text=f"{ticker} · Feature Importance", font=dict(size=13)),
    )
    return fig


def render_ml_signals_page(ctx):
    render_page_title("ML Signals")

    portfolio_tickers = list(ctx.get("updated_portfolio", {}).keys())

    st.markdown(
        "Walk-forward RandomForest signal classification. "
        "Train window: **252 days**, test window: **63 days**, data: **3 years**."
    )

    col_mode, col_custom = st.columns([2, 3])
    ticker_mode = col_mode.radio(
        "Analyze", ["All portfolio tickers", "Custom tickers"],
        key="ml_mode",
    )
    tickers_to_run: list[str] = []
    if ticker_mode == "Custom tickers":
        custom_raw = col_custom.text_input(
            "Tickers (comma-separated)", placeholder="AAPL, MSFT, NVDA", key="ml_custom",
        )
        tickers_to_run = [t.strip().upper() for t in custom_raw.split(",") if t.strip()]
    else:
        tickers_to_run = portfolio_tickers

    run = st.button("Run ML Analysis", type="primary", key="ml_run")

    if not run and "ml_results" not in st.session_state:
        st.info("Select tickers above and press **Run ML Analysis**.")
        return

    if run:
        if not tickers_to_run:
            st.warning("No tickers selected.")
            return

        results: dict = {}
        progress = st.progress(0, text="Initializing...")
        for i, ticker in enumerate(tickers_to_run):
            progress.progress(
                (i + 1) / len(tickers_to_run),
                text=f"Walk-forward validation: {ticker} ({i+1}/{len(tickers_to_run)})...",
            )
            results[ticker] = _run_ml_pipeline(ticker)
        progress.empty()

        # Store signals for paper trading
        ml_signals = {
            ticker: {
                "signal": r["signal"],
                "confidence": r["confidence"],
                "timestamp": datetime.now().isoformat(),
            }
            for ticker, r in results.items()
            if not r.get("error")
        }
        st.session_state["ml_signals"] = ml_signals
        st.session_state["ml_results"] = results

    results = st.session_state.get("ml_results", {})
    if not results:
        return

    # ── Summary table ──────────────────────────────────────────────────────────
    info_section(
        "Portfolio Signal Summary",
        "Walk-forward OOS accuracy and latest 5-day directional signal per ticker.",
    )

    summary_rows = []
    for ticker, r in results.items():
        if r.get("error"):
            summary_rows.append({
                "Ticker": ticker,
                "Signal": "ERROR",
                "Confidence %": "—",
                "OOS Accuracy %": "—",
                "Folds": "—",
                "Last Data": r["error"],
            })
        else:
            summary_rows.append({
                "Ticker": ticker,
                "Signal": r["signal"],
                "Confidence %": r["confidence"],
                "OOS Accuracy %": r["oos_accuracy"],
                "Folds": r["num_folds"],
                "Last Data": r.get("last_fold_date", ""),
            })

    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, height=280)

    if st.session_state.get("ml_signals"):
        st.caption("Signals saved to session — go to **Paper Trading** to simulate trades based on these signals.")

    # ── Ticker detail ──────────────────────────────────────────────────────────
    valid = [t for t, r in results.items() if not r.get("error")]
    if not valid:
        st.warning("No valid results to display in detail view.")
        return

    info_section("Ticker Detail", "Signal, confidence, feature importance, and walk-forward statistics.")
    selected = st.selectbox("Select ticker for detail", valid, key="ml_detail_select")
    r = results[selected]

    st.markdown(_signal_badge(r["signal"], r["confidence"]), unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    d1, d2, d3, d4 = st.columns(4)
    info_metric(d1, "OOS Accuracy", f"{r['oos_accuracy']:.1f}%", "Out-of-sample accuracy across all folds")
    info_metric(d2, "P(Up 5d)", f"{r['last_proba']:.1%}", "Bullish probability from last test fold")
    info_metric(d3, "Walk-Forward Folds", str(r["num_folds"]), "Number of 63-day test windows completed")
    info_metric(d4, "Last Fold Date", r.get("last_fold_date", "—"), "Date of the most recent test fold")

    st.plotly_chart(
        _build_importance_chart(r["importances"], selected),
        use_container_width=True,
        key="ml_importance_chart",
    )

    st.caption(
        "Model: RandomForestClassifier (100 trees, max_depth=4, balanced classes). "
        "Features computed from closing price only."
    )
