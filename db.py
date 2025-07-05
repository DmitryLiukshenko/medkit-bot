# Импортируем необходимые модули из SQLAlchemy
from sqlalchemy import create_engine, Column, Integer, String, Date
from sqlalchemy.orm import declarative_base, sessionmaker

# Создаём движок подключения к SQLite базе данных с именем "medkit.db"
engine = create_engine("sqlite:///medkit.db")

# Создаём сессию — объект, через который будут производиться запросы к БД
Session = sessionmaker(bind=engine)

# Создаём базовый класс, от которого будут наследоваться все модели
Base = declarative_base()

# Описание таблицы medicines в базе данных
class Medicine(Base):
    __tablename__ = 'medicines'  # Название таблицы

    # Уникальный идентификатор записи (автоинкрементный)
    id = Column(Integer, primary_key=True)

    # Название лекарства (например, "Парацетамол")
    name = Column(String, nullable=False)

    # Дозировка лекарства (например, "500мг")
    dosage = Column(String, nullable=False)

    # Количество единиц лекарства (например, 10 таблеток)
    quantity = Column(Integer, nullable=False)

    # Дата окончания срока годности (тип date)
    expiration = Column(Date, nullable=False)

    # Telegram ID пользователя, которому принадлежит эта запись
    user_id = Column(Integer, nullable=False)

# Функция инициализации базы данных
# Создаёт все таблицы, если они ещё не существуют
def init_db():
    Base.metadata.create_all(engine)
