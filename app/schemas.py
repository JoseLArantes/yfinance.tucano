from pydantic import BaseModel, ConfigDict, Field, field_validator
from datetime import date, datetime
from typing import Any, List, Optional

class TickerFetchRequest(BaseModel):
    ticker: str = Field(..., description="The stock ticker to fetch (e.g., PETR4, VALE3)")

    @field_validator("ticker")
    @classmethod
    def clean_ticker(cls, v: str) -> str:
        clean = v.upper().strip()
        if not clean:
            raise ValueError("Ticker cannot be empty")
        return clean

class TickerFetchResponse(BaseModel):
    ticker: str
    keys_fetched: List[str]
    historical_records_count: int
    message: str
    fetched_at: datetime
    sync_date: datetime

class HistoricalPriceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    date: date
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None
    dividends: Optional[float] = None
    stock_splits: Optional[float] = None
    sync_date: Optional[datetime] = None

class TickerRawDataResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticker: str
    data_key: str
    data_json: Any
    fetched_at: datetime

class ApiUserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=100)
    token: Optional[str] = Field(None, min_length=8, max_length=255, description="Optional custom token. If not provided, one will be generated.")

class ApiUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    username: str
    token: str
    created_at: datetime

class TokenRequest(BaseModel):
    username: str = Field(..., description="The username")
    password: str = Field(..., description="The password (which is the user's token)")


class SyncedTickerInfo(BaseModel):
    ticker: str
    historical_records_count: int
    keys_fetched_count: int

class FailedTickerInfo(BaseModel):
    ticker: str
    error: str

class TickerSyncResponse(BaseModel):
    message: str
    synced_tickers: List[SyncedTickerInfo]
    failed_tickers: List[FailedTickerInfo]
