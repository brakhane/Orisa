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

from bisect import bisect
from contextlib import contextmanager
from datetime import datetime, timedelta
from enum import Flag, auto, Enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    BigInteger,
    Integer,
    SmallInteger,
    String,
    Table,
    ForeignKey,
    create_engine,
    func,
    cast,
    desc,
)
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.orderinglist import ordering_list
from sqlalchemy.orm import backref, raiseload, relationship, sessionmaker
import sqlalchemy.types as types

from .config import DATABASE_URI

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
    __tablename__ = "user"

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

    teams = association_proxy("team_membership", "team")

    def __repr__(self):
        return f"<User(id={self.id}, discord_id={self.discord_id})>"


class Handle(Base):
    "Base class for gamer handles (BattleTag, Gamertag, PSN ID in the future)"
    __tablename__ = "handle"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, nullable=False)

    current_sr_id = Column(Integer, ForeignKey("sr.id"))
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
    __tablename__ = "sr"

    RANK_CUTOFF = (1500, 2000, 2500, 3000, 3500, 4000)

    id = Column(Integer, primary_key=True, index=True)
    handle_id = Column(
        Integer, ForeignKey("handle.id"), nullable=False, index=True
    )

    handle = relationship(
        "Handle", back_populates="sr_history", foreign_keys=[handle_id]
    )
    timestamp = Column(DateTime, nullable=False)
    value = Column(SmallInteger)

    @property
    def rank(self):
        return bisect(self.RANK_CUTOFF, self.value) if self.value is not None else None

    def __repr__(self):
        return f"<SR(id={self.id}, value={self.value})>"


class GuildConfigJson(Base):
    __tablename__ = "guild_config"

    id = Column(BigInteger, primary_key=True, index=True)

    config = Column(String, nullable=False)


#### Tournament stuff ####


class MemberType(Enum):
    MEMBER = auto()
    CAPTAIN = auto()


class Team(Base):
    __tablename__ = "team"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)

    members = association_proxy("membership", "user")
    matches = relationship("Match", primaryjoin="or_(Match.team_a_id==Team.id, Match.team_b_id==Team.id)", order_by="desc(Match.id)", lazy="dynamic")

    def __repr__(self):
        return f"<Team(id={self.id}, name={self.name})>"

    def __str__(self):
        return self.name


class TeamMembership(Base):
    __tablename__ = "team_membership"

    team_id = Column(Integer, ForeignKey("team.id"), primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id"), primary_key=True)

    position = Column(Integer, nullable=False)
    member_type = Column(types.Enum(MemberType), nullable=False)
    roles = Column(RoleType, nullable=False, default=Role.NONE)

    team = relationship("Team", backref=backref("membership", order_by=lambda: TeamMembership.position, collection_class=ordering_list("position")))
    user = relationship("User", backref=backref("team_membership", cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<TeamMembership(team={self.team}, user={self.user}, position={self.position}, member_type={self.member_type}, roles={self.roles})>"


team_tournament_assoc = Table("team_tournament", Base.metadata,
    Column("team_id", Integer, ForeignKey("team.id"), primary_key=True),
    Column("tournament_id", Integer, ForeignKey("tournament.id"), primary_key=True)
)

class Tournament(Base):
    __tablename__ = "tournament"
    id = Column(Integer, primary_key=True, index=True)

    name = Column(String, nullable=False)
    teams = relationship(
        "Team",
        secondary=team_tournament_assoc,
        backref="tournaments"
    )

    guild_id = Column(BigInteger, nullable=True)
    info_channel_id = Column(BigInteger, nullable=True)

    def __repr__(self):
        return f"<Tournament id={self.id}, name={self.name}>"


team_stage_assoc = Table("team_stage", Base.metadata,
    Column("team_id", Integer, ForeignKey("team.id"), primary_key=True),
    Column("stage_id", Integer, ForeignKey("stage.id"), primary_key=True)
)

class Stage(Base):
    __tablename__ = "stage"
    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, nullable=False)
    name = Column(String)

    position = Column(Integer)
    tournament_id = Column(Integer, ForeignKey("tournament.id"), nullable=False, index=True)
    tournament = relationship("Tournament", backref=backref("stages", lazy="dynamic", order_by=lambda: Stage.position, collection_class=ordering_list("position")))

    teams = relationship(
        "Team",
        secondary=team_stage_assoc
    )

    guild_id = Column(BigInteger)
    result_channel_id = Column(BigInteger)

    __mapper_args__ = {
        'polymorphic_identity': 'stage',
        'polymorphic_on': type,
        'with_polymorphic': '*',
    }

    def __repr__(self):
        return f"<Stage id={self.id}, type={self.type}, {len(self.teams)} teams>"


class RoundRobinStage(Stage):
    __tablename__ = "roundrobin"

    id = Column(Integer, ForeignKey('stage.id'), primary_key=True, index=True)

    leagues = relationship("League", backref="stage")

    __mapper_args__ = {
        'polymorphic_identity': 'R'
    }

    def __repr__(self):
        return f"<RoundRobinStage id={self.id}, name={self.name}, {len(self.teams)} teams>"


class KnockoutStage(Stage):
    __tablename__ = "knockout"

    id = Column(Integer, ForeignKey('stage.id'), primary_key=True, index=True)

    matches = relationship(
        "Match",
        backref="stage",
        order_by="Match.position",
        collection_class=ordering_list("position"),
    )

    __mapper_args__ = {
        'polymorphic_identity': 'K',
    }

    def __repr__(self):
        return f"<KnockoutStage id={self.id}, name={self.name}>"


team_league_assoc = Table("team_league", Base.metadata,
    Column("team_id", Integer, ForeignKey("team.id"), primary_key=True),
    Column("league_id", Integer, ForeignKey("league.id"), primary_key=True)
)

class League(Base):
    __tablename__ = "league"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=True)
    teams = relationship(
        "Team",
        secondary=team_league_assoc,
        backref="leagues"
    )
    stage_id = Column(Integer, ForeignKey("stage.id"), nullable=False, index=True)
    matchdays = relationship("Matchday", backref=backref("league", order_by=lambda: Stage.position, collection_class=ordering_list("position")))

    def standings(self, session, num_days=None):

        def points_query(a_or_b):
            if a_or_b == "a":
                t_id, p_for, p_against = Match.team_a_id, Match.points_a, Match.points_b
            else:
                t_id, p_for, p_against = Match.team_b_id, Match.points_b, Match.points_a

            return (
                session.query(
                    t_id.label("t"), 
                    func.sum(p_for).label("points"), 
                    cast(func.total(p_for > p_against), Integer).label("won"), 
                    cast(func.total(p_for == p_against), Integer).label("drawn"),
                    cast(func.total(p_for < p_against), Integer).label("lost")
                )
                .filter(Match.matchday_id.in_(md.id for md in self.matchdays[:num_days]))
                .filter(t_id.in_(t.id for t in self.teams))
                .group_by("t")
                .subquery())

        def no_null(x):
            return func.coalesce(x, 0)

        qa, qb = map(points_query, "ab")

        return (
            session.query(
                Team,
                (no_null(qa.c.points) + no_null(qb.c.points)).label("points"),
                (no_null(qa.c.won) + no_null(qb.c.won)).label("won"),
                (no_null(qa.c.drawn) + no_null(qb.c.drawn)).label("drawn"),
                (no_null(qa.c.lost) + no_null(qb.c.lost)).label("lost"),
            )
            .outerjoin(qa, qa.c.t==Team.id)
            .outerjoin(qb, qb.c.t==Team.id)
            .filter(Team.id.in_(x.id for x in self.teams))
            .order_by(desc("points")))

class Matchday(Base):
    __tablename__ = "matchday"

    id = Column(Integer, primary_key=True, index=True)
    league_id = Column(Integer, ForeignKey("league.id"), nullable=False, index=True)
    position = Column(SmallInteger)
    matches = relationship(
        "Match", 
        backref="matchday",
        order_by="Match.position",
        collection_class=ordering_list("position"),
    )   


class Match(Base):
    __tablename__ = "match"
    id = Column(Integer, primary_key=True, index=True)
    # teams can yet be undecided in a knockout stage
    team_a_id = Column(Integer, ForeignKey("team.id"), nullable=True, index=True)
    team_b_id = Column(Integer, ForeignKey("team.id"), nullable=True, index=True)
    team_a = relationship("Team", foreign_keys=team_a_id)
    team_b = relationship("Team", foreign_keys=team_b_id)

    stage_id  = Column(Integer, ForeignKey("stage.id"), index=True)
    matchday_id = Column(Integer, ForeignKey("matchday.id"), index=True)

    # position for match day or knockout stage
    position = Column(SmallInteger)

    score_a = Column(Integer)
    score_b = Column(Integer)

    # For leagues
    points_a = Column(Integer)
    points_b = Column(Integer)

    def __repr__(self):
        return f"<Match({self.team_a} vs {self.team_b}, {len(list(self.matches))} games, {self.score_a}:{self.score_b}, {self.points_a}-{self.points_b})>"

    def __str__(self):
        if self.team_a is None:
            if self.team_b is not None:
                return f"({self.team_b} has a bye)"
            else:
                return "(No teams)"
        elif self.team_b is None:
            return f"({self.team_a} has a bye)"
        else:
            return f"{self.team_a} vs {self.team_b}"


class Game(Base):
    __tablename__ = "game"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, nullable=True, index=True)

    position = Column(Integer, nullable=True)
    match_id = Column(Integer, ForeignKey("match.id"), nullable=True, index=True)
    match = relationship("Match", backref=backref("games", lazy="dynamic"))
    results = relationship("MapResult", backref="game")

    score_a = Column(Integer)
    score_b = Column(Integer)

    def __repr__(self):
        return f"<Game date={self.date}, position={self.position}, match={self.match}, results={self.results}, matchscore={self.score_a}:{self.score_b}>"


class MapResult(Base):
    __tablename__ = "mapresult"

    id = Column(Integer, primary_key=True, index=True)
    map_id = Column(Integer, ForeignKey("map.id"))
    map = relationship("Map")
    game_id = Column(Integer, ForeignKey("game.id"))

    score_a = Column(Integer)
    score_b = Column(Integer)

    def __repr__(self):
        return f"<MapResult map={self.map}, mapscore={self.score_a}:{self.score_b}>"


class Map(Base):
    __tablename__ = "map"
   
    class Type(Enum):
        ASSAULT = auto()
        CONTROL = auto()
        ESCORT = auto()
        HYBRID = auto()

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    
    type = Column(types.Enum(Type), nullable=False)

    def __repr__(self):
        return f"<Map {self.name}>"

    def __str__(self):
        return self.name


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

    def get_min_max_sr(self, session, discord_ids):
        return (
            session.query(func.min(SR.value), func.max(SR.value))
            .join(Handle.current_sr, User)
            .filter(Handle.position == 0)
            .filter(User.discord_id.in_(discord_ids))
            .one()
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
