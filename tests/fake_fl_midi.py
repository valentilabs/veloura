"""Fake FL Studio MIDI-scripting modules (channels, patterns, general, mixer, midi, ui, device)
for offline tests of device_VelouraController.py. SIMULATION ONLY.
"""

import types


class FakeFL:
    def __init__(self, names=("Kick", "Clap", "Hat", "Snare", "Pluck")):
        self.names = list(names)
        self.grid = {}      # (channel, pattern, step) -> velocity
        self.pattern = 1
        self.pattern_count = 3
        self.pattern_len = 64
        self.tempo = 140.0
        self.undo_points = []
        self.out_frames = []
        self.modules = self._build()

    def _build(self):
        fl = self
        channels = types.ModuleType("channels")
        channels.channelCount = lambda *a: len(fl.names)
        channels.getChannelName = lambda i, *a: fl.names[i]
        fl.route = {}       # channel -> mixer track (default: channel i on insert i+1)
        channels.getTargetFxTrack = lambda i, *a: fl.route.get(i, i + 1)
        channels.setTargetFxTrack = lambda i, t, *a: fl.route.__setitem__(i, t)
        channels.getChannelColor = lambda i, *a: 0x5F6A73
        channels.getChannelType = lambda i, *a: 2 if "osc" in fl.names[i].lower() or "flex" in fl.names[i].lower() else 0
        channels.isChannelSelected = lambda i, *a: i == fl.selected
        channels.getGridBit = lambda i, s, *a: (i, fl.pattern, s) in fl.grid

        def set_grid(i, s, v, *a):
            if v:
                fl.grid.setdefault((i, fl.pattern, s), 100)
            else:
                fl.grid.pop((i, fl.pattern, s), None)
        channels.setGridBit = set_grid
        fl.shift = {}
        channels.getCurrentStepParam = lambda i, s, p, *a: (fl.grid.get((i, fl.pattern, s), 100) if p == 1 else
                                                           fl.shift.get((i, fl.pattern, s), 0) if p == 7 else 0)

        def set_param(i, pat, s, p, v, *a):
            if p == 1 and (i, pat, s) in fl.grid:
                fl.grid[(i, pat, s)] = v
            if p == 7:
                fl.shift[(i, pat, s)] = v
        channels.setStepParameterByIndex = set_param

        patterns = types.ModuleType("patterns")
        patterns.patternNumber = lambda: fl.pattern
        patterns.patternCount = lambda: fl.pattern_count
        patterns.getPatternName = lambda n: "Pattern %d" % n
        patterns.getPatternLength = lambda n: fl.pattern_len

        def jump(n):
            fl.pattern = n
        patterns.jumpToPattern = jump

        midi = types.ModuleType("midi")
        midi.UF_None = 0
        midi.FPN_Preset = 6
        midi.UF_PR = 2
        midi.UF_SS = 2
        midi.REC_Tempo = 5
        midi.REC_Control = 1
        midi.REC_UpdateControl = 2
        midi.widPianoRoll = 3
        midi.REC_Chan_PianoRoll = 0x4000
        midi.EE_PR = 1

        general = types.ModuleType("general")
        general.getVersion = lambda: 36
        general.getRecPPQ = lambda: 96
        general.saveUndo = lambda name, flags, *a: fl.undo_points.append(name)

        def rec(event, value, flags):
            if event == midi.REC_Tempo:
                fl.tempo = value / 1000.0
        general.processRECEvent = rec

        mixer = types.ModuleType("mixer")
        mixer.getCurrentTempo = lambda *a: int(fl.tempo * 1000)
        fl.peaks = {}
        mixer.trackCount = lambda: 10
        mixer.getTrackPeaks = lambda i, mode: fl.peaks.get(i, 0.0)
        fl.track_names = {}
        mixer.getTrackName = lambda i: fl.track_names.get(i, "Master" if i == 0 else "Insert %d" % i)
        mixer.setTrackName = lambda i, n: fl.track_names.__setitem__(i, n)
        mixer.setTrackColor = lambda i, c: None
        fl.eq = {}          # (track, band) -> [gain 0..1, freq 0..1]
        mixer.getEqBandCount = lambda: 3
        _eqv = lambda t, b: fl.eq.setdefault((t, b), [0.5, (0.09, 0.5, 0.85)[b]])
        mixer.getEqGain = lambda t, b, mode=0: _eqv(t, b)[0] if mode == 0 else (_eqv(t, b)[0] - 0.5) * 36.0
        mixer.getEqFrequency = lambda t, b, mode=0: _eqv(t, b)[1] if mode == 0 else 20.0 * (1000.0 ** _eqv(t, b)[1])
        mixer.setEqGain = lambda t, b, v: _eqv(t, b).__setitem__(0, v)
        mixer.setEqFrequency = lambda t, b, v: _eqv(t, b).__setitem__(1, v)
        transport = types.ModuleType("transport")
        fl.playing = False
        transport.isPlaying = lambda: fl.playing
        fl.selected = 0
        midi.FPT_F7 = 0x45

        def global_transport(cmd, value, *a):
            if cmd == midi.FPT_F7:
                fl.open_roll = fl.selected
        transport.globalTransport = global_transport

        fl.open_roll = None
        fl.selected = 0
        fl.roll_caption_override = None
        channels.selectOneChannel = lambda i, *a: setattr(fl, "selected", i)
        channels.getRecEventId = lambda i, *a: i << 16

        ui = types.ModuleType("ui")

        def open_editor(event_id, mode, *a):
            fl.open_roll = event_id >> 16
        ui.openEventEditor = open_editor
        ui.getFocusedFormCaption = lambda: fl.roll_caption_override or (
            "Piano roll - %s" % fl.names[fl.open_roll] if fl.open_roll is not None else "Channel rack")
        ui.showWindow = lambda w: None
        ui.getVisible = lambda w: fl.open_roll is not None
        ui.hideWindow = lambda w: None
        ui.setFocused = lambda w: None
        ui.getFocused = lambda w: True

        device = types.ModuleType("device")
        device.midiOutSysex = lambda data: fl.out_frames.append(bytes(data))
        import math
        fl.ch_vol, fl.ch_pan, fl.ch_mute = {}, {}, set()
        channels.getChannelVolume = lambda i, *a: fl.ch_vol.get(i, 0.78125)
        channels.setChannelVolume = lambda i, v, *a: fl.ch_vol.__setitem__(i, v)
        channels.getChannelPan = lambda i, *a: fl.ch_pan.get(i, 0.0)
        channels.setChannelPan = lambda i, v, *a: fl.ch_pan.__setitem__(i, v)
        channels.isChannelMuted = lambda i, *a: i in fl.ch_mute
        channels.muteChannel = lambda i, v=-1, *a: (fl.ch_mute.add(i) if v else fl.ch_mute.discard(i))
        fl.tr_vol, fl.tr_pan, fl.tr_mute = {}, {}, set()

        def get_vol(i, mode=0):
            v = fl.tr_vol.get(i, 0.8)
            return v if mode == 0 else (-100.0 if v <= 0 else 40 * math.log10(v / 0.8))  # simulated fader curve
        mixer.getTrackVolume = get_vol
        mixer.setTrackVolume = lambda i, v, *a: fl.tr_vol.__setitem__(i, v)
        mixer.getTrackPan = lambda i: fl.tr_pan.get(i, 0.0)
        mixer.setTrackPan = lambda i, v, *a: fl.tr_pan.__setitem__(i, v)
        mixer.isTrackMuted = lambda i: i in fl.tr_mute
        mixer.muteTrack = lambda i, v=-1: (fl.tr_mute.add(i) if v else fl.tr_mute.discard(i))
        plugins = types.ModuleType("plugins")
        fl.fx = {(2, 0): {"name": "Fruity Reeverb 2", "params": [["Wet", 0.2], ["Decay", 0.5]]}}
        fl.presets = {}     # channel -> {"plugin": name, "names": [...], "cur": index}
        plugins.isValid = lambda i, slot=-1, *a: (i, slot) in fl.fx or (slot == -1 and i in fl.presets)
        plugins.getPluginName = lambda i, slot=-1, *a: (fl.presets[i]["plugin"] if slot == -1 and i in fl.presets
                                                         else fl.fx[(i, slot)]["name"])
        plugins.getPresetCount = lambda i, slot=-1, *a: len(fl.presets[i]["names"]) if i in fl.presets else 1

        def get_name(i, slot, flag, n=-1, *a):
            pr = fl.presets[i]
            return pr["names"][pr["cur"] if n == -1 else n]
        plugins.getName = get_name

        def step(i, d):
            pr = fl.presets[i]
            pr["cur"] = (pr["cur"] + d) % len(pr["names"])
            fl.names[i] = pr["names"][pr["cur"]]   # FL renames the channel to the loaded preset
        plugins.nextPreset = lambda i, slot=-1, *a: step(i, 1)
        plugins.prevPreset = lambda i, slot=-1, *a: step(i, -1)
        channels.setChannelName = lambda i, name, *a: fl.names.__setitem__(i, name)
        plugins.getParamCount = lambda i, slot=-1, *a: len(fl.fx[(i, slot)]["params"])
        plugins.getParamName = lambda pi, i, slot=-1, *a: fl.fx[(i, slot)]["params"][pi][0]
        plugins.getParamValue = lambda pi, i, slot=-1, *a: fl.fx[(i, slot)]["params"][pi][1]
        plugins.getParamValueString = lambda pi, i, slot=-1, *a: "%d%%" % round(fl.fx[(i, slot)]["params"][pi][1] * 100)

        def set_param(v, pi, i, slot=-1, *a):
            fl.fx[(i, slot)]["params"][pi][1] = v
        plugins.setParamValue = set_param
        return {"channels": channels, "patterns": patterns, "midi": midi, "general": general, "mixer": mixer, "transport": transport,
                "plugins": plugins,
                "ui": ui, "device": device}


class SysexEvent:
    def __init__(self, data):
        self.sysex = data
        self.handled = False


class LoopbackTransport:
    """Delivers host frames straight into the controller script's OnSysEx and returns its output frames."""

    def __init__(self, fl, script_ns):
        self.fl = fl
        self.ns = script_ns
        self.on_frame = None

    def send(self, frame):
        self.ns["OnSysEx"](SysexEvent(frame))
        if "OnIdle" in self.ns:              # FL runs queued requests on its idle tick
            for _ in range(5):
                self.ns["OnIdle"]()
        frames, self.fl.out_frames[:] = list(self.fl.out_frames), []
        for f in frames:
            self.on_frame(f)

    def close(self):
        pass
