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
import random

from bisect import bisect
from datetime import datetime, timedelta
from enum import Flag, auto

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    BigInteger,
    Integer,
    SmallInteger,
    String,
    ForeignKey,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.orderinglist import ordering_list
from sqlalchemy.orm import raiseload, relationship, sessionmaker
import sqlalchemy.types as types

from config import DATABASE_URI
from contextlib import contextmanager

Base = declarative_base()


class Role(Flag):
    NONE = 0
    DPS = auto()
    MAIN_TANK = auto()
    OFF_TANK = auto()
    SUPPORT = auto()


class RoleType(types.TypeDecorator):
    pytype = Role
    impl = Integer

    def process_bind_param(self, value, dialect):
        return None if value is None else value.value

    def process_result_value(self, value, dialect):
        return None if value is None else self.pytype(value)

    class comparator_factory(Integer.Comparator):
        def contains(self, other, **kwargs):
            return (self.op("&", return_type=types.Integer)(other)).bool_op("=")(
                other.value
            )


class Cron(Base):
    __tablename__ = "crontab"

    id = Column(String, primary_key=True, index=True)
    last_run = Column(DateTime, nullable=False)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    discord_id = Column(BigInteger, unique=True, nullable=False, index=True)
    format = Column(String, nullable=False)

    battle_tags = relationship(
        "BattleTag",
        back_populates="user",
        order_by="BattleTag.position",
        collection_class=ordering_list("position"),
        lazy="joined",
        cascade="all, delete-orphan",
    )
    last_problematic_nickname_warning = Column(DateTime)

    roles = Column(RoleType, nullable=False, default=Role.NONE)

    def __repr__(self):
        return f"<User(id={self.id}, discord_id={self.discord_id})>"


class BattleTag(Base):
    __tablename__ = "battle_tags"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    current_sr_id = Column(Integer, ForeignKey("srs.id"))
    position = Column(Integer, nullable=False)

    user = relationship("User", back_populates="battle_tags")
    tag = Column(String, nullable=False)

    sr_history = relationship(
        "SR",
        order_by="desc(SR.timestamp)",
        cascade="all, delete-orphan",
        lazy="dynamic",
        foreign_keys="SR.battle_tag_id",
        back_populates="battle_tag",
    )
    current_sr = relationship(
        "SR",
        uselist=False,
        foreign_keys=[current_sr_id],
        post_update=True,
        lazy="joined",
    )

    error_count = Column(Integer, nullable=False, default=0)

    @property
    def sr(self):
        return self.current_sr.value if self.current_sr else None

    @property
    def rank(self):
        return self.current_sr.rank if self.current_sr else None

    @property
    def last_update(self):
        return self.current_sr.timestamp if self.current_sr else None

    def update_sr(self, new_sr, *, timestamp=None):
        if timestamp is None:
            timestamp = datetime.utcnow()

        if (
            len(self.sr_history[:2]) > 1
            and self.sr_history[0].value == self.sr_history[1].value
        ):
            sr_obj = self.sr_history[0]
            sr_obj.timestamp = timestamp
            sr_obj.value = new_sr
        else:
            sr_obj = SR(timestamp=timestamp, value=new_sr)
            self.sr_history.append(
                sr_obj
            )  # sqlalchemy dynamic wrapper does not support prepend

        self.current_sr = sr_obj

    def __str__(self):
        return f"{self.tag} ({self.sr} SR)" if self.sr else f"{self.tag} (Unranked)"

    def __repr__(self):
        return f"<BattleTag(id={self.id}, tag={repr(self.tag)})>"


class SR(Base):
    __tablename__ = "srs"

    RANK_CUTOFF = (1500, 2000, 2500, 3000, 3500, 4000)

    id = Column(Integer, primary_key=True, index=True)
    battle_tag_id = Column(
        Integer, ForeignKey("battle_tags.id"), nullable=False, index=True
    )

    battle_tag = relationship(
        "BattleTag", back_populates="sr_history", foreign_keys=[battle_tag_id]
    )
    timestamp = Column(DateTime, nullable=False)
    value = Column(SmallInteger)

    @property
    def rank(self):
        return bisect(self.RANK_CUTOFF, self.value) if self.value is not None else None

    def __repr__(self):
        return f"<SR(id={self.id}, value={self.value})>"


# WoW stuff


class WowRole(Flag):
    NONE = 0
    MELEE = auto()
    RANGED = auto()
    TANK = auto()
    HEALER = auto()


class WowRoleType(RoleType):
    pytype = WowRole


class WowUser(Base):
    __tablename__ = "wow_users"

    id = Column(Integer, primary_key=True, index=True)
    discord_id = Column(Integer, index=True, nullable=False)
    character_name = Column(String, nullable=False)
    realm = Column(String, nullable=False)
    roles = Column(WowRoleType, nullable=False, default=WowRole.NONE)
    pvp = Column(Boolean, nullable=False, default=False)


class Database:
    def __init__(self):
        engine = create_engine(DATABASE_URI)
        self.Session = sessionmaker(bind=engine, autoflush=False)
        Base.metadata.create_all(engine)

        self._min_delay = min(self._sync_delay(x) for x in range(10))

    @contextmanager
    def session(self):
        session = self.Session()
        try:
            yield session
        finally:
            session.close()

    def user_by_id(self, session, id):
        return session.query(User).filter_by(id=id).one_or_none()

    def tag_by_id(self, session, id):
        return session.query(BattleTag).filter_by(id=id).one_or_none()

    def user_by_discord_id(self, session, discord_id):
        return session.query(User).filter_by(discord_id=discord_id).one_or_none()

    def wow_user_by_discord_id(self, session, discord_id):
        return session.query(WowUser).filter_by(discord_id=discord_id).one_or_none()

    def _sync_delay(self, error_count):
        if error_count == 0:
            # slight randomization to avoid having all
            # battletags update at the same time if Orisa didn't run
            # for a while
            return timedelta(minutes=random.randint(50, 70))
        elif 0 < error_count < 3:
            return timedelta(
                minutes=5
            )  # we actually want to try again fast, in case it was a temporary problem
        elif 3 <= error_count < 5:
            return timedelta(
                minutes=90
            )  # ok, the error's not going away, so wait longer
        elif 5 <= error_count < 10:
            # exponential backoff
            return timedelta(minutes=100 + 20 * (error_count - 5) ** 2)
        else:
            return timedelta(days=1)

    def get_tags_to_be_synced(self, session):
        results = (
            session.query(BattleTag)
            .join(BattleTag.current_sr)
            .filter(SR.timestamp <= datetime.utcnow() - self._min_delay)
            .all()
        )
        return [
            result.id
            for result in results
            if result.last_update
            <= datetime.utcnow() - self._sync_delay(result.error_count)
        ]
