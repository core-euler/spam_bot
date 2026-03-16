import os
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Text,
    DateTime, Boolean, ForeignKey, Table
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/bot.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# Связь many-to-many: рассылка ↔ чаты
campaign_chats = Table(
    "campaign_chats",
    Base.metadata,
    Column("campaign_id", Integer, ForeignKey("campaigns.id")),
    Column("chat_id", Integer, ForeignKey("chats.id")),
)


class Chat(Base):
    __tablename__ = "chats"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    username = Column(String(255), nullable=True)
    chat_id = Column(String(100), nullable=True)
    delay_seconds = Column(Integer, default=0)
    note = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    logs = relationship("SendLog", back_populates="chat")


class AdMessage(Base):
    __tablename__ = "ad_messages"

    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    text = Column(Text, nullable=False)
    media_file_id = Column(String(255), nullable=True)
    media_type = Column(String(50), nullable=True)
    parse_mode = Column(String(20), default="HTML")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    campaigns = relationship("Campaign", back_populates="ad_message")


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    ad_message_id = Column(Integer, ForeignKey("ad_messages.id"))

    scheduled_at = Column(DateTime, nullable=True)
    repeat_type = Column(String(50), nullable=True)
    repeat_interval = Column(Integer, nullable=True)

    status = Column(String(50), default="draft")
    tg_scheduled_msg_ids = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    last_run_at = Column(DateTime, nullable=True)

    ad_message = relationship("AdMessage", back_populates="campaigns")
    chats = relationship("Chat", secondary=campaign_chats)
    logs = relationship("SendLog", back_populates="campaign")


class SendLog(Base):
    """Журнал попыток отправки"""
    __tablename__ = "send_logs"

    id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=False)
    status = Column(String(20), nullable=False)   # sent / failed
    error = Column(Text, nullable=True)
    sent_at = Column(DateTime, default=datetime.utcnow)

    campaign = relationship("Campaign", back_populates="logs")
    chat = relationship("Chat", back_populates="logs")


def init_db():
    os.makedirs("data", exist_ok=True)
    Base.metadata.create_all(bind=engine)
    print("✅ База данных инициализирована")


def get_db():
    return SessionLocal()
