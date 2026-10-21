"""Plain-language help shared by the service's messages. The UI shows the same steps (RECONNECT_STEPS in app/ui/app.js;
tests/test_setup_speed.py keeps the two identical)."""

# The reconnect order that reliably brings Veloura and FL Studio back together.
RECONNECT_STEPS = [
    "Quit FL Studio and quit Veloura.",
    "Open Veloura first.",
    "Then open FL Studio.",
    "Open your project.",
    "Go straight to the Piano Roll.",
    "Link the bridge (Tools > Scripts > veloura_bridge).",
]
RECONNECT_TEXT = "To reconnect: " + " ".join("(%d) %s" % (i + 1, s) for i, s in enumerate(RECONNECT_STEPS))
