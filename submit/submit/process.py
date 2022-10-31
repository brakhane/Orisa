import cv2 as cv
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt
import pytesseract
from dataclasses import dataclass
from collections import namedtuple
from typing import Optional
from bisect import bisect
import re


pytesseract.pytesseract.tesseract_cmd = r"d:\tesseract-ocr\tesseract.exe"


Coords = namedtuple("Coords", "x y")


@dataclass
class Region:
    top_left: Coords
    bottom_right: Coords
    psm: Optional[int] = None


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
    hours: int
    current: Ranks
    season_high: Ranks


regions = {
    "nick": Region(Coords(560, 370), Coords(1600, 590), psm=8),
    "competitive season": Region(Coords(2110, 810), Coords(2800, 870), psm=7),
    "first row background": Region(Coords(2180, 1950), Coords(2360, 2050)),
    "hours": Region(Coords(400, 1360), Coords(870, 1460), psm=7),
    "rank icons": Region(Coords(1990, 1930), Coords(2660, 2500)),
    "fourth row background": Region(Coords(2180, 2400), Coords(2360, 2480)),
}


def determine_background_color(clip):

    row_avg = np.average(clip, axis=0)
    avg = np.average(row_avg, axis=0)
    return np.array([int(x) for x in avg])


def get_clip(image, region, fx, fy):
    return image[
        int(region.top_left.y * fy) : int(region.bottom_right.y * fy),
        int(region.top_left.x * fx) : int(region.bottom_right.x * fx),
    ]


def create_icon(
    rank: str, division: int, background_color, fx: float = 1, fy: float = 1
):
    if fx < 1:
        bg = cv.imread(f"template-div-{division}.png", cv.IMREAD_UNCHANGED)
        symbol = cv.imread(f"template-rank-{rank}.png", cv.IMREAD_UNCHANGED)
        fx *= 2
        fy *= 2
    else:
        bg = cv.imread(f"hq-template-div-{division}.png", cv.IMREAD_UNCHANGED)
        symbol = cv.imread(f"hq-template-rank-{rank}.png", cv.IMREAD_UNCHANGED)

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


def find_icons(image, background_color, fx, fy, *, debug=False):
    matches = {}
    for rank in "bronze silver gold platinum diamond master gm".split():
        for div in range(1, 6):
            template = create_icon(rank, div, background_color, fx, fy)
            res = cv.matchTemplate(image, template, cv.TM_SQDIFF_NORMED)

            # ic_r, ic_g, ic_b = cv.split(image)
            # tem_r, tem_g, tem_b = cv.split(template)
            # res_r = cv.matchTemplate(ic_r, tem_r, cv.TM_SQDIFF_NORMED)
            # res_g = cv.matchTemplate(ic_g, tem_g, cv.TM_SQDIFF_NORMED)
            # res_b = cv.matchTemplate(ic_b, tem_b, cv.TM_SQDIFF_NORMED)

            # res = res_r + res_g + res_b
            # thres = 3*0.25
            # res = res_r * res_g * res_b
            # thres = 0.21**3
            thres = 0.21
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
    h, w = image.shape[:2]
    converted_matches = {
        (bisect([w / 2], xy[0]), bisect([h / 4, 2 * h / 4, 3 * h / 4], xy[1])): val
        for xy, val in matches.items()
    }

    if debug:
        for xy, v in matches.items():
            rank, div, error = v
            template = create_icon(rank, div, background_color, fx, fy)

            cv.rectangle(
                image,
                xy,
                (xy[0] + template.shape[1], xy[1] + template.shape[0]),
                (0, 0, 255),
                1,
            )
            cv.putText(
                image,
                f"{rank[0].upper()}{div} {error:.3f}",
                (xy[0], xy[1] + int(15 * fx) + template.shape[0]),
                cv.FONT_HERSHEY_SIMPLEX,
                fx,
                (255, 0, 255),
            )

        plt.imshow(image[:, :, ::-1])
        plt.show()
    return converted_matches


def perform_ocr(image, region, fx, fy):
    clip = get_clip(image, region, fx, fy)
    gray = cv.cvtColor(clip, cv.COLOR_BGR2GRAY)
    # plt.imshow(gray, cmap='gray');plt.show()
    return pytesseract.image_to_string(
        gray, config=f"--psm {region.psm} -l eng+jpn+rus"
    )


def process_image(image, debug=False):
    h, w, depth = image.shape
    fx = w / 5120
    fy = w * 9 / 16 / 2880
    clip = get_clip(image, regions["first row background"], fx, fy)
    bg_color = determine_background_color(clip)
    clip = get_clip(image, regions["fourth row background"], fx, fy)
    bg_color4 = determine_background_color(clip)

    sq_diff = sum((bg_color - bg_color4) ** 2)
    has_4_rows = sq_diff < 3 * (20**2)

    icon_region = get_clip(image, regions["rank icons"], fx, fy)
    icons = find_icons(icon_region, bg_color, fx, fy, debug=debug)

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

    nick = perform_ocr(image, regions["nick"], fx, fy)

    hours = perform_ocr(image, regions["hours"], fx, fy)

    season = perform_ocr(image, regions["competitive season"], fx, fy)

    return ParsedScreenshot(
        current=current,
        season_high=season_high,
        nick=re.sub(r"\W+.*$", "", nick),
        hours=hours,  # int(re.sub(r"[^\d]+", "", hours)),
        season=re.sub(r"[^ \w]+$", "", season),
    )


for path in Path("ow screenshots").glob("*.jpg"):
    print(path, process_image(cv.imread(str(path)), False), sep="\n")
