import os
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from sqlalchemy import create_engine, Column, Integer, Float, String, DateTime, event, func, text
from sqlalchemy.orm import declarative_base, sessionmaker
import config

Base = declarative_base()


class Trade(Base):
    """Фіксація фактичних торгових угод та біржових комісій"""
    __tablename__ = 'trades'

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    order_id = Column(String(50), nullable=True)
    side = Column(String(10), nullable=False)
    amount_btc = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    realized_pnl = Column(Float, default=0.0)
    fee_usdt = Column(Float, default=0.0, nullable=True)
    note = Column(String(100), default="")


class EquitySnapshot(Base):
    """Посвічковий стан капіталу для моніторингу та побудови графіків"""
    __tablename__ = 'equity_snapshots'

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    balance_usdt = Column(Float, nullable=False)
    position_btc = Column(Float, nullable=False)
    btc_price = Column(Float, nullable=False)
    total_equity = Column(Float, default=0.0, nullable=True)  # Wallet Balance + Unrealized PnL
    unrealized_pnl = Column(Float, default=0.0)
    model_action = Column(Float, default=0.0)


DATABASE_URL = f"sqlite:///{config.DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    echo=False
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute("PRAGMA cache_size=-8000")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def get_db():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        config.logger.error(f"Помилка транзакції БД: {e}")
        raise
    finally:
        session.close()


def _auto_migrate():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE trades ADD COLUMN fee_usdt FLOAT DEFAULT 0.0"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE equity_snapshots ADD COLUMN total_equity FLOAT DEFAULT 0.0"))
        except Exception:
            pass


def init_db():
    Base.metadata.create_all(engine)
    _auto_migrate()
    config.logger.info(f"База даних SQLite (WAL Mode) готова: {config.DB_PATH}")


def record_trade(side: str, amount: float, price: float, order_id: str = None,
                 pnl: float = 0.0, fee: float = 0.0, note: str = ""):
    try:
        with get_db() as session:
            trade = Trade(
                side=side.upper(),
                amount_btc=float(amount),
                price=float(price),
                order_id=str(order_id) if order_id else None,
                realized_pnl=float(pnl),
                fee_usdt=float(fee),
                note=note
            )
            session.add(trade)
    except Exception as e:
        config.logger.error(f"Не вдалося зберегти угоду в БД: {e}")


def record_snapshot(balance: float, pos_btc: float, price: float, un_pnl: float, action: float):
    """Точний ф'ючерсний капітал: Wallet Balance + Unrealized PnL"""
    try:
        total_equity = float(balance) + float(un_pnl)
        with get_db() as session:
            snapshot = EquitySnapshot(
                balance_usdt=float(balance),
                position_btc=float(pos_btc),
                btc_price=float(price),
                total_equity=total_equity,
                unrealized_pnl=float(un_pnl),
                model_action=float(action)
            )
            session.add(snapshot)
    except Exception as e:
        config.logger.error(f"Не вдалося зберегти зріз капіталу в БД: {e}")


def get_daily_pnl() -> float:
    try:
        with get_db() as session:
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
            daily_pnl = session.query(func.sum(Trade.realized_pnl))\
                               .filter(Trade.timestamp >= cutoff_time)\
                               .scalar()
            return float(daily_pnl) if daily_pnl else 0.0
    except Exception as e:
        config.logger.error(f"Помилка розрахунку денного PnL: {e}")
        return 0.0


def cleanup_old_data(days_to_keep: int = 90):
    try:
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
        with get_db() as session:
            deleted_count = session.query(EquitySnapshot)\
                                   .filter(EquitySnapshot.timestamp < cutoff_date)\
                                   .delete()
            if deleted_count > 0:
                config.logger.info(f"Очищено {deleted_count} застарілих записів EquitySnapshot.")
    except Exception as e:
        config.logger.error(f"Помилка очищення старої історії БД: {e}")