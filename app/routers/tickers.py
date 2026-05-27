import math
import json
from datetime import datetime, date
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
import yfinance as yf
import pandas as pd
from deep_translator import GoogleTranslator

def translate_info_fields(info: dict) -> dict:
    """Translates the 'longBusinessSummary' from English to Portuguese using deep-translator."""
    if not isinstance(info, dict):
        return info
    
    summary = info.get("longBusinessSummary")
    if isinstance(summary, str) and summary.strip():
        try:
            translated = GoogleTranslator(source="auto", target="pt").translate(summary)
            if translated:
                info["longBusinessSummary"] = translated
        except Exception as e:
            print(f"Error translating longBusinessSummary: {e}")
            
    return info

from app.database import get_db
from app.models import TickerRawData, HistoricalPrice, Ticker
from app.schemas import (
    TickerFetchRequest,
    TickerFetchResponse,
    HistoricalPriceResponse,
    TickerRawDataResponse,
    TickerSyncResponse
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

def perform_ticker_sync(
    ticker_name: str,
    db: Session,
    period: Optional[str] = "1mo",
    sync_raw: bool = True
) -> dict:
    """
    Downloads stock data from yfinance for a given B3 ticker symbol and persists/updates
    historical prices and raw JSON properties in the PostgreSQL database.
    """
    ticker = ticker_name.upper().strip()
    if not ticker.endswith(".SA"):
        ticker += ".SA"

    # Auto-detect latest price in DB to run incrementally if no explicit period is provided
    if period is None:
        latest_price = db.query(HistoricalPrice)\
            .filter(HistoricalPrice.ticker == ticker)\
            .order_by(HistoricalPrice.date.desc())\
            .first()
    else:
        latest_price = None

    tk = yf.Ticker(ticker)
    try:
        if latest_price:
            start_date_str = latest_price.date.strftime("%Y-%m-%d")
            hist = tk.history(start=start_date_str, auto_adjust=True)
        else:
            hist = tk.history(period=period or "1mo", auto_adjust=True)
    except Exception as e:
        raise ValueError(f"Failed to fetch history for ticker '{ticker_name}': {str(e)}")

    if hist.empty and not latest_price:
        raise ValueError(f"No yfinance data found for ticker '{ticker_name}'. Please check the ticker name.")

    now = datetime.now()

    try:
        # Update or create the Ticker registry record (Idempotent, no duplicates)
        ticker_record = db.query(Ticker).filter(Ticker.ticker == ticker).first()
        if ticker_record:
            ticker_record.sync_date = now
        else:
            ticker_record = Ticker(ticker=ticker, sync_date=now)
            db.add(ticker_record)

        # 1️⃣ Insert / Update historical prices (Idempotent, update sync_date only on actual changes)
        existing_prices = {
            p.date: p for p in db.query(HistoricalPrice).filter(HistoricalPrice.ticker == ticker).all()
        }

        visited_dates = set()
        historical_records_count = 0
        new_records = []
        if not hist.empty:
            for date_val, row in hist.iterrows():
                row_date = date_val.date()
                visited_dates.add(row_date)
                new_open = safe_float(row.get("Open"))
                new_high = safe_float(row.get("High"))
                new_low = safe_float(row.get("Low"))
                new_close = safe_float(row.get("Close"))
                new_volume = safe_float(row.get("Volume"))
                new_dividends = safe_float(row.get("Dividends"))
                new_splits = safe_float(row.get("Stock Splits"))

                existing_p = existing_prices.get(row_date)
                if existing_p:
                    is_changed = (
                        existing_p.open != new_open or
                        existing_p.high != new_high or
                        existing_p.low != new_low or
                        existing_p.close != new_close or
                        existing_p.volume != new_volume or
                        existing_p.dividends != new_dividends or
                        existing_p.stock_splits != new_splits
                    )
                    if is_changed:
                        existing_p.open = new_open
                        existing_p.high = new_high
                        existing_p.low = new_low
                        existing_p.close = new_close
                        existing_p.volume = new_volume
                        existing_p.dividends = new_dividends
                        existing_p.stock_splits = new_splits
                        existing_p.sync_date = now
                else:
                    new_record = HistoricalPrice(
                        ticker=ticker,
                        date=row_date,
                        open=new_open,
                        high=new_high,
                        low=new_low,
                        close=new_close,
                        volume=new_volume,
                        dividends=new_dividends,
                        stock_splits=new_splits,
                        sync_date=now
                    )
                    new_records.append(new_record)
                historical_records_count += 1

        if new_records:
            db.bulk_save_objects(new_records)

        # Delete database records that are no longer in yfinance history within the fetched range
        if not hist.empty:
            min_date = hist.index.min().date()
            max_date = hist.index.max().date()
            for d, p in existing_prices.items():
                if min_date <= d <= max_date and d not in visited_dates:
                    db.delete(p)

        # 2️⃣ Insert / Update other keys (flexible JSON, update fetched_at only on actual changes)
        keys_saved = []
        if sync_raw:
            existing_raw = {
                r.data_key: r for r in db.query(TickerRawData).filter(TickerRawData.ticker == ticker).all()
            }

            visited_keys = set()
            for key in KEYS_TO_FETCH:
                try:
                    data = getattr(tk, key, None)
                    if callable(data):
                        data = data()
                    
                    if key == "info" and isinstance(data, dict):
                        data = translate_info_fields(data)
                    
                    serializable = to_serializable(data)
                    if serializable is None or serializable == [] or serializable == {}:
                        continue

                    visited_keys.add(key)
                    existing_r = existing_raw.get(key)
                    if existing_r:
                        if existing_r.data_json != serializable:
                            existing_r.data_json = serializable
                            existing_r.fetched_at = now
                    else:
                        new_raw = TickerRawData(
                            ticker=ticker,
                            data_key=key,
                            data_json=serializable,
                            fetched_at=now
                        )
                        db.add(new_raw)
                    keys_saved.append(key)
                except Exception as e:
                    error_json = {"_error": str(e)}
                    visited_keys.add(key)
                    existing_r = existing_raw.get(key)
                    if existing_r:
                        if existing_r.data_json != error_json:
                            existing_r.data_json = error_json
                            existing_r.fetched_at = now
                    else:
                        new_raw = TickerRawData(
                            ticker=ticker,
                            data_key=key,
                            data_json=error_json,
                            fetched_at=now
                        )
                        db.add(new_raw)
                    keys_saved.append(key)

            # Delete raw keys that are no longer present in yfinance response
            for k, r in existing_raw.items():
                if k not in visited_keys:
                    db.delete(r)

        db.commit()

        return {
            "ticker": ticker,
            "keys_fetched": keys_saved,
            "historical_records_count": historical_records_count,
            "fetched_at": now,
            "sync_date": now
        }

    except Exception as e:
        db.rollback()
        raise RuntimeError(f"Database transaction failed during save: {str(e)}")


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
    try:
        res = perform_ticker_sync(payload.ticker, db, period="max", sync_raw=True)
        return TickerFetchResponse(
            ticker=res["ticker"],
            keys_fetched=res["keys_fetched"],
            historical_records_count=res["historical_records_count"],
            message=f"Successfully imported stock data for {res['ticker']}",
            fetched_at=res["fetched_at"],
            sync_date=res["sync_date"]
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/{ticker}/sync", response_model=TickerSyncResponse)
def sync_ticker(
    ticker: str,
    period: Optional[str] = Query("1mo", description="yfinance history period (e.g. 1d, 5d, 1mo, 1y, max)"),
    sync_raw: bool = Query(True, description="Whether to synchronize raw JSON metadata keys"),
    db: Session = Depends(get_db),
    current_user: Any = Depends(get_current_user)
):
    """
    Refresh/synchronize data from yfinance for a specific ticker currently registered in the database.
    """
    clean_ticker = ticker.upper().strip()
    if not clean_ticker.endswith(".SA"):
        clean_ticker += ".SA"

    ticker_record = db.query(Ticker).filter(Ticker.ticker == clean_ticker).first()
    if not ticker_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticker '{clean_ticker}' is not registered in the database. Please use the fetch endpoint to import it first."
        )

    synced = []
    failed = []

    try:
        res = perform_ticker_sync(clean_ticker, db, period=period, sync_raw=sync_raw)
        synced.append({
            "ticker": clean_ticker,
            "historical_records_count": res["historical_records_count"],
            "keys_fetched_count": len(res["keys_fetched"])
        })
        message = f"Successfully synced ticker {clean_ticker}"
    except Exception as e:
        failed.append({
            "ticker": clean_ticker,
            "error": str(e)
        })
        message = f"Failed to sync ticker {clean_ticker}"

    return TickerSyncResponse(
        message=message,
        synced_tickers=synced,
        failed_tickers=failed
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
                    "stock_splits": p.stock_splits,
                    "sync_date": p.sync_date.isoformat() if p.sync_date else None
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
            
            if db_key == "info" and isinstance(attr_val, dict):
                attr_val = translate_info_fields(attr_val)
            
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

ENDPOINT_DESCRIPTIONS: Dict[str, str] = {
    "info": "Retrieve a comprehensive dictionary of corporate, financial, and market metadata for the security (e.g., business summary, sector, market cap, valuation ratios).",
    "fast_info": "Retrieve fast-access key market data and metadata (e.g., currency, exchange, shares outstanding, previous close, timezone).",
    "history_metadata": "Retrieve metadata related to the ticker's historical market database parameters.",
    "calendar": "Retrieve upcoming corporate events including earnings announcements and revenue disclosure dates.",
    "sec_filings": "Retrieve the list of recent SEC filings submitted by the company.",
    "balance_sheet": "Retrieve the annual balance sheet statement showing assets, liabilities, and equity.",
    "balancesheet": "Retrieve the annual balance sheet statement (alias).",
    "income_stmt": "Retrieve the annual income statement showing revenues, expenses, and profits.",
    "incomestmt": "Retrieve the annual income statement (alias).",
    "cash_flow": "Retrieve the annual cash flow statement showing cash inflows and outflows.",
    "cashflow": "Retrieve the annual cash flow statement (alias).",
    "financials": "Retrieve key annual financial statement metrics.",
    "quarterly_balance_sheet": "Retrieve the quarterly balance sheet statement.",
    "quarterly_balancesheet": "Retrieve the quarterly balance sheet statement (alias).",
    "quarterly_income_stmt": "Retrieve the quarterly income statement.",
    "quarterly_incomestmt": "Retrieve the quarterly income statement (alias).",
    "quarterly_cash_flow": "Retrieve the quarterly cash flow statement.",
    "quarterly_cashflow": "Retrieve the quarterly cash flow statement (alias).",
    "quarterly_financials": "Retrieve key quarterly financial statement metrics.",
    "earnings": "Retrieve the company's annual historical earnings metrics.",
    "quarterly_earnings": "Retrieve the company's quarterly historical earnings metrics.",
    "earnings_dates": "Retrieve historical and future earnings announcement dates and EPS estimates.",
    "dividends": "Retrieve historical dividend payments and dates.",
    "splits": "Retrieve historical stock split ratios and dates.",
    "actions": "Retrieve both dividend payments and stock split corporate actions.",
    "capital_gains": "Retrieve historical capital gains distributions.",
    "major_holders": "Retrieve breakdown of major share ownership categories (e.g. insiders, institutions).",
    "institutional_holders": "Retrieve the list of top institutional shareholders and their positions.",
    "mutualfund_holders": "Retrieve the list of top mutual fund shareholders and their positions.",
    "insider_transactions": "Retrieve recent insider trading transactions (buying/selling).",
    "insider_purchases": "Retrieve summaries of recent insider purchase activities.",
    "insider_roster_holders": "Retrieve the roster of key company insider shareholders.",
    "recommendations": "Retrieve detailed analyst recommendations and ratings over time.",
    "recommendations_summary": "Retrieve summary statistics of current consensus recommendations.",
    "upgrades_downgrades": "Retrieve history of analyst upgrades, downgrades, and price target changes.",
    "analyst_price_targets": "Retrieve current analyst price targets (low, high, mean, median).",
    "earnings_estimate": "Retrieve consensus analyst EPS estimates for upcoming quarters/years.",
    "revenue_estimate": "Retrieve consensus analyst revenue estimates for upcoming quarters/years.",
    "eps_trend": "Retrieve current trends in consensus EPS estimates.",
    "eps_revisions": "Retrieve frequency and direction of consensus EPS estimate revisions.",
    "growth_estimates": "Retrieve projected growth estimates (e.g., next quarter, next year, next 5 years).",
    "valuation": "Retrieve historical valuation ratios and metrics.",
    "sustainability": "Retrieve Environmental, Social, and Governance (ESG) sustainability scores and ratings.",
    "shares": "Retrieve historical share count outstanding data.",
    "funds_data": "Retrieve ETF/mutual fund specific data (e.g. sector weightings, holdings) if applicable.",
    "ttm_financials": "Retrieve Trailing Twelve Months (TTM) financial metrics.",
    "ttm_income_stmt": "Retrieve Trailing Twelve Months (TTM) income statement metrics.",
    "ttm_incomestmt": "Retrieve Trailing Twelve Months (TTM) income statement metrics (alias).",
    "news": "Retrieve recent news articles and headlines related to the company.",
    "isin": "Retrieve the International Securities Identification Number (ISIN) of the security.",
    "options": "Retrieve available option contract expiration dates.",
    "option_chain": "Retrieve option chains (calls and puts contracts) including strike prices and implied volatility.",
    "history": "Retrieve historical market prices (Open, High, Low, Close, Volume) and corporate actions.",
}

# Register all routes programmatically (filtering out duplicates starting with get_)
ALL_ENDPOINTS = sorted(list(set(
    endpoint[4:] if endpoint.startswith("get_") else endpoint
    for endpoint in (ATTRIBUTES + METHODS)
)))

for endpoint_name in ALL_ENDPOINTS:
    desc = ENDPOINT_DESCRIPTIONS.get(
        endpoint_name,
        f"Retrieve data for the '{endpoint_name}' attribute/method of yfinance Ticker."
    )
    router.add_api_route(
        path=f"/{{ticker}}/{endpoint_name}",
        endpoint=create_endpoint(endpoint_name),
        methods=["GET"],
        name=f"Get {endpoint_name.replace('_', ' ').title()}",
        description=desc
    )
