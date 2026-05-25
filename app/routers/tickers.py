import math
import json
from datetime import datetime, date
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
import yfinance as yf
import pandas as pd

from app.database import get_db
from app.models import TickerRawData, HistoricalPrice, Ticker
from app.schemas import (
    TickerFetchRequest,
    TickerFetchResponse,
    HistoricalPriceResponse,
    TickerRawDataResponse
)
from app.auth import get_current_user

router = APIRouter(prefix="/api/v1/tickers", tags=["tickers"])

# ─────────────────────────────────────────────────────────────
# 🛠️ Robust Serialization Logic (pandas/yfinance to JSON-safe)
# ─────────────────────────────────────────────────────────────
def to_serializable(obj):
    """Converts any return from yfinance/pandas to a JSON-safe representation."""
    if obj is None:
        return None
    
    # Handle pandas DataFrame
    if isinstance(obj, pd.DataFrame):
        if obj.empty:
            return []
        df = obj.copy()
        df.index = [str(i) for i in df.index]
        df.columns = [str(c) for c in df.columns]
        return to_serializable(df.reset_index().to_dict(orient='records'))
        
    # Handle pandas Series
    if isinstance(obj, pd.Series):
        if obj.empty:
            return {}
        s = obj.copy()
        s.index = [str(i) for i in s.index]
        return to_serializable(s.to_dict())
        
    # Handle Timestamp and datetime
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return obj.isoformat()
        
    # Handle float (specifically NaN and Inf)
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
        
    # Handle dict (recursively sanitize keys and values)
    if isinstance(obj, dict):
        return {
            str(k) if not isinstance(k, (str, int, float, bool, type(None))) else k: to_serializable(v)
            for k, v in obj.items()
        }
        
    # Handle lists/tuples (recursively sanitize elements)
    if isinstance(obj, (list, tuple)):
        return [to_serializable(i) for i in obj]
        
    # Handle standard primitive types
    if isinstance(obj, (str, int, bool)):
        return obj
        
    # Handle object attributes (fallback)
    if hasattr(obj, "__dict__"):
        return {k: to_serializable(v) for k, v in vars(obj).items() if not k.startswith("_")}
        
    # Fallback to string representation
    try:
        if hasattr(obj, "item"):
            val = obj.item()
            return to_serializable(val)
    except Exception:
        pass
        
    return str(obj)

def safe_float(val):
    if pd.isna(val) or (isinstance(val, float) and math.isnan(val)):
        return None
    return float(val)

# ─────────────────────────────────────────────────────────────
# 📥 yfinance attributes to import
# ─────────────────────────────────────────────────────────────
KEYS_TO_FETCH = [
    "info", "fast_info", "history_metadata", "calendar", "sec_filings",
    "balance_sheet", "income_stmt", "cash_flow", "financials",
    "quarterly_balance_sheet", "quarterly_income_stmt", "quarterly_cash_flow",
    "earnings", "quarterly_earnings", "earnings_dates",
    "dividends", "splits", "actions", "capital_gains",
    "major_holders", "institutional_holders", "mutualfund_holders",
    "insider_transactions", "insider_purchases", "insider_roster_holders",
    "recommendations", "recommendations_summary", "upgrades_downgrades",
    "analyst_price_targets", "earnings_estimate", "revenue_estimate",
    "eps_trend", "eps_revisions", "growth_estimates", "valuation",
    "sustainability", "shares", "funds_data", "ttm_financials", "ttm_income_stmt",
    "news", "isin"
]

# ─────────────────────────────────────────────────────────────
# 🌐 Endpoints
# ─────────────────────────────────────────────────────────────

@router.post("/fetch", response_model=TickerFetchResponse, status_code=status.HTTP_201_CREATED)
def fetch_ticker_data(
    payload: TickerFetchRequest,
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user)
):
    """
    Fetch comprehensive stock data from yfinance for a B3 ticker and persist it in PostgreSQL.
    Automatically appends '.SA' if the B3 suffix is missing.
    """
    ticker = payload.ticker
    if not ticker.endswith(".SA"):
        ticker += ".SA"

    tk = yf.Ticker(ticker)
    try:
        hist = tk.history(period="max", auto_adjust=True)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to fetch history for ticker '{payload.ticker}': {str(e)}"
        )

    if hist.empty:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No yfinance data found for ticker '{payload.ticker}'. Please check the ticker name."
        )

    now = datetime.now()

    try:
        # Delete existing data for clean ups (same behavior as SQLite REPLACE/DELETE)
        db.query(HistoricalPrice).filter(HistoricalPrice.ticker == ticker).delete()
        db.query(TickerRawData).filter(TickerRawData.ticker == ticker).delete()

        # Update or create the Ticker registry record (Idempotent, no duplicates)
        ticker_record = db.query(Ticker).filter(Ticker.ticker == ticker).first()
        if ticker_record:
            ticker_record.sync_date = now
        else:
            ticker_record = Ticker(ticker=ticker, sync_date=now)
            db.add(ticker_record)

        # 1️⃣ Insert historical prices
        historical_records = []
        for date_val, row in hist.iterrows():
            historical_records.append(
                HistoricalPrice(
                    ticker=ticker,
                    date=date_val.date(),
                    open=safe_float(row.get("Open")),
                    high=safe_float(row.get("High")),
                    low=safe_float(row.get("Low")),
                    close=safe_float(row.get("Close")),
                    volume=safe_float(row.get("Volume")),
                    dividends=safe_float(row.get("Dividends")),
                    stock_splits=safe_float(row.get("Stock Splits"))
                )
            )
        db.bulk_save_objects(historical_records)

        # 2️⃣ Insert other keys (flexible JSON)
        keys_saved = []
        raw_records = []
        for key in KEYS_TO_FETCH:
            try:
                data = getattr(tk, key, None)
                if callable(data):
                    data = data()
                
                serializable = to_serializable(data)
                if serializable is None or serializable == [] or serializable == {}:
                    continue

                raw_records.append(
                    TickerRawData(
                        ticker=ticker,
                        data_key=key,
                        data_json=serializable,
                        fetched_at=now
                    )
                )
                keys_saved.append(key)
            except Exception as e:
                raw_records.append(
                    TickerRawData(
                        ticker=ticker,
                        data_key=key,
                        data_json={"_error": str(e)},
                        fetched_at=now
                    )
                )
                keys_saved.append(key)

        if raw_records:
            db.bulk_save_objects(raw_records)

        db.commit()

        return TickerFetchResponse(
            ticker=ticker,
            keys_fetched=keys_saved,
            historical_records_count=len(historical_records),
            message=f"Successfully imported stock data for {ticker}",
            fetched_at=now,
            sync_date=now
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database transaction failed during save: {str(e)}"
        )


@router.get("", response_model=List[str])
def list_tickers(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user)
):
    """
    List all tickers currently imported into the database.
    """
    tickers = db.query(Ticker.ticker).order_by(Ticker.ticker).limit(limit).offset(offset).all()
    return [t[0] for t in tickers]


@router.get("/{ticker}/historical", response_model=List[HistoricalPriceResponse])
def get_historical_prices(
    ticker: str,
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user)
):
    """
    Retrieve structured historical prices for a specific B3 ticker.
    Supports filtering by start and end date with pagination.
    """
    clean_ticker = ticker.upper().strip()
    if not clean_ticker.endswith(".SA"):
        clean_ticker += ".SA"

    query = db.query(HistoricalPrice).filter(HistoricalPrice.ticker == clean_ticker)
    
    if start_date:
        query = query.filter(HistoricalPrice.date >= start_date)
    if end_date:
        query = query.filter(HistoricalPrice.date <= end_date)
        
    query = query.order_by(HistoricalPrice.date.desc())
    prices = query.limit(limit).offset(offset).all()
    
    if not prices:
        ticker_exists = db.query(Ticker).filter(Ticker.ticker == clean_ticker).first()
        if not ticker_exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Ticker '{clean_ticker}' has no stored historical prices. Please import it first."
            )
            
    return prices


@router.get("/{ticker}/raw")
def get_raw_ticker_data(
    ticker: str,
    key: Optional[str] = Query(None, description="Specific yfinance attribute (e.g. 'info', 'calendar')"),
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user)
):
    """
    Retrieve raw JSON data from yfinance for a specific ticker.
    If 'key' is provided, returns just the value for that key.
    Otherwise, returns a dictionary of all available keys for the ticker.
    """
    clean_ticker = ticker.upper().strip()
    if not clean_ticker.endswith(".SA"):
        clean_ticker += ".SA"

    if key:
        raw_record = db.query(TickerRawData).filter(
            TickerRawData.ticker == clean_ticker,
            TickerRawData.data_key == key.lower().strip()
        ).first()
        
        if not raw_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Key '{key}' not found for ticker '{clean_ticker}'. Check if it exists or fetch again."
            )
        return raw_record.data_json
    else:
        raw_records = db.query(TickerRawData).filter(TickerRawData.ticker == clean_ticker).all()
        if not raw_records:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Ticker '{clean_ticker}' not found. Please import it first."
            )
        return {r.data_key: r.data_json for r in raw_records}


# ─────────────────────────────────────────────────────────────
# 🛠️ Dynamic Route Setup for Attributes and Methods
# ─────────────────────────────────────────────────────────────

ATTRIBUTES = [
    "actions", "analyst_price_targets", "balance_sheet", "balancesheet", "calendar", "capital_gains",
    "cash_flow", "cashflow", "dividends", "earnings", "earnings_dates", "earnings_estimate",
    "earnings_history", "eps_revisions", "eps_trend", "fast_info", "financials",
    "funds_data", "growth_estimates", "history_metadata", "income_stmt", "incomestmt", "info",
    "insider_purchases", "insider_roster_holders", "insider_transactions",
    "institutional_holders", "isin", "major_holders", "mutualfund_holders", "news",
    "options", "quarterly_balance_sheet", "quarterly_balancesheet", "quarterly_cash_flow", "quarterly_cashflow", "quarterly_earnings",
    "quarterly_financials", "quarterly_income_stmt", "quarterly_incomestmt", "recommendations",
    "recommendations_summary", "revenue_estimate", "sec_filings", "shares", "splits",
    "sustainability", "ttm_financials", "ttm_income_stmt", "ttm_incomestmt", "upgrades_downgrades",
    "valuation"
]

METHODS = [
    "get_actions", "get_analyst_price_targets", "get_balance_sheet", "get_balancesheet",
    "get_calendar", "get_capital_gains", "get_cash_flow", "get_cashflow", "get_dividends",
    "get_earnings", "get_earnings_dates", "get_earnings_estimate", "get_earnings_history",
    "get_eps_revisions", "get_eps_trend", "get_fast_info", "get_financials", "get_funds_data",
    "get_growth_estimates", "get_history_metadata", "get_income_stmt", "get_incomestmt",
    "get_info", "get_insider_purchases", "get_insider_roster_holders", "get_insider_transactions",
    "get_institutional_holders", "get_isin", "get_major_holders", "get_mutualfund_holders",
    "get_news", "get_option_chain", "get_recommendations", "get_recommendations_summary",
    "get_revenue_estimate", "get_sec_filings", "get_shares", "get_splits", "get_sustainability",
    "get_ttm_financials", "get_ttm_income_stmt", "get_ttm_incomestmt", "get_quarterly_balancesheet",
    "get_quarterly_cashflow", "get_quarterly_incomestmt", "get_upgrades_downgrades", "get_valuation",
    "history", "option_chain"
]

def create_endpoint(endpoint_name: str):
    # Resolve aliases & prefixes
    target_key = endpoint_name
    if target_key.startswith("get_"):
        target_key = target_key[4:]
    
    aliases_mapping = {
        "balancesheet": "balance_sheet",
        "cashflow": "cash_flow",
        "incomestmt": "income_stmt",
        "quarterly_balancesheet": "quarterly_balance_sheet",
        "quarterly_cashflow": "quarterly_cash_flow",
        "quarterly_incomestmt": "quarterly_income_stmt",
        "ttm_incomestmt": "ttm_income_stmt",
    }
    
    db_key = aliases_mapping.get(target_key, target_key)

    async def get_ticker_field(
        ticker: str,
        db: Session = Depends(get_db),
        current_user: Any = Depends(get_current_user)
    ):
        clean_ticker = ticker.upper().strip()
        if not clean_ticker.endswith(".SA"):
            clean_ticker += ".SA"

        # Check if the ticker exists in the database
        ticker_exists = db.query(Ticker).filter(Ticker.ticker == clean_ticker).first()
        if not ticker_exists:
            # Check raw data as fallback
            raw_exists = db.query(TickerRawData).filter(TickerRawData.ticker == clean_ticker).first()
            if not raw_exists:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Ticker '{clean_ticker}' has not been imported. Please import it first using the fetch endpoint."
                )

        # Special case: history, historical, get_historical_prices
        if db_key in ("history", "historical", "get_historical_prices"):
            prices = db.query(HistoricalPrice).filter(HistoricalPrice.ticker == clean_ticker).order_by(HistoricalPrice.date.desc()).all()
            return [
                {
                    "date": p.date.strftime("%Y-%m-%d") if p.date else None,
                    "open": p.open,
                    "high": p.high,
                    "low": p.low,
                    "close": p.close,
                    "volume": p.volume,
                    "dividends": p.dividends,
                    "stock_splits": p.stock_splits
                }
                for p in prices
            ]

        # Check if it exists in the DB
        raw_record = db.query(TickerRawData).filter(
            TickerRawData.ticker == clean_ticker,
            TickerRawData.data_key == db_key
        ).first()

        if raw_record:
            if isinstance(raw_record.data_json, dict) and "_error" in raw_record.data_json:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Stored data for key '{db_key}' has error: {raw_record.data_json['_error']}"
                )
            return raw_record.data_json

        # Fallback dynamic fetch on-the-fly from yfinance
        try:
            tk = yf.Ticker(clean_ticker)
            # Find attribute/method on the ticker object
            attr_val = getattr(tk, db_key, None)
            if callable(attr_val):
                attr_val = attr_val()
            
            serializable = to_serializable(attr_val)
            if serializable is not None and serializable != [] and serializable != {}:
                # Cache it in the database for future requests
                new_record = TickerRawData(
                    ticker=clean_ticker,
                    data_key=db_key,
                    data_json=serializable,
                    fetched_at=datetime.now()
                )
                db.add(new_record)
                db.commit()
                return serializable
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to fetch attribute '{db_key}' dynamically from yfinance: {str(e)}"
            )

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Data for '{db_key}' not found or empty for ticker '{clean_ticker}'."
        )

    return get_ticker_field

# Register all routes programmatically
ALL_ENDPOINTS = sorted(list(set(ATTRIBUTES + METHODS)))

for endpoint_name in ALL_ENDPOINTS:
    router.add_api_route(
        path=f"/{{ticker}}/{endpoint_name}",
        endpoint=create_endpoint(endpoint_name),
        methods=["GET"],
        name=f"Get {endpoint_name.replace('_', ' ').title()}",
        description=f"Retrieve data for the '{endpoint_name}' attribute/method of yfinance Ticker."
    )
