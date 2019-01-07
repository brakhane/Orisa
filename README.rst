Orisa
=====

Orisa is a Discord bot that solves a problem an Overwatch community
I'm a member of had: people who want to play as a team in a Quickplay or
competitive match always had to ask for each other's BattleTags and - in
case of competitive - rank.

Orisa solves this problem: people can message her to register their BattleTag,
and other players can now ask her for each others BattleTags, Orisa also
regularly checks Blizzard's playoverwatch.com site to update the member's
nicknames to include their current SR (or rank).

As an added bonus, it tries to motivate people by publically congratulating
them if they manage to increase their competitive rank (Silver -> Gold etc.)

She also can manage voice channels and create them on demand, and show fancy SR graphs

Why is it called Orisa?
-----------------------

Like Orisa, this bot is still quite young, "new at this", a bit clumsy at times,
but wants to make people's life easier; it wants to be the hero the discord users need.

Features
--------

* Shows the current SR and/or rank in nicknames, e.g. ``somenick [2345]``. Users can configure what it shown by using flexible format strings
* SR is automatically updated whenever a player stops playing Overwatch while being in Discord, and also every hour
* Supports multiple BattleTags per user
* BattleTags are registered via OAuth, so you can be sure that the BattleTag really belongs to that user
* Finds (registered) players in a given SR range
* Congratulates every player when he/she reached a new personal best rank
* Can manage voice channels and create them on demand, e.g. "Comp #2" will be created when "Comp #1" has members in it
* Can show the SR range of people in the voice channel name, e.g. "Comp #1 [2104-2340]"
* Allows people to track their SR and display a SR graph
* Has a `findplayers` command that can suggest people in a specific SR range
* Can be configured via a web interface
* Tries to be as user friendly as possible: has an extensive help and gives suggestions.
* Uses fuzzy search whenever possible, ``!ow oirsa`` will still find and display the BattleTags of the user named "Orisa"
* Has been called "the best Overwatch Discord bot I've seen" by at least 2 people
* Might have been called "a stupid Omnic I do not trust" by Zarya
* Is not evil; it won't even try to eat your cat

Installation
------------

**If you think Orisa can be useful for your community, instead of installing
your own instance, try contacting me first (Joghurt#2732 on discord).** My Orisa instance can be configured via
web, and currently she's not easy to set up; it's easier to just add your Discord server to the
already running instance.

**This information here is a little bit outdated**

You need to use Discords developer pages to create a link you can use to allow
Orisa on your site. Orisa needs the following permissions: "Manage Nicknames", "Send Messages",
"Embed Links". For ``srgraph`` she also needs "Attach Files" and if you want her to manage the
amount of voice channels (currently undocumented), you would also need "Manage Channels".

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

