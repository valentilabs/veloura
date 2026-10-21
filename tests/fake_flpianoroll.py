"""A stand-in for FL Studio's `flpianoroll` module, for offline tests only.

It mimics the documented API surface (Note, score, Utils) closely enough to
exercise veloura_bridge.pyscript's logic. Passing tests here are SIMULATED
results; they do not prove anything about real FL Studio behaviour.
"""


class Note:
    def __init__(self):
        self.number = 60
        self.time = 0
        self.length = 48
        self.group = 0
        self.pan = 0.5
        self.velocity = 0.8
        self.release = 0.5
        self.color = 0
        self.fcut = 0.5
        self.fres = 0.5
        self.pitchofs = 0
        self.slide = False
        self.porta = False
        self.muted = False
        self.selected = False
        self.repeats = 0

    def clone(self):
        n = Note()
        n.__dict__.update(self.__dict__)
        return n


class _Score:
    def __init__(self):
        self.reset()

    def reset(self, ppq=96, tsnum=4, tsden=4):
        self.PPQ = ppq
        self.tsnum = tsnum
        self.tsden = tsden
        self.notes = []
        self.timeline = (0, -1)
        self.fail_on_add_after = None  # simulate a crash part-way through

    @property
    def noteCount(self):
        return len(self.notes)

    def addNote(self, note):
        if self.fail_on_add_after is not None and len(self.notes) >= self.fail_on_add_after:
            raise RuntimeError("simulated crash")
        # FL stores velocity in limited precision; mimic a small rounding.
        n = note.clone()
        n.velocity = round(n.velocity, 4)
        self.notes.append(n)

    def getNote(self, i):
        return self.notes[i]

    def deleteNote(self, i):
        del self.notes[i]

    def getTimelineSelection(self):
        return self.timeline


class _Utils:
    def __init__(self):
        self.messages = []
        self.logs = []

    def ShowMessage(self, msg):
        self.messages.append(msg)

    def log(self, msg):
        self.logs.append(msg)


score = _Score()
Utils = _Utils()
