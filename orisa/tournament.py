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

from .models import (
    Tournament,
    Team,
    TeamMembership,
    Match,
    Stage,
    GroupStage,
    KnockoutStage,
    League,
    LeagueRound,
    Pairing,
    Matchday,
)


def create_round_robin_schedule(num_teams):
    """Create pairings for round robin tournaments/leagues
    Uses the circle method."""
    pool = list(range(num_teams))

    size = num_teams
    # Make number of participants even if necessary
    if num_teams % 2 == 1:
        pool.append(None)
        size += 1

    rounds = []
    for round in range(size - 1):

        rounds.append([(pool[i], pool[size - 1 - i]) for i in range(size // 2)])

        # rotate
        pool.insert(1, pool.pop())

    # Alternate home/away, gives better results (more H/A/H/A sequences) even when balancing later
    rounds = [
        [(pairing[1], pairing[0]) for pairing in pairings] if i % 2 else pairings
        for i, pairings in enumerate(rounds)
    ]


    # Balance Home/Away by using the method described in
    # Sigrid Knust, Michael von Thaden, "Balanced home–away assignments"
    # Discrete Optimization 3 (2006) 354–365
    
    #Home/Away matrix 
    ham = [[0]*num_teams for _ in range(num_teams)]

    # lookup map to find pairing in rounds table
    rounds_ix = {}

    for ri, pairings in enumerate(rounds):
        for pi, pairing  in enumerate(pairings):
            home, away = pairing
            if home is None or away is None:
                continue
            ham[home][away] = 1
            ham[away][home] = -1
            rounds_ix[home, away] = rounds_ix[away, home] = ri, pi

    # imbalance of home/away games; +1 = one more home than away, -3 three more away than home, etc.
    delta = [sum(x) for x in ham]


    def swap_pairing(a, b):
        r,p = rounds_ix[a, b]
        home, away = rounds[r][p]   
        assert (home == a and away == b) or (home == b and away == a)

        rounds[r][p] = away, home
        delta[home] -= 2
        delta[away] += 2
        ham[home][away] = -1
        ham[away][home] = 1


    if num_teams % 2 == 0:

        theta = sum(x>0 for x in delta) - sum(x<0 for x in delta)

        if theta <= 0:
            # at least one team has a higher delta than +1, need to swap a home game to away game
            balance_cond = lambda d: d > 1
            match_cond = lambda team: ham[team_to_balance][team] == 1 and delta[team] <= -1
        else:
            # at least one team has a lower delta than -1, need to swap an away game to a home game
            balance_cond = lambda d: d < -1
            match_cond = lambda team: ham[team_to_balance][team] == -1 and delta[team] >= 1 

        while True:
            for team_to_balance, d in enumerate(delta):
                if balance_cond(d):
                    break  # exit for, team_to_balance is set
            else:  # nobreak
                break  # no more imbalances, we're done
            
            # find a game where the team_to_balance is home/away and the opponent
            # has a negative/positive score. After we swap, we'll have reduced the total imbalance

            for team in range(num_teams):
                if match_cond(team):
                    swap_pairing(team_to_balance, team)
                    break
                else:  # nobreak
                    continue
                break
    
    else:  # num_teams is odd


        while True:

            i = j = None
            for n, d in enumerate(delta):
                if d > 0:
                    i = n
                elif d < 0:
                    j = n
            if i is None:  # j is also None in this case, since sum(delta) = 0
                # no more imbalances, we're done
                break

            # i has more home games than away, j has more away
            if ham[i][j] == 1:
                # easy case, just swap the two
                swap_pairing(i, j)
            else:  # i is playing away, more difficult
                # find team k that plays away on both i and j
                for k in range(num_teams):
                    if ham[i][k] == ham[j][k] == 1:
                        break
                else:
                    raise RuntimeError("This shouldn't happen")
                # swap both
                swap_pairing(i, k)
                swap_pairing(j, k)
                
    return rounds





def create_simple_league_tournament(name, teams, rounds):
    t = Tournament(name=name)
    gs = GroupStage(tournament=t)
    l = League(stage=gs)
    l.teams = gs.teams = t.teams = teams
    for round_id in range(rounds):
        r = LeagueRound(name=f"{name} Round #{round_id+1}", league=l)

        schedule = create_round_robin_schedule(len(teams))

        shuffled_teams = teams.copy()
        random.shuffle(shuffled_teams)

        def team(x):
            if x is None:
                return None
            else:
                return shuffled_teams[x]

        if round_id % 2 == 0:
            day_pairings = [[(team(a), team(b)) for a, b in pairings] for pairings in schedule]
        else:
            day_pairings = [[(team(b), team(a)) for a, b in pairings] for pairings in schedule]

        for day_nr, pairings in enumerate(day_pairings):
            md = Matchday(league_round=r, position=day_nr)

            pairing_objs = []
            for pairing in pairings:
                p = Pairing(team_a=pairing[0], team_b=pairing[1])
                m = Match(pairing=p)
                pairing_objs.append(p)

            md.pairings = pairing_objs

    return t
