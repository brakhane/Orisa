#!/usr/bin/env python3

import json
import glob
from contextlib import suppress
from operator import itemgetter

from babel import Locale

complete = []
incomplete = []

for fn in glob.glob("orisa/locale/stats/*_stats.json"):
    with open(fn) as f:
        data = json.load(f)
        loc = data["code"]
        data["native_name"] = Locale.parse(loc).get_display_name(loc).title()
    with suppress(IOError):
        with open(f"orisa-web/locale/stats/{loc}_stats.json") as f:
            data["web_percent_translated"] = json.load(f)["percent_translated"]

    if data["percent_translated"] >= 90:
        complete.append(data)
    else:
        incomplete.append(data)

complete.append({"code": "en", "name": "English", "native_name": "English", "percent_translated": 100, "web_percent_translated": 100})
complete.sort(key=itemgetter("native_name"))
incomplete.sort(key=itemgetter("native_name"))

info = {"complete": complete, "incomplete": incomplete}

with open("orisa-web/src/generated/translation_info.json", "w", encoding="utf-8") as f:
    json.dump(info, f, ensure_ascii=False, separators=",:")