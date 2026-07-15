from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from config import DATABASE_PATH
from models import Base, IntrusionLog

DATABASE_DIR = Path(DATABASE_PATH).parent
DATABASE_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DATABASE_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    if "intrusion_logs" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("intrusion_logs")}
        if "embeddings_path" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE intrusion_logs ADD COLUMN embeddings_path VARCHAR(255)"))


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
