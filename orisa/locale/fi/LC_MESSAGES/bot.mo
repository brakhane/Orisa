��    z      �  �   �      H
  �   I
  e   �
  ^   [  ^   �  A     �  [  �    {   �  �   [     Y     u     �     �  �   �  i   .     �     �  `   �       +     ?  K     �     �     �     �  C   �  .   �  $   !  0   F     w     z     }     �     �  P   �  �   �    �  �   �  �   o  �   <  r   �  %   ^     �  J   �  N   �  i   2  �   �  �   W  �      3   �   �   !     �!  .   �!     "  �   '"  M  �"     H$     N$  q  Q$     �%  �   �%     {&  �   �&      E'  �   f'     8(     M(     ](     o(     x(     {(     �(     �(  �   �(  �  3)     %+     A+  j   X+  �  �+     s-     v-    }-  �   �.     </     D/     I/  5   N/     �/  �   �/  ;   �0  �   �0  �   E1  '   �1     �1  �    2  �   �2  �   �3  �   b4     5  B   (5  �  k5  m   k9  3   �9  5   :  4   C:  �   x:  {   ;  |   �;  �   <  %  �<  �   �=  .   8>     g>  5   ~>  E   �>     �>     ?  9   +?  ^   e?     �?     �?  �  �?  �   �A  \   EB  `   �B  c   C  <   gC  �  �C    kE  �   rI  +  	J     5K     SK     pK     �K  �   �K  }   L     �L     �L  �   �L  (   *M  2   SM    �M     �O     �O     �O     �O  O   �O  0   P  $   IP  ,   nP     �P     �P     �P     �P     �P  L   �P  �   Q  -  �Q  �   �R  �   �S  �   �T  �   �U  +   -V  !   YV  \   {V  V   �V  n   /W  �   �W  �   {X  �   6Y  >   Z  �   TZ  )   [  3   E[  -   y[  �   �[  �  t\     ^     	^  �  ^     �_  �   �_  
   p`  �   {`  "   Za  �   }a     xb     �b     �b     �b     �b     �b     �b     �b  �   �b    ~c  $   �e     �e  t   �e  �  Kf     �g     �g  J  h  �   Qi     �i     j     j  5   j  !   Hj  �   jj  =   bk  �   �k  �   7l  '   �l     m  �   m  �   �m  {   �n  �   Qo     p  Y   'p  N  �p  v   �t  9   Gu  0   �u  9   �u  �   �u  w   �v  �   w  �   �w  #  ?x  �   cy  0   �y     !z  B   :z  F   }z     �z  $   �z  >   {  g   A{     �{     �{     x   X   7   (   U   %   Y   t   g   8   
           c       $       ,       6          e   =   5   :             F   L   "       a           3         d       .   4              n           u   P         ?   /                    N                     ;          j             +   B      >   1   K      A               0   S   	   i      b   h   G   E   s   M   I       ]       ^   W           -   *      H   @   m   q   r       !             C   p              2   v      R              Q   [   \   k          o   9   O   y       )   '   #       `   Z   D   <   f   J   _       l       T             &   z   V   w        

*Somebody (hopefully you) invited me to your server {guild_name}, but I couldn't find a text channel I am allowed to send messages to, so I have to message you directly* 
BTW, you do not need to specify your nickname if you want your own BattleTag; just @Orisa is enough. 
Orisa can neither confirm nor refute that the PSN Online ID actually belongs to this account. 
Orisa can neither confirm nor refute that the PSN Online IDs actually belong to this account. "{handle}" already is your primary {type}. *Going back to sleep!* *Greetings*! I am excited to be here :smiley:
To get started, create a new role named `Orisa Admin` (only the name is important, it doesn't need any special permissions) and add yourself and everybody that should be allowed to configure me.
Then, write `@Orisa config` in this channel and I will send you a link to configure me via DM.
*I will ignore all commands except `@Orisa help` and `@Orisa config` until I'm configured for this Discord!* *The following placeholders are defined:*
`$sr`
the first two digits of your SR for all 3 roles in order Tank, Damage, Support; if you have secondary accounts, an asterisk (\*) is added at the end. A question mark is added if an old SR is shown

`$fullsr`
Like `$sr` but all 4 digits are shown

`$rank`
your rank in shortened form for all 3 roles in order Tank, Damage, Support; asterisk and question marks work like in `$sr`

`$tank`, `$damage`, `$support`
Your full SR for the respective role followed by its symbol. Asterisk and question mark have the same meaning like in `$sr`. For technical reasons the symbols for the respective roles are `{SYMBOL_TANK}`, `{SYMBOL_DPS}`, `{SYMBOL_SUPPORT}`

`$tankrank`, `$damagerank`, `$supportrank`
like above, but the rank is shown instead.

`$shorttank`, `$shorttankrank` etc.
show only 2 digits/letters of the respective SR/rank.

`$dps`, `$dpsrank`, `$shortdps`, `$shortdpsrank` 
Alias for `$damage`, `$damagerank` etc. *This command can only be used by users with the "Orisa Admin" role!*
Like srgraph, but shows the graph for the given user. *This command is in beta and can change at any time; it might also have bugs, report them please*
Shows a graph of your SR. If from_date (as DD.MM.YY or YYYY-MM-DD) is given, the graph starts at that date, otherwise it starts as early as Orisa has data. :information_source: Protip :thinking: Need help? :video_game: Not on PC? About Me All your BattleTags will be removed from the database and your nick will not be updated anymore. You can re-register at any time. Blizzard says your {type} {handle} does not exist. Did you change it? Use `@Orisa register` to update it. Br Bronze By registering, you agree to Orisa's Privacy Policy; you can read it by entering @Orisa privacy. Click here to configure me! Click here to register your {type} account! Create a link to your BattleNet or Gamertag account, or adds a secondary BattleTag to your account. Your OW account will be checked periodically and your nick will be automatically updated to show your SR or rank (see the *format* command for more info). `@Orisa register` and `@Orisa register pc` will register a PC account, `@Orisa register xbox` will register an XBL account. If you register an XBL account, you have to link it to your Discord beforehand. For PSN accounts, you have to give your Online ID as part of the command, like `@Orisa register psn Your_Online-ID`. Damage Diamond Dm Donate `{HEART}` Done. Henceforth, thou shall be knownst as "`{new_nick}`, {title}". Done. Your primary {type} is now **{handle}**. Done. Your roles are now **{roles}** Download your SR history as an Excel spreadsheet GM Go Gold Grandmaster Help Translate Orisa However, there was an error updating your nickname. I will try that again later. However, your new nickname "{nickname}" is now longer than 32 characters, which Discord doesn't allow. Please choose a different format, or shorten your nickname and do a `@Orisa forceupdate` afterwards. I am an open source Discord bot to help manage Overwatch Discord communities.
I'm written and maintained by Dennis Brakhane (Joghurt#2732 on Discord) and licensed under the [GNU Affero General Public License 3.0+]({AGPL_LINK}); [development happens on GitHub]({GH_LINK}) I tried to send you a DM with help, but you don't allow DM from server members. I can't post it here, because it's rather long. Please allow DMs and try again. I tried to send you a DM with the link, but you disallow DM from server members. Please allow that and retry. I can't post the link here because everybody who knows that link will be able to configure me. I'm not allowed to send you a DM. Please right click on the Discord server, select "Privacy Settings", and enable "Allow direct messages from server members." Then try again. I'm not configured yet! Somebody with the role `Orisa Admin` needs to issue `@Orisa config` to configure me first! I've sent you a DM with instructions. I've sent you a DM. If you find me useful, [buy my maintainer a cup of coffee]({DONATE_LINK}). If you find me useful, consider voting for me [by clicking here]({VOTE_LINK})! If you have an XBL account, use `@Orisa register xbox`. For PSN, use `@Orisa register psn Your_Online-ID` If you use me in your Discord server, or generally have suggestions, [join the official Orisa Discord]({SUPPORT_DISCORD}). Updates and new features will be discussed and announced there. If you want to register a secondary/smurf BattleTag, you can open the link in a private/incognito tab (try right clicking the link) and enter the account data for that account instead. Immediately checks your account data and updates your nick accordingly.
*Checks and updates are done automatically, use this command only if you want your nick to be up to date immediately!* Invalid format string: unknown placeholder "{key}"! Invalid registration type "{type}". Use `@Orisa register` or `@Orisa register pc` for PC; `@Orisa register xbox` for Xbox, or `@Orisa register psn My-Online-Id_1234` for PlayStation. Invite me to your own Discord Join the [Support Discord]({SUPPORT_DISCORD})! Join the official Orisa Discord Lets you specify how your SR or rank is displayed. It will always be shown in [square\u00a0brackets] appended to your name.
In the *format*, you can specify placeholders with `$placeholder` or `${placeholder}`. Like `@Orisa setprimary battletag`, but uses numbers, 1 is your first secondary, 2 your seconds etc. The order is shown by `@Orisa` (alphabetical)
Normally, you should not need to use this alternate form, it's available in case Orisa gets confused on what BattleTag you mean (which shouldn't happen).
*Example:*
`@Orisa setprimary 1` Links Ma Makes the given secondary BattleTag your primary BattleTag. Your primary BattleTag is the one you are currently using: its SR is shown in your nick
The search is performed fuzzy and case-insensitve, so you normally only need to give the first (few) letters.
The given BattleTag must already be registered as one of your BattleTags.
*Example:*
`@Orisa setprimary jjonak` Master Missing roles identifier. Valid role identifiers are: `m` (Main Tank), `o` (Off Tank), `d` (Damage), `s` (Support). They can be combined, e.g. `ds` would mean Damage + Support. Nick OK, I have updated your data. Your ranks are now {sr}. If that is not correct, you need to log out of Overwatch once and try again; your profile also needs to be public for me to track your ranks. OK, deleted {name} from database On some servers, Orisa will only show your SR or rank in your nick when you are in an OW voice channel. If you want your nick to always show your SR or rank, set this to on.
*Example:*
`@Orisa alwaysshowsr on` Orisa Support Server Orisa's purpose Overwatch profile Platinum Pt Removed **{handle}**! Roles SR SRs Same as `@Orisa [nick]`, (only) useful when the nick is the same as a command.
*Example:*
`@Orisa get register` will search for the nick "register". Sets the role you can/want to play. It will be shown in `@Orisa` and will also be used to update the number of roles in voice channels you join.
*roles* is a single "word" consisting of one or more of the following identifiers (both upper and lower case work):
`d` for DPS, `m` for Main Tank, `o` for Off Tank, `s` for Support
*Examples:*
`@Orisa setroles d`: you only play DPS.
`@Orisa setroles so`: you play Support and Off Tanks.
`@Orisa setroles dmos`: you are a true Flex and play everything. Show Orisa's Privacy Policy Show your love :heart: Shows information about Orisa, and how you can add her to your own Discord server, or help supporting her. Shows the BattleTag for the given nickname, or your BattleTag if no nickname is given. `nick` can contain spaces. A fuzzy search for the nickname is performed.
*Examples:*
`@Orisa` will show your BattleTag
`@Orisa the chosen one` will show the BattleTag of "tHE ChOSeN ONe"
`@Orisa orisa` will show the BattleTag of "SG | Orisa", "Orisa", or "Orisad"
`@Orisa oirsa` and `@Orisa ori` will probably also show the BattleTag of "Orisa" Si Silver Smarties Expert
Bread Scientist
Eternal Bosom of Hot Love
Sith Lord of Security
Namer of Clouds
Scourge of Beer Cans
Muse of Jeff Kaplan
Shredded Cheese Authority
Pork Rind Expert
Dinosaur Supervisor
Galactic Viceroy of C9
Earl of Bacon
Dean of Pizza
Duke of Tacos
Retail Jedi Sorry, using this format would make your nickname `{nickname}` be longer than 32 characters ({len} to be exact).
Please choose a shorter format or shorten your nickname! Support Tags Tank The SR of the primary {type} was last updated {when}. The SR was last updated {when}. The config command must be issued from a channel of the server you want to configure. Don't worry, I will send you the config instructions as a DM, so others can't configure me just by watching you sending this command. There were some problems updating your SR! Try again later. This command can only be used by members with the "Orisa Admin" role and allows them to configure Orisa for the specific Discord server. This command can only be used by members with the `Orisa Admin` role! Only the name of the role is important, it doesn't need any permissions. This link will be valid for 30 minutes. Tip To complete your registration, I need your permission to ask Blizzard for your BattleTag. Please click the link above and give me permission to access your data. I only need this permission once, you can remove it later in your BattleNet account. To complete your registration, I need your permission to ask Discord for your Gamertag. Please click the link above and give me permission to access your data. Make sure you have linked your Xbox account to Discord. To invite me to your server, simply [click here]({LINK}), I will post a message with more information in a channel after I have joined your server Unknown role identifier '{role}'. Valid role identifiers are: `m` (Main Tank), `o` (Off Tank), `d` (Damage), `s` (Support). They can be combined, e.g. `ds` would mean Damage + Support. Upvote Orisa Use `@Orisa register` to register, or `@Orisa help` for more info. When joining a QP or Comp channel, you need to know the BattleTag of a channel member, or they need yours to add you. In competitive channels it also helps to know which SR the channel members have. To avoid having to ask for this information again and again when joining a channel, this bot was created. When you register with your BattleTag, your nick will automatically be updated to show your current SR and it will be kept up to date. You can also ask for other member's BattleTag, or request your own so others can easily add you in OW.
It will also send a short message to the chat when you ranked up.
*Like Overwatch's Orisa, this bot is quite young and still new at this. Report issues to <@!{OWNER}>*

**The commands only work in the <#{channel_id}> channel or by sending me a DM**
If you are new to Orisa, you are probably looking for `@Orisa register` or `@Orisa register xbox`
If you want to use Orisa on your own server or help developing it, enter `@Orisa about`
Parameters in [square brackets] are optional. When registering a PSN account, you need to give your Online ID, like `@Orisa register psn My-Cool-ID_12345`. You are not registered! Do `@Orisa register` first. You are not registered, there's nothing for me to do. You are not registered. Use `@Orisa register` first. You cannot unregister your primary handle. Use `@Orisa setprimary` to set a different primary first, or use `@Orisa forgetme` to delete all your data. Your nick will be updated even when you are not in an OW voice channel. Use `@Orisa alwaysshowsr off` to turn it off again. Your nick will only be updated when you are in an OW voice channel. Use `@Orisa alwaysshowsr on` to always update your nick. `@Orisa config` works in *any* channel (that I'm allowed to read messages in, of course), so you can also use an admin-only channel. `@Orisa format hello $sr` will result in `[hello 12-34-45]`.
`@Orisa format Potato/$fullrank` in `[Potato/Bronze-Gold-Diamond]`.
`@Orisa format $damage $support` in `[{SYMBOL_DPS}1234 {SYMBOL_SUPPORT}2345]`.
`@Orisa format $shortdamage` in `[{SYMBOL_DPS}12]`.
*By default, the format is `$sr`* `setprimary` requires the first few letters of the handle you want to make your primary as a parameter, e.g. `@Orisa setprimary foo` format string may not contain square brackets! format string missing! format string must contain at least one $placeholder! you are not registered anyway, so there's nothing for me to forget… you are not registered! you must register first! {member_name} not found in database! *Do you need a hug?* {type} looks like a BattleTag and not like PC/Xbox, assuming you meant `@Orisa register pc`… ★ *ow format examples* ★ *ow format placeholders* Project-Id-Version: Finnish (Orisa)
Report-Msgid-Bugs-To: 
PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE
Last-Translator: FULL NAME <EMAIL@ADDRESS>
Language-Team: Finnish <https://hosted.weblate.org/projects/orisa/bot/fi/>
Language: fi
MIME-Version: 1.0
Content-Type: text/plain; charset=UTF-8
Content-Transfer-Encoding: 8bit
Plural-Forms: nplurals=2; plural=n != 1;
X-Generator: Weblate 5.10-dev
 

*Joku (toivottavasti sinä) kutsui minut palvelimellesi {guild_name}, mutta en löytänyt tekstikanavaa, johon voin lähettää viestejä, joten minun on lähetettävä sinulle viesti suoraan* 
PS, sinun ei tarvitse tarkentaa nimikerkkiäsi kun haluat oman BattleTagisi, !ow riittää. 
Orisa ei voi vahvistaa eikä kiistää, että PSN Online -tunnus todella kuuluu tälle tilille. 
Orisa ei voi vahvistaa tai kiistää, että PSN Online -tunnukset todella kuuluvat tälle tilille. "{handle}" on jo ensisijainen {type}. *Going back to sleep!* *Terveisiä*! Olen innoissani täällä :smiley:
Aloita luomalla uusi rooli nimeltä `Orisa Admin` (vain nimi on tärkeä, se ei vaadi erityisiä lupia) ja lisää itsesi ja kaikki, joiden pitäisi olla sallittuja määrittää minut.
Kirjoita sitten tähän kanavaan `@Orisa config`, niin lähetän sinulle linkin konfigurointiin DM:n kautta.
*Ohitan kaikki komennot paitsi `@Orisa help` ja `@Orisa config`, kunnes olen määritetty tähän Discordiin!* *Seuraavat paikkamerkit on määritelty:*
`$sr`
SR:n kaksi ensimmäistä numeroa kaikille kolmelle roolille järjestyksessä Tank, Damage, Support; jos sinulla on toissijaisia tilejä, tähti (\*) lisätään loppuun. Kysymysmerkki lisätään, jos näytetään vanha SR

`$fullsr`
Kuten "$sr", mutta kaikki 4 numeroa näytetään

`$rank`
arvosi lyhennetyssä muodossa kaikissa kolmessa roolissa järjestyksessä Tank, Damage, Support; tähti ja kysymysmerkit toimivat kuten "$sr".

`$tank`, `$damage`, `$support`
Täydellinen SR vastaavalle roolille ja sen symboli. Tähdellä ja kysymysmerkillä on sama merkitys kuin lausekkeessa "$sr". Teknisistä syistä vastaavien roolien symbolit ovat `{SYMBOL_TANK}`, `{SYMBOL_DPS}`, `{SYMBOL_SUPPORT}`

`$tankrank`, `$damagerank`, `$supportrank`
kuten yllä, mutta sen sijaan näytetään sijoitus.

`$shorttank`, `$shorttankrank` jne.
näyttää vain 2 numeroa/kirjainta vastaavasta SR:sta/luokasta.

`$dps`, `$dpsrank`, `$shortdps`, `$shortdpsrank`
Alias `$damage`, `$damagerank` jne. *Tätä komentoa voivat käyttää vain käyttäjät, joilla on rooli "Orisa Admin"!*
Kuten srgraph, mutta näyttää kaavion tietylle käyttäjälle. *Tämä komento on beta-vaiheessa ja voi muuttua milloin tahansa; siinä saattaa myös olla virheitä, ilmoita niistä*
Näyttää kaavion SR:stäsi. Jos on annettu from_date (kuten PP.KK.VV tai VVVV-KK-PP), kaavio alkaa kyseisestä päivämäärästä, muuten se alkaa heti kun Orisalla on tietoja. :information_source: Provihje :thinking: Tarvitsetko apua? :video_game: Ei PC? Tietoja minusta Kaikki BattleTagisi poistetaan tietokannasta, eikä nimimerkkiäsi enää päivitetä. Voit rekisteröityä uudelleen milloin tahansa. Blizzard sanoo, että sinun {type} {handle} ei ole olemassa. Vaihdoitko sen? Käytä `@Orisa register` päivittääksesi sen. Br Bronze Rekisteröityessäsi hyväksyt Orisan yksityisyyskäytännön; voit lukea sen (saatavilla vain Englanniksi) komennolla @Orisa privacy. Klikkaa tästä konfiguroidaksesi minut! Klikkaa tästä rekisteröidäksesi {type} tilisi! Luo linkki BattleNet- tai Gamertag-tiliisi tai lisää tiliisi toissijainen BattleTag. OW-tilisi tarkistetaan ajoittain ja nimimerkkisi päivitetään automaattisesti näyttämään SR tai sijoitus (katso *format*-komento saadaksesi lisätietoja). `@Orisa register` ja `@Orisa register pc` rekisteröi PC-tilin, `@Orisa register xbox` XBL-tilin. Jos rekisteröit XBL-tilin, sinun on linkitettävä se Discord-tiliisi etukäteen. PSN-tileissä sinun on annettava online-tunnuksesi osana komentoa, kuten `@Orisa register psn sinun_verkko-ID`. Damage Diamond Dm Lahjoita `{HEART}` Valmis. Tästä eteenpäin sinua kutsutaan tittelillä "`{new_nick}`, {title}". Valmis. Ensisijainen {type} on nyt **{handle}**. Valmis. Roolisi ovat nyt **{roles}** Lataa SR-historiasi Excel-laskentataulukkona GM Go Gold Grandmaster Auta kääntämään Orisa Päivittäessä nimimerkkiäsi tapahtui virhe. Yritän myöhemmin uudelleen. Uusi nimimerkkisi "{nickname}" on pidempi kuin 32 merkkiä, mitä Discord ei salli. Valitse eri formaatti tai lyhennä nimimerkkiäsi ja tee `@Orisa forceupdate` sen jälkeen. Olen avoimen lähdekoodin Discord botti, joka auttaa hallitsemaan Overwatch Discord yhteisöjä.
Minut on kirjoittanut ja minua ylläpitää Dennis Brakhane (Joghurt#2732 Discordissa) ja minut on lisensoitu [GNU Affero General Public License 3.0]({AGPL_LINK}); [kehitys on tehty Githubissa]({GH_LINK}) Yritin lähettää sinulle apua yksityisviestillä, mutta et ole sallinut yksityisviestejä palvelimen jäseniltä. En voi lähettää viestiä tässä, sillä se on aika pitkä. Salli yksityisviestit ja yritä uudelleen. Yritin lähettää sinulle linkin sisältävän DM-viestin, mutta et salli DM:n lähettämistä palvelimen jäseniltä. Salli se ja yritä uudelleen. En voi lähettää linkkiä tänne, koska kaikki, jotka tietävät linkin, voivat määrittää minut. En saa lähettää sinulle DM:a. Napsauta hiiren kakkospainikkeella Discord-palvelinta, valitse "Privacy Settings" ja ota käyttöön "Salli suorat viestit palvelimen jäseniltä". Yritä sitten uudelleen. Minua ei ole configuroitu vielä! Jonkun roolilla `Orisa Admin` pitää käyttää komentoa `@Orisa config` konfiguroidaksensa minut ensin! Lähetin sinulle ohjeet yksityisviestillä. Lähetin sinulle yksityisviestin. Jos pidät minua hyödyllisenä, [osta ylläpitäjälleni kupillinen kahvia]({DONATE_LINK}). Jos pidät minua hyödyllisenä, äänestä minua [klikkaamalla tästä]({VOTE_LINK})! Jos sinulla on XBL-tili, käytä `@Orisa register xbox`. PSN:ssa käytä `@Orisa register psn sinun_verkko-ID` Jos käytät minua Discord palvelimellasi tai sinulla on ehdotuksia, [liity viralliselle Orisa Discord palvelimelle]({SUPPORT_DISCORD}). Päivityksistä ja uusista ominaisuuksista keskustellaan ja ne julkaistaan siellä. Jos haluat rekisteröidä toissijaisen BattleTagin, avaa linkki privaatissa/incognito välilehdessä (klikkaa linkkiä oikealla hiirinäppäimellä) ja lisää toissijaisen tilin tiedot. Tarkistaa välittömästi tilitietosi ja päivittää nimimerkkisi vastaavasti.
*Tarkistukset ja päivitykset tehdään automaattisesti, käytä tätä komentoa vain, jos haluat nimesi olevan ajan tasalla välittömästi!* Virheellinen muotomerkkijono: tuntematon paikkamerkki "{key}"! Virheellinen rekisteröintityyppi "{type}". Käytä `@Orisa register` tai `@Orisa register pc` PC:lle; `@Orisa register xbox` Xboxille tai `@Orisa register psn minun-verkko-Id_1234` PlayStationille. Kutsu minut omalle Discord palvelimellesi Liity [tuki Discord serverille]({SUPPORT_DISCORD})! Liity viralliselle Orisa Discord palvelimelle Voit määrittää, miten sinun SRisi tai sijoituksesi näytetään. Se näytetään aina [hakasulkeissa] nimesi liitteenä.
*muodossa* voit määrittää paikkamerkit `$placeholder` tai `${placeholder}`. Kuten `@Orisa setprimary battletag`, mutta käyttää numeroita, 1 on ensimmäinen toissijainen, 2 sekuntisi jne. Järjestys näkyy `@Orisa` (aakkosjärjestyksessä)
Normaalisti sinun ei tarvitse käyttää tätä vaihtoehtoista lomaketta, se on käytettävissä siltä varalta, että Orisa hämmentää, mitä BattleTagia tarkoitat (mitä ei pitäisi tapahtua).
*Esimerkki:*
`@Orisa setprimary 1` Linkit Ma Tekee annetusta toissijaisesta BattleTagista ensisijaisen BattleTagin. Ensisijainen BattleTagisi on se, jota käytät tällä hetkellä: sen SR näkyy nimimerkissäsi
Haku suoritetaan sumeasti ja isot ja pienet kirjaimet huomioimatta, joten sinun tarvitsee yleensä antaa vain ensimmäiset (muutama) kirjain.
Annetun BattleTagin on oltava jo rekisteröity yhdeksi BattleTagistasi.
*Esimerkki:*
`@Orisa setprimary jjonak` Master Roolin tunniste puuttuu. Roolin tunnisteiksi kelpaavat: `m` (Main Tank), `o` (Off Tank), `d` (Damage), `s` (Support). Niitä voi yhdistellä, esim. `ds` tarkoittaisi Damage + Support. Nimimerkki OK, olen päivittänyt tietosi. Arvosi ovat nyt {sr}. Jos tämä ei ole oikein, sinun on kirjauduttava ulos Overwatchista kerran ja yritettävä uudelleen; profiilisi on myös oltava julkinen, jotta voin seurata riveitasi. OK, poistettu {name} tietokannasta Joillakin palvelimilla Orisa näyttää vain SR:si tai sijoituksesi nimimerkissäsi, kun olet OW-äänikanavalla. Jos haluat, että nimimerkkisi näyttää aina SR:si tai sijoituksesi, aseta tämä päälle.
*Esimerkki:*
`@Orisa ainashowsr päällä` Orisa tuki palvelin Orisan tarkoitus Overwatch profiili Platinum Pt Poistettu **{handle}**! Roolit SR SRs Sama kuin `@Orisa [nick]`, (vain) hyödyllinen, kun nimimerkki on sama kuin komento.
*Esimerkki:*
`@Orisa get register` etsii nimimerkkiä "rekisteröidy". Asettaa roolin, jonka voit/haluat pelata. Se näkyy @Orisassa ja sitä käytetään myös päivittämään roolien määrää äänikanavilla, joihin liityit.
*roolit* on yksittäinen "sana", joka koostuu yhdestä tai useammasta seuraavista tunnisteista (sekä isot että pienet kirjaimet):
"d" DPS:lle, "m" PääTankille, "o" Pois Tankille, "s" Tukeelle
*Esimerkit:*
`@Orisa setroles d`: pelaat vain DPS:aa.
`@Orisa setroles niin`: pelaat Support- ja Pois Tank -pelejä.
`@Orisa setroles dmos`: olet todellinen Flex ja pelaat kaikkea. Näytä Orisan tietosuojakäytäntö Näytä rakkautesi :heart: Näyttää tietoa Orisasta ja kuinka voit lisätä hänet omalle Discord-palvelimellesi tai auttaa häntä tukemaan. Näyttää BattleTagin annetulle lempinimelle tai BattleTagin, jos lempinimeä ei ole annettu. `nick` voi sisältää välilyöntejä. Lempinimelle suoritetaan sumea haku.
*Esimerkit:*
`@Orisa` näyttää BattleTagisi
`@Orisa valittu` näyttää "VALITTUJEN" BattleTagin
`@Orisa orisa` näyttää BattleTagin "SG | Orisa", "Orisa" tai "Orisad"
`@Orisa oirsa` ja `@Orisa ori` näyttävät todennäköisesti myös "Orisan" BattleTagin Si Silver Smarties Expert
Bread Scientist
Eternal Bosom of Hot Love
Sith Lord of Security
Namer of Clouds
Scourge of Beer Cans
Muse of Jeff Kaplan
Shredded Cheese Authority
MILF Commander
Cunning Linguist
Pork Rind Expert
Dinosaur Supervisor
Galactic Viceroy of C9
Earl of Bacon
Dean of Pizza
Duke of Tacos
Retail Jedi
Pornography Historian Valitettavasti tämän muodon käyttäminen tekisi lempinimestäsi `{nickname}` pidempi kuin 32 merkkiä (tarkasti {len}).
Valitse lyhyempi muoto tai lyhennä lempinimeäsi! Support Tagit Tank Ensisijaisen {type} SR päivitettiin viimeksi {when}. SR päivitettiin viimeksi {when}. Konfiguraatio komento pitää lähettää serverisi kanavalta, jonka haluat konfiguroida. Älä huoli, lähetän sinulle konfiguraatio ohjeistukset yksityisviestillä, jotta muut eivät voi konfiguroida minua nähdessään lähettämäsi komennon. SR päivityksessä oli ongelmia! Yritä myöhemmin uudelleen. Tätä komentoa voi käyttää vain käyttäjät, joilla on "Orisa Admin" rooli, joka antaa heidän konfiguroida Orisan tietylle Discord palvelimelle. Tätä komentoa voi käyttää vain käyttäjät, joilla on `Orisa Admin` rooli! Vain roolin nimi on tärkeä, siihen ei tarvitse liittyä mitään käyttöoikeuksia. Tämä linkki on voimassa 30 minuuttia. Vihje Suorittaaksesi rekisteröitymisesi loppuun tarvitsen lupasi kysyä Blizzardilta BattleTagisi. Klikkaa linkkiä yläpuolella ja anna minulle pääsy dataasi. Tarvitsen luvan vain kerran, voit poistaa sen myöhemmin BattleNet tilisi kautta. Suorittaaksesi rekisteröitymisesi loppuun tarvitsen lupasi kysyä Discordilta Gamertagiasi. Klikkaa linkkiä yläpuolella ja anna minulle pääsy dataasi. Varmistathan, että olet linkittänyt Xbox tilisi Discordiin. Kutsu minut palvelimellesi [tästä linkistä]({LINK}), kirjoitan lisätietoja kanavalle, kun olen liittynyt palvelimellesi Tuntematon roolin tunniste '{role}'. Roolin tunnisteiksi kelpaavat: `m` (Main Tank), `o` (Off Tank), `d` (Damage), `s` (Support). Niitä voi yhdistellä, esim. `ds` tarkoittaisi Damage + Support. Äänestä Orisaa käytä `@Orisa register` rekisteröityäksesi tai `@Orisa help` saadaksesi lisätietoja. Kun liityt QP- tai Comp-kanavalle, sinun on tiedettävä kanavan jäsenen BattleTag tai he tarvitsevat sinun lisäämään sinut. Kilpailukanavissa auttaa myös tietämään, mikä SR kanavan jäsenillä on. Tämä botti luotiin, jotta näitä tietoja ei tarvitsisi kysyä uudelleen ja uudelleen liittyessäsi kanavaan. Kun rekisteröidyt BattleTagillesi, nimimerkkisi päivitetään automaattisesti näyttämään nykyinen SR ja se pidetään ajan tasalla. Voit myös pyytää toisen jäsenen BattleTagia tai pyytää omaa, jotta muut voivat helposti lisätä sinut OW:hen.
Se lähettää myös lyhyen viestin chatiin, kun saavutat paremmuusjärjestyksen.
* Kuten Overwatchin Orisa, tämä botti on melko nuori ja vielä uusi tässä. Ilmoita ongelmista <@!{OWNER}>*

**Komennot toimivat vain <#{channel_id}>-kanavalla tai lähettämällä minulle DM**
Jos olet uusi Orisa, etsit todennäköisesti `@Orisa register` tai `@Orisa register xbox`
Jos haluat käyttää Orisaa omalla palvelimellasi tai auttaa sen kehittämisessä, kirjoita `@Orisa about`
Parametrit [square brackets]:ssa ovat valinnaisia. Kun rekisteröit PSN-tilin, sinun on ilmoitettava verkkotunnuksesi, kuten `@Orisa register psn minun-siisti-ID_12345`. Et ole rekisteröitynyt! Käytä `@Orisa register` ensin. Et ole rekisteröitynyt, en voi tehdä mitään. Et ole rekisteröitynyt. Käytä `@Orisa register` ensin. Et voi peruttaa rekisteröintiä päätililtäsi. Käytä `@Orisa setprimary` asettaaksesi toisen tilin päätiliksi tai käytä `@Orisa forgetme` poistaaksesi kaikki tietosi. Nimimerkkisi päivitetään, vaikket ole OW puhekanavalla. Käytä `@Orisa alwaysshowsr off` poistaaksesi ominaisuuden. Nimimerkkisi päivitetään, kun olet OW puhekanavalla. Käytä `@Orisa alwaysshowsr on`päivittääksesi nimimerkkisi koko ajan. `@Orisa config` toimii *millä tahansa* kanavalla (jossa saan tietysti lukea viestejä), joten voit käyttää myös vain järjestelmänvalvojalle tarkoitettua kanavaa. `@Orisa-muoto hei $sr` johtaa `[hei 12-34-45]`.
`@Orisa-muoto Peruna/$fullrank` muodossa `[Peruna/pronssi-kulta-timantti].
`@Orisa-muoto $damage $support` muodossa `[{SYMBOL_DPS}1234 {SYMBOL_SUPPORT}2345]`.
`@Orisa-muoto $shortdamage` muodossa `[{SYMBOL_DPS}12]`.
*Oletuksena muoto on `$sr`* `setprimary` vaatii muutaman ensimmäisen kirjaimen kahvasta, josta haluat tehdä ensisijaiseksi parametriksi, esim. `@Orisa setprimary foo` muotomerkkijono ei saa sisältää hakasulkeita! muotomerkkijono puuttuu! muotomerkkijonon tulee sisältää vähintään yksi $placeholder! et ole rekisteröitynyt, joten minulla ei ole mitään unohdettavaa… et ole rekisteröitynyt! sinun pitää rekisteröityä ensin! {member_name} ei löytynyt tietokannasta! *Do you need a hug?* {type} näyttää BattleTagilta, ei PC:ltä/Xboxilta, olettaen, että tarkoitit `@Orisa register pc`… ★ *ow-muotoiset esimerkit* ★ *ow-muotoiset paikkamerkit* 