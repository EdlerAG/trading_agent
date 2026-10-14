from datetime import datetime
from pydantic import BaseModel, field_validator
from sqlalchemy import create_engine, Column, Integer, Float, DateTime, String
from sqlalchemy.orm import declarative_base, sessionmaker

# 1. Налаштування підключення (поки використовуємо SQLite для простоти старту)
DATABASE_URL = "sqlite:///market_data.db"
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 2. Модель SQLAlchemy (як це зберігатиметься в базі)
class KlineDB(Base):
    __tablename__ = "klines"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)
    open_time = Column(DateTime, index=True)
    open_price = Column(Float)
    high_price = Column(Float)
    low_price = Column(Float)
    close_price = Column(Float)
    volume = Column(Float)
    close_time = Column(DateTime)

# Створюємо таблиці в базі
Base.metadata.create_all(bind=engine)

# 3. Модель Pydantic (для жорсткої валідації даних з API Binance)
class KlineSchema(BaseModel):
    symbol: str
    open_time: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    close_time: datetime

    @field_validator('open_time', 'close_time', mode='before')
    def parse_timestamp(cls, value):
        # Binance повертає час у мілісекундах, перетворюємо у стандартний datetime
        if isinstance(value, int):
            return datetime.fromtimestamp(value / 1000.0)
        return value