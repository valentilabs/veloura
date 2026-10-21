# dmgbuild settings for Veloura-Beta.dmg (used by make-dmg.sh): branded background, icons on the arrow.
import os
app = defines.get("app")  # noqa: F821 (dmgbuild provides `defines`)
format = "UDZO"
compression_level = 9
filesystem = "HFS+"
files = [app]
symlinks = {"Applications": "/Applications"}
background = os.path.join(defines.get("build_dir"), "dmg-background.tiff")  # noqa: F821
window_rect = ((200, 140), (660, 420))
icon_size = 112
text_size = 13
icon_locations = {"Veloura.app": (170, 203), "Applications": (490, 203)}
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
default_view = "icon-view"
