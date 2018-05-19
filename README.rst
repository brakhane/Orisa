Orisa
=====

Orisa is a simple Discord bot that solves a problem an Overwatch community
I'm a member of had: people who want to play as a team in a Quickplay or
competitive match always had to ask for each other's BattleTags and - in
case of competitive - rank.

Orisa solves this problem: people can message her to register their BattleTag,
and other players can now ask her for each others BattleTags, Orisa also
regularly checks Blizzard's playoverwatch.com site to update the member's
nicknames to include their current SR (or rank).

As an added bonus, it tries to motivate people by publically congratulating
them if they manage to increase their competitive rank (Silver -> Gold etc.)

Why is it called Orisa?
-----------------------

Like Orisa, this bot is still quite young, "new at this", a bit clumsy at times,
but wants to make people's life easier; it wants to be the hero the discord users need.

Installation
------------

If you think Orisa can be useful for your community, instead of installing
your own instance, try contacting me first. There are no technical reasons
my instance cannot handle more than one guild (the current restrictions
on a single guild are simply shortcuts taken to keep the complexity as low
as possible); if there is interest, it can be added quickly.

If you still want to run your own instance, be advised that it currently
requires the current git branch 0.7 of `discord-curious <https://github.com/Fuyukai/curious>`_,
the current 0.7.7 available on PyPI has a few bugs that make this bot crash.

.. code-block:: bash

    $ pipenv install # Keep in mind you need the discord-curios 0.7 branch checked out at ../curious
    $ pipenv shell
    $ cp config.py.template config.py
    $ $EDITOR config.py # use your favorite editor to fill in the necessary values

After that, you're set, just run `python orisa.py` in the pipenv environment.

License
-------
Orisa is licensed under the GNU AGPL version 3.

Basically it means that you have to give every user of your bot (which is every discord user on
your server) the same rights you got; the right to see and modify the source.

If you make modifications, you are required to disclose them to the users of your modified bot.

