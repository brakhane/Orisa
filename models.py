import curio
from datetime import datetime, timedelta

from sqlalchemy import (Boolean, Column, DateTime, Integer, String,
                        create_engine)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URI, ECHO_SQL

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    discord_id = Column(Integer, unique=True, nullable=False)
    battle_tag = Column(String, nullable=False)
    sr = Column(Integer)
    last_update = Column(DateTime)
    error_count = Column(Integer, nullable=False, default=0)
    format = Column(String, nullable=False)

    def __repr__(self):
        return (f'User(id={self.id}, discord_id={self.discord_id}, battle_tag={self.battle_tag}, sr={self.sr}, '
                f'format={self.format}, last_update={self.last_update}, error_count={self.error_count})')


class Database:

    def __init__(self):
        engine = create_engine(DATABASE_URI, echo=ECHO_SQL)
        self.Session = sessionmaker(bind=engine)
        Base.metadata.create_all(engine)

    def by_id(self, session, id):
        return session.query(User).filter_by(id=id).one_or_none()

    def by_discord_id(self, session, discord_id):
        return session.query(User).filter_by(discord_id=discord_id).one_or_none()

    def _sync_delay(self, error_count):
        if 0 <= error_count < 2:
            return timedelta(minutes=10)
        elif 2 <= error_count < 5:
            return timedelta(minutes=30)
        elif 5 <= error_count < 10:
            # exponential backoff
            return timedelta(minutes=60+10*(error_count-5)**2)
        else:
            return timedelta(days=1)

    def get_to_be_synced(self, session):
        min_time = datetime.now() - self._sync_delay(0)
        results = session.query(User).filter(User.last_update <= min_time).all()
        return [result.id for result in results if result.last_update <= datetime.now() - self._sync_delay(result.error_count)]