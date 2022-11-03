from io import BytesIO
import math
import os
import re
from bisect import bisect
from collections import namedtuple
from contextlib import ExitStack
from dataclasses import dataclass
from difflib import get_close_matches
from functools import total_ordering
from pathlib import Path
from tempfile import TemporaryFile
from typing import Optional

import cv2 as cv
import json
import dramatiq
import httpx
import matplotlib.pyplot as plt
import numpy as np
import numpy.typing as npt
import pytesseract
from dramatiq.brokers.redis import RedisBroker
from dramatiq.rate_limits import ConcurrentRateLimiter
from dramatiq.rate_limits.backends import RedisBackend

from .models import SR, Database, Handle, User
from .shared import APPID, CommandInteraction

# pytesseract.pytesseract.tesseract_cmd = R"d:\tesseract-ocr\tesseract.exe"

backend = RedisBackend()
broker = RedisBroker(host="localhost")
dramatiq.set_broker(broker)
PROCESS_RATELIMIT = ConcurrentRateLimiter(
    backend, "process-ratelimit", limit=2, ttl=30000
)

TOKEN = os.environ["BOT_TOKEN"]

Coords = namedtuple("Coords", "x y")


@dataclass
class Region:
    top_left: Coords
    bottom_right: Coords
    psm: Optional[int] = None
    invert: bool = False


@total_ordering
class Rank:
    ranks: list[str] = "bronze silver gold platinum diamond master gm".split()

    def __init__(self, rankname: str, div: int):
        self.name = f"{'GM' if rankname == 'gm' else rankname.capitalize()} {div}"
        if not (1 <= div <= 5):
            raise ValueError(f"division {div} is out of bounds")
        try:
            self.sr = 1000 + self.ranks.index(rankname) * 500 + (5 - div) * 100
        except ValueError as e:
            raise ValueError(f"invalid rank name {rankname}") from None

    def __repr__(self):
        return f"<Rank: {self.name} ({self.sr} SR)>"

    def __str__(self):
        return self.name

    def __lt__(self, other):
        if not isinstance(other, Rank):
            return NotImplemented
        return self.sr < other.sr

    def __eq__(self, other):
        return isinstance(other, Rank) and other.sr == self.sr

    def __hash__(self):
        return self.sr


@dataclass
class Ranks:
    combined: Optional[Rank] = None
    tank: Optional[Rank] = None
    damage: Optional[Rank] = None
    support: Optional[Rank] = None


@dataclass
class ParsedScreenshot:
    nick: str
    season: str
    hours: Optional[int]
    hours_raw: str
    nick_raw: str
    season_raw: str
    current: Ranks
    season_high: Ranks
    debug_img: Optional[npt.ArrayLike]


regions = {
    "nick": Region(Coords(550, 370), Coords(2500, 590), invert=True, psm=8),
    "competitive season": Region(Coords(2110, 810), Coords(2800, 870), psm=7),
    "first row background": Region(Coords(2180, 1950), Coords(2360, 2050)),
    "hours": Region(Coords(400, 1360), Coords(870, 1460), invert=True, psm=7),
    "rank icons": Region(Coords(1990, 1930), Coords(2660, 2520)),
    "fourth row background": Region(Coords(2180, 2400), Coords(2360, 2500)),
}


class ScreenshotReader:
    def __init__(self, image):
        self.image = image
        h, w, depth = image.shape
        self.fx = w / 5120
        self.fy = w * 9 / 16 / 2880

    def determine_background_color(self, clip):
        row_avg = np.average(clip, axis=0)
        avg = np.average(row_avg, axis=0)
        return np.array([int(x) for x in avg])

    def get_clip(self, region):
        return self.image[
            int(region.top_left.y * self.fy) : int(region.bottom_right.y * self.fy),
            int(region.top_left.x * self.fx) : int(region.bottom_right.x * self.fx),
        ]

    def create_icon(self, rank: str, division: int, background_color):
        fx, fy = self.fx, self.fy
        if fx < 1:
            bg = cv.imread(
                f"templates/template-div-{division}-trans.png", cv.IMREAD_UNCHANGED
            )
            symbol = cv.imread(
                f"templates/template-rank-{rank}.png", cv.IMREAD_UNCHANGED
            )
            fx *= 2
            fy *= 2
        else:
            bg = cv.imread(
                f"templates/hq-template-div-{division}.png", cv.IMREAD_UNCHANGED
            )
            symbol = cv.imread(
                f"templates/hq-template-rank-{rank}.png", cv.IMREAD_UNCHANGED
            )

        bg_alpha = bg[:, :, 3] / 255
        symbol_alpha = symbol[:, :, 3] / 255

        # FIXME: don't iterate in Python
        # for i in range(3):
        #     bg[:, :, i] = (
        #         (1 - symbol_alpha) * (
        #             bg_alpha * bg[:, :, i] + (1-bg_alpha)*background_color[i]
        #         ) + (
        #             symbol_alpha * symbol[:, :, i]
        #         )
        #     )

        # res = bg[:, :, :3]

        bg_alpha = np.repeat(bg_alpha[:, :, np.newaxis], 3, axis=2)
        symbol_alpha = np.repeat(symbol_alpha[:, :, np.newaxis], 3, axis=2)

        res = (1 - symbol_alpha) * (
            bg_alpha * bg[:, :, :3] + (1 - bg_alpha) * background_color
        ) + (symbol_alpha * symbol[:, :, :3])

        if fx != 1 or fy != 1:
            res = cv.resize(
                res,
                None,
                fx=fx,
                fy=fy,
                interpolation=cv.INTER_AREA if fx < 1 else cv.INTER_CUBIC,
            )

        # cv.imshow(f"{rank}{division}", res.astype(np.uint8))
        # cv.waitKey()

        return res.astype(np.uint8)

    def find_icons(self, clip, background_color, *, debug=False):
        matches = {}
        for rank in "bronze silver gold platinum diamond master gm".split():
            for div in range(1, 6):
                template = self.create_icon(rank, div, background_color)
                res = cv.matchTemplate(clip, template, cv.TM_SQDIFF_NORMED)

                # ic_r, ic_g, ic_b = cv.split(image)
                # tem_r, tem_g, tem_b = cv.split(template)
                # res_r = cv.matchTemplate(ic_r, tem_r, cv.TM_SQDIFF_NORMED)
                # res_g = cv.matchTemplate(ic_g, tem_g, cv.TM_SQDIFF_NORMED)
                # res_b = cv.matchTemplate(ic_b, tem_b, cv.TM_SQDIFF_NORMED)

                # res = res_r + res_g + res_b
                # thres = 3*0.25
                # res = res_r * res_g * res_b
                # thres = 0.21**3
                thres = 0.1
                # print(f"{rank} {div} {res.min()}")
                min_distance_sq = min(template.shape[:2]) ** 2
                if np.any(res <= thres):
                    for yx in np.column_stack(np.nonzero(res <= thres)):
                        found = False
                        y, x = yx
                        for k, v in matches.copy().items():
                            if (k[0] - x) ** 2 + (k[1] - y) ** 2 < min_distance_sq:
                                found = True
                                if v[2] > res[y][x]:
                                    # print(f"replacing {k}: {v} with {x},{y}: {rank, div, res[y][x]}")
                                    del matches[k]
                                    matches[x, y] = rank, div, res[y][x]
                                    break
                                # else:
                                #    print(f"{res[y][x]} > {v}@{k}")

                        if not found:
                            matches[x, y] = rank, div, res[y][x]

        # Convert matches coordinates to column and row
        h, w = clip.shape[:2]
        converted_matches = {
            (bisect([w / 2], xy[0]), bisect([h / 4, 2 * h / 4, 3 * h / 4], xy[1])): val
            for xy, val in matches.items()
        }

        debug_img = None

        if debug:
            for xy, v in matches.items():
                rank, div, error = v
                template = self.create_icon(rank, div, background_color)

                cv.rectangle(
                    clip,
                    xy,
                    (xy[0] + template.shape[1], xy[1] + template.shape[0]),
                    (0, 0, 255),
                    1,
                )
                cv.putText(
                    clip,
                    f"{rank[0].upper()}{div} {error:.3f}",
                    (xy[0], xy[1] + int(15 * self.fx) + template.shape[0]),
                    cv.FONT_HERSHEY_SIMPLEX,
                    self.fx,
                    (255, 255, 255),
                )

            # plt.imshow(clip[:, :, ::-1])
            # plt.show()
            debug_img = clip

        return converted_matches, debug_img

    def perform_ocr(self, region):
        clip = self.get_clip(region)
        gray = cv.cvtColor(clip, cv.COLOR_BGR2GRAY)
        if region.invert:
            gray = 255 - gray
        # plt.imshow(gray, cmap="gray");plt.show()
        return pytesseract.image_to_string(
            gray, config=f"--psm {region.psm} -l eng+jpn+rus"
        )

    def parse_screenshot(self, debug=False):
        clip = self.get_clip(regions["first row background"])
        bg_color = self.determine_background_color(clip)
        clip = self.get_clip(regions["fourth row background"])
        bg_color4 = self.determine_background_color(clip)

        sq_diff = sum((bg_color - bg_color4) ** 2)
        has_4_rows = sq_diff < 3 * (20**2)

        icon_region = self.get_clip(regions["rank icons"])
        icons, debug_img = self.find_icons(icon_region, bg_color, debug=debug)

        current = Ranks()
        season_high = Ranks()

        if has_4_rows:
            rank_keys = ["combined", "tank", "damage", "support"]
        else:
            rank_keys = ["tank", "damage", "support"]
        for idx, key in enumerate(rank_keys):
            if val := icons.get((0, idx)):
                setattr(current, key, Rank(val[0], val[1]))
            if val := icons.get((1, idx)):
                setattr(season_high, key, Rank(val[0], val[1]))

        nick = self.perform_ocr(regions["nick"])

        hours = self.perform_ocr(regions["hours"])

        season = self.perform_ocr(regions["competitive season"])

        try:
            hours_int = int(re.sub(r"[^\d]+", "", hours))
        except ValueError:
            hours_int = None

        return ParsedScreenshot(
            current=current,
            season_high=season_high,
            nick_raw=nick,
            nick=re.sub(r"\W+.*$", "", nick),
            hours_raw=hours,
            hours=hours_int,
            season_raw=season,
            season=re.sub(r"[^ \w]+$", "", season),
            debug_img=debug_img,
        )


def _reply(client, interaction, content, **more):
    client.patch(
        f"https://discord.com/api/v10/webhooks/{APPID}/{interaction.token}/messages/@original",
        headers={"Authorization": f"Bot {TOKEN}"},
        json={"content": content, "flags": 64, **more},
    )


@dramatiq.actor(min_backoff=2500, max_backoff=60000, max_retries=10, time_limit=30000)
def process_image(interaction_json: str):
    interaction = CommandInteraction.parse_raw(interaction_json)

    db = Database()
    with ExitStack() as stack:
        stack.enter_context(PROCESS_RATELIMIT.acquire())
        client = stack.enter_context(httpx.Client())
        session = stack.enter_context(db.Session())

        attachment = interaction.data.resolved.attachments[
            int(interaction.data.options[0].value)
        ]
        print(attachment)

        if attachment.size > 8 * 1024 * 1024:
            _reply(client, interaction, f"file too large ({attachment.size})")
            return
        elif not attachment.content_type.startswith("image/"):
            _reply(client, interaction, "That's not an image")
            return
        elif not any(
            math.isclose(attachment.width / attachment.height, x)
            for x in (16 / 9, 16 / 10)
        ):
            _reply(
                client,
                interaction,
                "Image has incorrect dimensions. It must be in 16:9 or 16:10.",
            )
            return

        user = db.user_by_discord_id(session, interaction.member.user.id)

        if user is None:
            _reply(
                client,
                interaction,
                "You are not registered. You need to register first.",
            )
            return

        print(">>>> USER IS ", user.handles)

        # _reply(client, interaction, f"downloading {attachment.url} ({attachment.size} bytes)")

        resp: httpx.Response = httpx.get(attachment.url)
        resp.raise_for_status()
        raw = np.fromstring(resp.read(), np.uint8)
        img = cv.imdecode(raw, cv.IMREAD_COLOR)
        if img is None:
            _reply(client, interaction, "Can't decode image!")
            return

        data = ScreenshotReader(img).parse_screenshot(debug=True)

        def convert_btag(handle):
            return handle.battle_tag.upper().split("#", 1)[0]

        matches = get_close_matches(
            data.nick, [convert_btag(h) for h in user.handles], n=1
        )
        try:
            matching_btag = matches[0]
        except IndexError:
            matching_btag = None

        matching_handle: Optional[Handle] = None

        if matching_btag:
            for handle in user.handles:
                if matching_btag == convert_btag(handle):
                    matching_handle = handle

            nickname_str = f"{matching_btag} :white_check_mark:"
            if matching_btag != data.nick:
                nickname_str += f"\n*(corrected from {data.nick})*"
        else:
            nickname_str = f"{data.nick} :x:\n*(not found in database)*"

        rank_field_list = [
            {
                "name": role.capitalize(),
                "value": f"__{getattr(data.current, role)}__ *(current)* \n{getattr(data.season_high, role)} *(season high)*",
                "inline": role != "combined",
            }
            for role in "combined tank damage support".split()
        ]

        submit_button = {
            "type": 2,
            "style": 1,
            "custom_id": "ok",
            "emoji": {"name": "👍"},
            "label": "Everything is correct. Update the database.",
        }

        no_submit_button = {
            "type": 2,
            "style": 2,
            "custom_id": "ok",
            "emoji": {"name": "👍"},
            "label": "You've read everything correctly. I will fix the errors and try again.",
        }

        review_button = {
            "type": 2,
            "style": 2,
            "custom_id": "shit",
            "emoji": {"name": "👎"},
            "label": "You've made a mistake. Let Efi have a look!",
        }

        if matching_btag:
            txt = (
                'Please make sure that **all** information, including your season high and "hours played" '
                "is correct. "
                "I've attached an image of where I think the rank icons are. Make sure I detected "
                "all of them, and identified them correctly. If not, please request a review so Efi can take a "
                "look."
            )
            buttons = [submit_button, review_button]
        else:
            txt = (
                f"None of your registered accounts is named *{data.nick}*, I even checked for "
                "slight differences in case I misread. That means one of two things: "
                "you either tried to submit a screenshot that belongs to an account you "
                "haven't registered yet – in that case please register it first; or "
                "I completely misread your nickname (damn you, "
                "Sombra!) – in that case please submit the image for review "
                "so Efi can adjust my reading glasses."
            )
            buttons = [no_submit_button, review_button]

        res = client.patch(
            f"https://discord.com/api/v10/webhooks/{APPID}/{interaction.token}/messages/@original",
            headers={"Authorization": f"Bot {TOKEN}"},
            data={
                "payload_json": json.dumps(
                    {
                        "content": str(data),
                        "components": [
                            {
                                "type": 1,
                                "components": buttons,
                            },
                        ],
                        "flags": 64,
                        "embeds": [
                            {
                                "image": {
                                    "url": "attachment://debug.png",
                                },
                                "footer": {
                                    "text": (
                                        "Order of icons is (from top to bottom): Combined, Tank, "
                                        'Damage, Support. The "Combined" row is missing when there are only 3 rows. '
                                        "Left side is current, right side is season high. (If you're "
                                        "curious: the numbers after the division indicate how sure Orisa "
                                        "is, 0.000 means a perfect match. They are purely informational.)"
                                    )
                                },
                                "fields": [
                                    {
                                        "name": R":warning: Early Alpha Warning:warning:",
                                        "value": (
                                            "This feature is in early alpha, expect a lot of rough edges! "
                                            ":robot::screwdriver::girl:\n"
                                            "Please [join the support server](https://discord.gg/ZKzBEDF) if you use this feature."
                                        ),
                                        "inline": False,
                                    },
                                    {
                                        "name": "Screenshot analyzed :mag:",
                                        "value": txt,
                                        "inline": False,
                                    },
                                    {
                                        "name": "Nickname",
                                        "value": nickname_str,
                                        "inline": True,
                                    },
                                    {
                                        "name": "Hours played",
                                        "value": str(data.hours),
                                        "inline": True,
                                    },
                                    {
                                        "name": "Season",
                                        "value": data.season,
                                        "inline": False,
                                    },
                                    *rank_field_list,
                                ],
                            }
                        ],
                    }
                )
            },
            files=[
                (
                    "files[0]",
                    (
                        "debug.png",
                        cv.imencode(".png", data.debug_img)[1].tobytes(),
                        "image/png",
                    ),
                ),
            ],
        )
        if res.is_error:
            print(res, res.read())


if __name__ == "__main__":
    for path in Path("ow screenshots").glob("*.jpg"):
        print(path, flush=True)
        try:
            print(parse_screenshot(cv.imread(str(path)), False))
        except Exception as e:
            __import__("traceback").print_exception(e)
