import hashlib
import os
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime, timezone

# ---------- Путь к SQLite ----------
# Используй переменную окружения DB_FILE или значение по умолчанию
DB_FILE = os.environ.get("DB_FILE", "database.db")
DB_PATH = os.path.abspath(DB_FILE)

# Создаём папку для БД, если указан путь с поддиректориями
db_dir = os.path.dirname(DB_PATH)
if db_dir:
    os.makedirs(db_dir, exist_ok=True)

DATABASE_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ---------- Хэширование паролей ----------
def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${h}"

def verify_password(password: str, hashed: str) -> bool:
    salt, h = hashed.split("$", 1)
    return hashlib.sha256((salt + password).encode()).hexdigest() == h

# ---------- Модели ----------
class AdminUser(Base):
    __tablename__ = "admin_users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    leads = relationship("Lead", back_populates="user")

class Part(Base):
    __tablename__ = "parts"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    price = Column(Integer, nullable=False)
    category = Column(String, nullable=True)
    photo = Column(String, nullable=True)
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Lead(Base):
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True, index=True)
    part_id = Column(Integer, ForeignKey("parts.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    message = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_processed = Column(Integer, default=0)
    part = relationship("Part")
    user = relationship("User", back_populates="leads")

# Создаём таблицы (если их нет)
Base.metadata.create_all(bind=engine)

def init_admin():
    db = SessionLocal()
    if not db.query(AdminUser).filter_by(username="admin").first():
        db.add(AdminUser(username="admin", password="admin123"))
        db.commit()
    db.close()

init_admin()