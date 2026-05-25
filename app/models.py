from sqlalchemy import Column, String, DateTime, Float, Date, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from app.database import Base

class Ticker(Base):
    __tablename__ = "tickers"

    ticker = Column(String(20), primary_key=True, index=True)
    sync_date = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

class TickerRawData(Base):
    __tablename__ = "ticker_raw_data"

    ticker = Column(String(20), primary_key=True, index=True)
    data_key = Column(String(50), primary_key=True)
    data_json = Column(JSONB, nullable=True)
    fetched_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

class HistoricalPrice(Base):
    __tablename__ = "historical_prices"

    ticker = Column(String(20), primary_key=True, index=True)
    date = Column(Date, primary_key=True)
    open = Column(Float, nullable=True)
    high = Column(Float, nullable=True)
    low = Column(Float, nullable=True)
    close = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    dividends = Column(Float, nullable=True)
    stock_splits = Column(Float, nullable=True)

class ApiUser(Base):
    __tablename__ = "api_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    token = Column(String(255), unique=True, index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now())
