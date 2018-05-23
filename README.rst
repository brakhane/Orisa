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

**If you think Orisa can be useful for your community, instead of installing
your own instance, try contacting me first.** There are no technical reasons
my instance cannot handle more than one guild (the current restrictions
on a single guild are simply shortcuts taken to keep the complexity as low
as possible); if there is interest, it can be added quickly.

.. code-block:: bash

    $ pipenv install
    $ cp config.py.template config.py
    $ $EDITOR config.py # use your favorite editor to fill in the necessary values

After that, you're set, just run ``pipenv python orisa.py``.

You need to use Discords developer pages to create a link you can use to allow
Orisa on your site. Orisa needs the following permissions: "Manage Nicknames", "Send Messages",
"Embed Links".

Once Orisa has joined, you will need to move the newly created Orisa role as high as possible;
the reason is that Discord only allows nickname changes to be done to people whose highest
role is lower than the one attempting the modification. So Orisa needs to be at least higher than the
group you use for your regular members.

License
-------
Orisa is licensed under the GNU AGPL version 3.

Basically it means that you have to give every user of your bot (which is every discord user on
your server) the same rights you got; the right to see and modify the source.

If you make modifications, you are required to disclose them to the users of your modified bot.

