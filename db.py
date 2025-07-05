from sqlalchemy import create_engine, Column, Integer, String, Date, Text, TIMESTAMP
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime

# Настройка базы SQLite
engine = create_engine('sqlite:///medkit.db', echo=True)  # echo=True для логов запросов, можно убрать
Session = sessionmaker(bind=engine)
Base = declarative_base()

class Medicine(Base):
    __tablename__ = 'medicines'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    dosage = Column(String, nullable=True)
    quantity = Column(Integer, default=1)
    expiration = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    added_at = Column(TIMESTAMP, default=datetime.datetime.utcnow)


def init_db():
    """Создаёт таблицы в базе данных"""
    Base.metadata.create_all(engine)


if __name__ == '__main__':
    init_db()
    print("База данных medkit.db инициализирована")
