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

from typing import List, Dict

from .models import (
    Tournament,
    Team,
    TeamMembership,
    Match,
    Game,
    Stage,
    RoundRobinStage,
    KnockoutStage,
    League,
    Matchday,
)


def create_round_robin_schedule(num_teams):
    """Create pairings for round robin tournaments/leagues
    Uses the well-known circle method, and also home-away balancing using the method described in

    "Balanced home–away assignments", Sigrid Knust, Michael von Thaden
    Discrete Optimization 3 (2006) 354–365
    """
    pool = list(range(num_teams))

    size = num_teams
    # Make number of participants even if necessary
    if num_teams % 2 == 1:
        pool.append(None)
        size += 1

    rounds = []
    for round in range(size - 1):

        rounds.append([(pool[i], pool[size - 1 - i]) for i in range(size // 2)])

        # rotatevbc
        pool.insert(1, pool.pop())

    # Alternate home/away, gives better results (more H/A/H/A sequences) even when balancing later
    rounds = [
        [(pairing[1], pairing[0]) for pairing in pairings] if i % 2 else pairings
        for i, pairings in enumerate(rounds)
    ]


    # now start the H/A balacing algorithm
    
    #Home/Away matrix 
    ham: List[List[int]] = [[0]*num_teams for _ in range(num_teams)]

    # lookup map to find pairing in rounds table
    rounds_ix: Dict[Tuple[int, int], Tuple[int, int]] = {}

    for r, pairings in enumerate(rounds):
        for p, pairing  in enumerate(pairings):
            home, away = pairing
            if home is None or away is None:
                continue
            ham[home][away] = 1
            ham[away][home] = -1
            rounds_ix[home, away] = rounds_ix[away, home] = r, p

    # imbalance of home/away games; +1 = one more home than away, -3 three more away than home, etc.
    delta = [sum(x) for x in ham]


    def swap_pairing(a, b):
        nonlocal rounds_ix, rounds, delta, ham

        r, p = rounds_ix[a, b]
        home, away = rounds[r][p]   
        assert (home == a and away == b) or (home == b and away == a)

        home, away = away, home

        rounds[r][p] = home, away
        delta[home] += 2
        delta[away] -= 2
        ham[home][away] = 1
        ham[away][home] = -1

    if num_teams % 2 == 0:

        # Each team will have a home/away balance that is non-zero, since the number of matches is odd


        # number of teams with more home games minus number of teams with away games
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

        # since the number of matches of each team is even, we can get the imbalance to zero

        while True:
            # The sum of all imbalances (sum(delta)) is always zero, so if there exist a team with a positive
            # imbalance, there exist at least one team with a negative imbalance
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
                # easy case, just swap home/away status for the match they play and we
                # improve the overall situation
                swap_pairing(i, j)
            else:  # i is playing away at j, more difficult
                # find a team k that plays away on both i and j; This must exist, see paper for proof.
                for k in range(num_teams):
                    if ham[i][k] == ham[j][k] == 1:
                        break
                else:  # no break
                    assert False, "This can't happen!"
                # swap both, i will now play away at k, and j will play at home against k
                swap_pairing(i, k)
                swap_pairing(j, k)
                
    return rounds


def create_simple_round_robin_tournament(name, teams, rounds):
    t = Tournament(name=name)
    rrs = RoundRobinStage(tournament=t)
    l = League(stage=rrs)
    l.teams = rrs.teams = t.teams = teams


    def team(x):
        return shuffled_teams[x] if x is not None else None

    num_teams = len(teams)

    shuffled_teams = teams.copy()
    schedule = create_round_robin_schedule(num_teams)

    for round in range(rounds):
        if round % 2 == 0:
            random.shuffle(shuffled_teams)
            day_pairings = [[(team(a), team(b)) for a, b in pairings] for pairings in schedule]
        else:
            day_pairings = [[(team(b), team(a)) for a, b in pairings] for pairings in schedule]

        for day_nr, pairings in enumerate(day_pairings):
            md = Matchday(league=l, position=day_nr + round * (num_teams - 1))

            matches = []
            for pairing in pairings:
                m = Match(team_a=pairing[0], team_b=pairing[1])
                g = Game(match=m)
                matches.append(m)

            md.matches = matches

    return t
