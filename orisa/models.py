# Orisa, a simple Discord bot with good intentions
# Copyright (C) 2018, 2019 Dennis Brakhane
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
import typing

from contextlib import contextmanager
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
    func,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.orderinglist import ordering_list
from sqlalchemy.orm import raiseload, relationship, sessionmaker
import sqlalchemy.types as types

from .config import DATABASE_URI
from .utils import sr_to_rank, TDS

Base = declarative_base()


class Role(Flag):
    NONE = 0
    DPS = auto()
    MAIN_TANK = auto()
    OFF_TANK = auto()
    SUPPORT = auto()

    def format(self):
        names = {
            Role.DPS: "Damage",
            Role.MAIN_TANK: "Main Tank",
            Role.OFF_TANK: "Off Tank",
            Role.SUPPORT: "Support",
        }
    
        return ", ".join(names[r] for r in Role if r and r in self)



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

    handles = relationship(
        "Handle",
        back_populates="user",
        order_by="Handle.position",
        collection_class=ordering_list("position"),
        lazy="joined",
        cascade="all, delete-orphan",
    )
    last_problematic_nickname_warning = Column(DateTime)

    roles = Column(RoleType, nullable=False, default=Role.NONE)

    always_show_sr = Column(Boolean, nullable=False, default=False)

    def __repr__(self):
        return f"<User(id={self.id}, discord_id={self.discord_id})>"


class Handle(Base):
    "Base class for gamer handles (BattleTag, Gamertag, PSN ID in the future)"
    __tablename__ = "handle"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    current_sr_id = Column(Integer, ForeignKey("srs.id"))
    position = Column(Integer, nullable=False)

    user = relationship("User", back_populates="handles")

    sr_history = relationship(
        "SR",
        order_by="desc(SR.timestamp)",
        cascade="all, delete-orphan",
        lazy="dynamic",
        foreign_keys="SR.handle_id",
        back_populates="handle",
    )
    current_sr = relationship(
        "SR",
        uselist=False,
        foreign_keys=[current_sr_id],
        post_update=True,
        lazy="joined",
    )

    error_count = Column(Integer, nullable=False, default=0)


    __mapper_args__ = {
        'polymorphic_on': type,
    }

    @property
    def sr(self):
        return self.current_sr.values if self.current_sr else None

    @property
    def rank(self):
        return self.current_sr.ranks if self.current_sr else None

    @property
    def last_update(self):
        return self.current_sr.timestamp if self.current_sr else None

    def update_sr(self, new_srs, *, timestamp=None):
        if timestamp is None:
            timestamp = datetime.utcnow()

        if new_srs is None:
            new_srs = TDS(None, None, None)

        if (
            len(self.sr_history[:2]) > 1
            and self.sr_history[0].values == self.sr_history[1].values
        ):
            sr_obj = self.sr_history[0]
            sr_obj.timestamp = timestamp
            sr_obj.values = new_srs
        else:
            sr_obj = SR(timestamp=timestamp, tank=new_srs.tank, damage=new_srs.damage, support=new_srs.support)
            self.sr_history.append(
                sr_obj
            )  # sqlalchemy dynamic wrapper does not support prepend

        self.current_sr = sr_obj


    def __repr__(self):
        return f"<Handle(id={self.id})>"


class BattleTag(Handle):
    blizzard_id = Column(
        Integer, nullable=True, index=True
    )  # nullable because of single table inheritance
    battle_tag = Column(String)

    __mapper_args__ = {
        'polymorphic_identity': 'battletag'
    }

    desc = "BattleTag"
    blizzard_url_type = "pc"

    @property
    def handle(self):
        return self.battle_tag

    @handle.setter
    def handle(self, value):
        self.battletag = value

    @property
    def external_id(self):
        return self.blizzard_id

    def __str__(self):
        return f"BT/{self.battle_tag} ({self.sr} SR)" if self.sr else f"{self.battle_tag} (Unranked)"

    def __repr__(self):
        return f"<BattleTag(id={self.id} tag={self.battle_tag})>"


class Gamertag(Handle):
    xbl_id = Column(
        String, index=True
    )
    gamertag = Column(String)

    __mapper_args__ = {
        'polymorphic_identity': 'gamertag'
    }

    desc = "Gamertag"
    blizzard_url_type = "xbl"

    @property
    def handle(self):
        return self.gamertag

    @handle.setter
    def handle(self, value):
        self.gamertag = value

    @property
    def external_id(self):
        return self.xbl_id


    def __str__(self):
        return f"GT/{self.gamertag} ({self.sr} SR)" if self.sr else f"{self.gamertag} (Unranked)"

    def __repr__(self):
        return f"<Gamertag(id={self.id} gamertag={self.gamertag})>"


class SR(Base):
    __tablename__ = "srs"

    id = Column(Integer, primary_key=True, index=True)
    handle_id = Column(
        Integer, ForeignKey("handle.id"), nullable=False, index=True
    )

    handle = relationship(
        "Handle", back_populates="sr_history", foreign_keys=[handle_id]
    )
    timestamp = Column(DateTime, nullable=False)
    tank = Column(SmallInteger)
    damage = Column(SmallInteger)
    support = Column(SmallInteger)

    @property
    def values(self):
        return TDS(tank=self.tank, damage=self.damage, support=self.support)

    @values.setter
    def values(self, values):
        self.tank = values.tank
        self.damage = values.damage
        self.support = values.support

    @property
    def ranks(self):
        return TDS(*[sr_to_rank(val) for val in self.values])

    def __repr__(self):
        return f"<SR(id={self.id}, values={self.values})>"


class GuildConfigJson(Base):
    __tablename__ = "guild_configs"

    id = Column(BigInteger, primary_key=True, index=True)

    config = Column(String, nullable=False)


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

    def handle_by_id(self, session, id):
        return session.query(Handle).filter_by(id=id).one_or_none()

    def user_by_discord_id(self, session, discord_id):
        return session.query(User).filter_by(discord_id=discord_id).one_or_none()

    def get_srs(self, session, discord_ids):
        return (
            session.query(SR)
            .join(Handle.current_sr, User)
            .filter(Handle.position == 0)
            .filter(User.discord_id.in_(discord_ids))
            .all()
        )

    def _sync_delay(self, error_count):
        if error_count == 0:
            # slight randomization to avoid having all
            # battletags update at the same time if Orisa didn't run
            # for a while
            return timedelta(minutes=random.randint(90, 100))
        elif 0 < error_count < 3:
            return timedelta(
                minutes=5
            )  # we actually want to try again fast, in case it was a temporary problem
        elif 3 <= error_count < 5:
            return timedelta(
                minutes=120
            )  # ok, the error's not going away, so wait longer
        elif 5 <= error_count < 10:
            # exponential backoff
            return timedelta(minutes=180 + 20 * (error_count - 5) ** 2)
        else:
            return timedelta(days=1)

    def get_handles_to_be_synced(self, session):
        results = (
            session.query(Handle)
            .join(Handle.current_sr)
            .filter(SR.timestamp <= datetime.utcnow() - self._min_delay)
            .all()
        )
        return [
            result.id
            for result in results
            if result.last_update
            <= datetime.utcnow() - self._sync_delay(result.error_count)
        ]
