# Orisa, a simple Discord bot with good intentions
# Copyright (C) 2018 Dennis Brakhane
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, version 3 only
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
from datetime import datetime, timedelta

from sqlalchemy import (Column, DateTime, Integer, String,
                        create_engine)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URI

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    discord_id = Column(Integer, unique=True, nullable=False, index=True)
    battle_tag = Column(String, nullable=False)
    sr = Column(Integer)
    last_update = Column(DateTime, index=True)
    error_count = Column(Integer, nullable=False, default=0)
    format = Column(String, nullable=False)
    highest_rank = Column(Integer)

    def __repr__(self):
        return (f'User(id={self.id}, discord_id={self.discord_id}, battle_tag={self.battle_tag}, sr={self.sr}, '
                f'format={self.format}, last_update={self.last_update}, error_count={self.error_count}, '
                f'highest_rank={self.highest_rank})')


class Database:

    def __init__(self):
        engine = create_engine(DATABASE_URI)
        self.Session = sessionmaker(bind=engine)
        Base.metadata.create_all(engine)

    def by_id(self, session, id):
        return session.query(User).filter_by(id=id).one_or_none()

    def by_discord_id(self, session, discord_id):
        return session.query(User).filter_by(discord_id=discord_id).one_or_none()

    def _sync_delay(self, error_count):
        if error_count == 0:
            return timedelta(minutes=60)
        elif 0 < error_count < 3:
            return timedelta(minutes=5) # we actually want to try again fast, in case it was a temporary problem
        elif 3 <= error_count < 5:
            return timedelta(minutes=90) # ok, the error's not going away, so wait longer
        elif 5 <= error_count < 10:
            # exponential backoff
            return timedelta(minutes=100+20*(error_count-5)**2)
        else:
            return timedelta(days=1)

    def get_to_be_synced(self, session):
        min_time = datetime.now() - min(self._sync_delay(x) for x in range(10))
        results = session.query(User).filter(User.last_update <= min_time).all()
        return [result for result in results if result.last_update <= datetime.now() - self._sync_delay(result.error_count)]
