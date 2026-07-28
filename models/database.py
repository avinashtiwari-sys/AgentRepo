from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models.lead import Base
from config import DATABASE_URL

# check_same_thread is a SQLite-only arg; passing it to psycopg2 raises.
_is_sqlite = DATABASE_URL.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,  # drop stale connections before use (matters on Postgres)
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
