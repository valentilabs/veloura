"""Guided mode (Mode B): step-by-step instructions for things Veloura cannot automate.

These offline templates cover common requests. AI providers can write richer,
context-specific guides in the same shape:

    {"title", "problem", "why", "where", "steps": [..], "settings": [{"control", "value", "range"}],
     "listen_for", "undo"}

The steps name FL Studio stock effects that ship with every edition as far as
we know (Fruity Reeverb 2, Fruity Parametric EQ 2, Fruity Limiter, Fruity
Fast Dist). Each guide asks the user to say so if their screen differs,
because Veloura cannot see the FL interface.
"""

ROUTE_STEPS = [
    "In the Channel Rack, click the channel's name to open its Channel settings, and look at the 'Track' number box "
    "(top right). If it shows '-' or 0, set it to a free Mixer insert number, e.g. the next unused one.",
    "Open the Mixer (F9) and click that insert so it is selected.",
]

TEMPLATES = [
    {
        "keywords": ("reverb", "space", "spacious", "dry", "wet", "room", "atmosphere"),
        "guide": {
            "title": "Add space with Fruity Reeverb 2",
            "problem": "The sound sits flat and dry, with no sense of room around it.",
            "why": "A reverb on the instrument's own Mixer insert adds depth without washing out the drums.",
            "where": "Mixer > the instrument's insert > an empty effect slot",
            "steps": ROUTE_STEPS + [
                "In the insert's effect slots (right side of the Mixer), click an empty slot's arrow and choose "
                "Select > Fruity Reeverb 2.",
                "Start from the default preset, then adjust the controls below.",
            ],
            "settings": [
                {"control": "Decay", "value": "1.5 - 2.5 s", "range": "longer = bigger, washier"},
                {"control": "Low cut", "value": "200 - 400 Hz", "range": "keeps low end out of the reverb"},
                {"control": "Wet", "value": "start low (about 15-20%) and raise slowly", "range": "too high = blurry"},
                {"control": "Pre-delay", "value": "20 - 40 ms", "range": "keeps the attack clear"},
            ],
            "listen_for": "Toggle the slot on and off. The sound should feel further back and wider, while notes stay clear.",
            "undo": "Click the slot's green switch to bypass it, or right-click the slot > Delete.",
        },
    },
    {
        "keywords": ("muddy", "mud", "eq", "boomy", "harsh", "clean", "cleaner", "clarity"),
        "guide": {
            "title": "Clean up the low-mids with Fruity Parametric EQ 2",
            "problem": "Instruments that don't need deep lows add mud that fights the kick and 808.",
            "why": "Cutting unneeded lows and a little 200-500 Hz on melodic sounds leaves room for the low end.",
            "where": "Mixer > each melodic insert > an empty effect slot",
            "steps": ROUTE_STEPS + [
                "Add Select > Fruity Parametric EQ 2 to an empty slot.",
                "Use the leftmost band as a low cut: drag its point to the left edge, then raise its frequency.",
                "Sweep one band with a narrow boost to find a boxy or harsh spot, then turn that boost into a small cut.",
            ],
            "settings": [
                {"control": "Low cut (band 1)", "value": "100 - 200 Hz on melodies and pads", "range": "do not cut the 808 or kick"},
                {"control": "Mud cut", "value": "-2 to -4 dB around 250 - 400 Hz", "range": "gentle and wide"},
                {"control": "Harshness cut", "value": "-2 dB around 2.5 - 4 kHz if piercing", "range": "narrow"},
            ],
            "listen_for": "With the full beat playing, the kick and 808 should get clearer while the melody keeps its character.",
            "undo": "Bypass the EQ with the slot switch, or delete the slot.",
        },
    },
    {
        "keywords": ("hit harder", "harder", "distort", "saturation", "grit", "808 louder", "punch"),
        "guide": {
            "title": "Make the 808 hit harder with saturation",
            "problem": "The 808 is felt more than heard, so it vanishes on small speakers.",
            "why": "Gentle distortion adds harmonics that make the 808 audible on phones and laptops.",
            "where": "Mixer > the 808's insert > an empty effect slot",
            "steps": ROUTE_STEPS + [
                "Add Select > Fruity Fast Dist (or another distortion you own) to an empty slot.",
                "Start subtle and raise it while the beat plays. If your edition lacks this plugin, tell Veloura which ones you have.",
            ],
            "settings": [
                {"control": "Drive / Pre-amp", "value": "start low, raise until the 808 is audible on laptop speakers", "range": "too much = buzzy"},
                {"control": "Mix", "value": "30 - 60%", "range": "blend keeps the sub weight"},
            ],
            "listen_for": "On laptop speakers the 808 notes should be clearly audible, without making the kick sound smaller.",
            "undo": "Bypass or delete the slot.",
        },
    },
    {
        "keywords": ("louder", "loud", "limiter", "master", "volume", "too quiet"),
        "guide": {
            "title": "Raise overall loudness safely with Fruity Limiter",
            "problem": "The beat sounds quieter than reference tracks.",
            "why": "A limiter on the Master raises level while preventing clipping.",
            "where": "Mixer > Master insert > last effect slot",
            "steps": [
                "Open the Mixer (F9) and select the Master insert.",
                "Check whether Fruity Limiter is already in a Master slot (new projects often include it). If not, add it to the last empty slot.",
                "Raise the limiter's Gain slowly while the loudest part of the beat plays.",
            ],
            "settings": [
                {"control": "Gain", "value": "+2 to +6 dB", "range": "stop when the drums lose punch"},
                {"control": "Ceiling", "value": "about -0.3 dB", "range": "prevents clipping"},
            ],
            "listen_for": "Louder overall, while the kick and snare still snap.",
            "undo": "Set Gain back to 0 dB or bypass the slot.",
        },
    },
    {
        "keywords": ("load ", "plugin", "preset", "my sample", "my kit", "drum kit", "find a", "find me a"),
        "guide": {
            "title": "Load a sound from your library into a channel",
            "problem": "Veloura cannot load samples or plugins into FL Studio yet (FL's scripting interface does not allow it).",
            "why": "Your own kits and samples give the beat its character. Loading them takes a few seconds by hand.",
            "where": "FL Studio Browser (left panel) > your sample folder",
            "steps": [
                "In the Browser, open the folder that holds your drum kits or one-shots.",
                "Click a file to preview it. When it fits, drag it onto an empty part of the Channel Rack to create a new sampler channel.",
                "Name the channel (right-click > Rename) so Veloura's instructions match, e.g. 'Kick', '808', 'Bell'.",
                "For an instrument plugin, use Add (top menu) > the plugin name instead.",
            ],
            "settings": [],
            "listen_for": "Play the channel (click its pad). The sound should fit the key and mood of the beat.",
            "undo": "Right-click the channel > Delete.",
        },
    },
]


def match(text):
    t = text.lower()
    out = []
    for tpl in TEMPLATES:
        if any(k in t for k in tpl["keywords"]):
            out.append(dict(tpl["guide"]))
    return out[:2]
