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
import curio
from datetime import datetime, timedelta

from sqlalchemy import (Boolean, Column, DateTime, Integer, String,
                        ForeignKey, create_engine)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.orderinglist import ordering_list
from sqlalchemy.orm import raiseload, relationship, sessionmaker

from config import DATABASE_URI

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    discord_id = Column(Integer, unique=True, nullable=False, index=True)
    format = Column(String, nullable=False)
    highest_rank = Column(Integer)
    battle_tags = relationship(
        "BattleTag", back_populates="user", order_by="BattleTag.position", collection_class=ordering_list('position'),
        lazy="joined", cascade="all, delete-orphan")

    def __repr__(self):
        return (f'User(id={self.id}, discord_id={self.discord_id}, battle_tags={repr(self.battle_tags)}, '
                f'format={self.format}, highest_rank={self.highest_rank})')

class BattleTag(Base):
    __tablename__ = 'battle_tags'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    position = Column(Integer, nullable=False)

    user = relationship("User", back_populates="battle_tags")
    tag = Column(String, nullable=False)
    sr = Column(Integer)
    error_count = Column(Integer, nullable=False, default=0)
    last_update = Column(DateTime, index=True)


    def __str__(self):
        return f'{self.tag} ({self.sr} SR)' if self.sr else f'{self.tag} (Unranked)'

    def __repr__(self):
        return (f'<BattleTag(id={self.id}, tag={repr(self.tag)}, user_id={self.user_id}, position={self.position}, sr={self.sr}, last_update={self.last_update}, error_count={self.error_count})>')



class Database:

    def __init__(self):
        engine = create_engine(DATABASE_URI)
        self.Session = sessionmaker(bind=engine, autoflush=False)
        Base.metadata.create_all(engine)

    def user_by_id(self, session, id):
        return session.query(User).filter_by(id=id).one_or_none()

    def tag_by_id(self, session, id):
        return session.query(BattleTag).filter_by(id=id).one_or_none()

    def user_by_discord_id(self, session, discord_id):
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

    def get_tags_to_be_synced(self, session):
        min_time = datetime.now() - min(self._sync_delay(x) for x in range(10))
        results = session.query(BattleTag).filter(BattleTag.last_update <= min_time).all()
        return [result.id for result in results if result.last_update <= datetime.now() - self._sync_delay(result.error_count)]
