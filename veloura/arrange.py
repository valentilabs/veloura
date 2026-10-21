"""Arrangement planner: turn a loop into a song map (sections, bars, which groups play, energy).

FL's scripting API can't place Playlist clips, so this is a plan the user follows in the Playlist,
with the shortest practical instructions. Section templates follow each genre's conventions.
"""

GROUPS = ("melody", "drums", "bass", "other")

# (section, bars, energy 0-10, groups on: m=melody d=drums b=bass, lower-case = partial / filtered)
TEMPLATES = {
    "trap": [("Intro", 8, 3, "m"), ("Hook", 16, 9, "MDB"), ("Verse", 16, 7, "mDB"), ("Hook", 16, 9, "MDB"),
             ("Bridge", 8, 5, "Mb"), ("Hook", 16, 10, "MDB"), ("Outro", 8, 2, "m")],
    "plugg": [("Intro", 8, 3, "M"), ("Hook", 16, 8, "MDB"), ("Verse", 16, 7, "MdB"), ("Hook", 16, 9, "MDB"),
              ("Outro", 8, 3, "Mb")],
    "rage": [("Intro", 4, 5, "M"), ("Hook", 16, 10, "MDB"), ("Verse", 16, 8, "mDB"), ("Break", 4, 4, "M"),
             ("Hook", 16, 10, "MDB"), ("Outro", 4, 3, "m")],
    "jerk": [("Intro", 4, 5, "Md"), ("Hook", 16, 9, "MDB"), ("Verse", 16, 8, "mDB"), ("Hook", 16, 9, "MDB"),
             ("Outro", 4, 3, "d")],
    "drill": [("Intro", 8, 3, "M"), ("Hook", 16, 8, "MDB"), ("Verse", 16, 7, "mDB"), ("Hook", 16, 8, "MDB"),
              ("Verse", 16, 7, "mDB"), ("Outro", 8, 2, "M")],
    "melodic rap": [("Intro", 8, 3, "M"), ("Verse", 16, 6, "MdB"), ("Hook", 16, 8, "MDB"), ("Verse", 16, 6, "MdB"),
                    ("Hook", 16, 9, "MDB"), ("Bridge", 8, 4, "M"), ("Hook", 16, 9, "MDB"), ("Outro", 8, 2, "m")],
    "ambient": [("Intro", 8, 2, "m"), ("A", 16, 5, "MdB"), ("B", 16, 6, "MDB"), ("A", 16, 5, "MdB"), ("Outro", 8, 2, "m")],
    "boom bap": [("Intro", 4, 3, "M"), ("Verse", 16, 6, "MDB"), ("Hook", 8, 7, "MDB"), ("Verse", 16, 6, "MDB"),
                 ("Hook", 8, 7, "MDB"), ("Outro", 4, 2, "M")],
    "detroit": [("Intro", 4, 4, "M"), ("Verse", 16, 7, "MDB"), ("Hook", 8, 8, "MDB"), ("Verse", 16, 7, "MDB"),
                ("Hook", 8, 8, "MDB"), ("Outro", 4, 2, "M")],
}
ALIASES = {"dark trap": "trap", "melodic plugg": "plugg", "melodic trap": "melodic rap", "cloud rap": "ambient",
           "r&b": "melodic rap", "pop": "melodic rap"}
TIPS = {
    "Intro": "Melody only (or filtered). Drums come in at the hook.",
    "Hook": "Everything in. This is the loop at full energy.",
    "Verse": "Drop a melody layer or thin the hats so a vocal has room.",
    "Bridge": "Strip it back: melody and 808, no drums.",
    "Break": "One bar of silence or melody only, then slam back in.",
    "Outro": "Melody alone, fade or end on beat 1.",
    "A": "Main section.", "B": "Add the extra layer or busier drums.",
}


def plan(genre=None, loop_bars=8, groups_present=None):
    g = (genre or "trap").lower()
    t = TEMPLATES.get(ALIASES.get(g, g), TEMPLATES["trap"])
    present = set(groups_present or GROUPS)
    sections, bar = [], 1
    for name, bars, energy, code in t:
        active = {}
        for grp, ch in (("melody", "m"), ("drums", "d"), ("bass", "b")):
            if grp not in present:
                continue
            active[grp] = "full" if ch.upper() in code else ("partial" if ch in code else "off")
        if "other" in present:
            active["other"] = "full" if energy >= 7 else "off"
        repeats = max(1, round(bars / max(1, loop_bars)))
        sections.append({"name": name, "start_bar": bar, "bars": bars, "energy": energy, "groups": active,
                         "tip": TIPS.get(name, ""), "loop_repeats": repeats})
        bar += bars
    return {"genre": g, "sections": sections, "total_bars": bar - 1, "loop_bars": loop_bars,
            "how": ["In the Playlist, paint your pattern across the bars for each section.",
                    "For sections marked off, split the pattern: make a copy (Pattern ▸ Clone) and delete that group's notes.",
                    "Put a 1-beat dropout (no kick or 808) right before each hook."]}
