from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtGui import QColor, QFontDatabase


SUPPORTED_RENDERER_MODES = {
    "gm_modern",
    "dark_parchment",
    "rpg_retro",
}

DEFAULT_OVERLAY_THEME = {
    "renderer_mode": "gm_modern",
    "bg": "#000000",
    "combat_bg": "#121212",
    "combat_bdr": "#333333",
    "dialog_bg": "#121212",
    "dialog_bdr": "#333333",
    "turn_bg": "#4A4A4A",
    "friendly_bg": "#2A2A2A",
    "friendly_text": "#77DD77",
    "enemy_bg": "#2A2A2A",
    "enemy_text": "#F08080",
    "neutral_bg": "#2A2A2A",
    "neutral_text": "#FADFAD",
    "text": "#FFFFFF",
    "metric_fill": "#28C878",
    "metric_track": "#282828",
    "condition_text": "#FFFFFF",
    "condition_bg": "#282828",
    "condition_border": "#C8C8C8",
    "speaker_text": "#FFFFFF",
    "font_combat_name": "Arial",
    "font_combat_hp": "Arial",
    "font_combat_init": "Arial",
    "font_dialog": "Arial",
    "font_base_size": 16,
    "font_dialog_size": 18,
    "font_small_size": 10,
    "layout": {
        "grid": {"cols": 100, "rows": 100, "margin": 0, "gutter": 0},
        "regions": {
            "right_column": {"gridRect": [65, 5, 30, 1]},
            "dialog_box": {"gridRect": [5, 78, 58, 18]},
        },
    },
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _color(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip() and QColor(value.strip()).isValid():
        return value.strip()
    return fallback


def _font_family(value: Any, fallback: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    candidate = value.strip()
    try:
        installed = {family.casefold() for family in QFontDatabase.families()}
    except Exception:
        installed = set()
    if installed and candidate.casefold() not in installed:
        return fallback
    return candidate


def _integer(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return value if minimum <= value <= maximum else fallback


def _grid_rect(value: Any, fallback: list[int], cols: int, rows: int) -> list[int]:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
    ):
        return list(fallback)
    x, y, width, height = value
    if (
        x < 0
        or y < 0
        or width <= 0
        or height <= 0
        or x + width > cols
        or y + height > rows
    ):
        return list(fallback)
    return [x, y, width, height]


def _default_region_rect(name: str, cols: int, rows: int) -> list[int]:
    if name == "right_column":
        x = min(cols - 1, max(0, int(cols * 0.65)))
        y = min(rows - 1, max(0, int(rows * 0.05)))
        return [x, y, max(1, cols - x), 1]
    x = min(cols - 1, max(0, int(cols * 0.05)))
    y = min(rows - 1, max(0, int(rows * 0.78)))
    width = max(1, min(cols - x, int(cols * 0.58)))
    height = max(1, min(rows - y, int(rows * 0.18)))
    return [x, y, width, height]


def _parse_layout(document: Mapping[str, Any]) -> dict[str, Any]:
    defaults = DEFAULT_OVERLAY_THEME["layout"]
    layout = _mapping(document.get("layout"))
    grid = _mapping(layout.get("grid"))
    cols = _integer(grid.get("cols"), defaults["grid"]["cols"], 1, 256)
    rows = _integer(grid.get("rows"), defaults["grid"]["rows"], 1, 256)
    margin = _integer(grid.get("margin"), defaults["grid"]["margin"], 0, 256)
    gutter = _integer(grid.get("gutter"), defaults["grid"]["gutter"], 0, 128)
    regions = _mapping(layout.get("regions"))
    parsed_regions = {}
    for name in ("right_column", "dialog_box"):
        region = _mapping(regions.get(name))
        parsed_regions[name] = {
            "gridRect": _grid_rect(
                region.get("gridRect"),
                (
                    defaults["regions"][name]["gridRect"]
                    if cols == defaults["grid"]["cols"] and rows == defaults["grid"]["rows"]
                    else _default_region_rect(name, cols, rows)
                ),
                cols,
                rows,
            )
        }
    return {
        "grid": {
            "cols": cols,
            "rows": rows,
            "margin": margin,
            "gutter": gutter,
        },
        "regions": parsed_regions,
    }


def parse_overlay_theme(document: Any) -> dict[str, Any]:
    theme = deepcopy(DEFAULT_OVERLAY_THEME)
    if not isinstance(document, Mapping):
        return theme

    mode = document.get("renderer_mode")
    if isinstance(mode, str) and mode in SUPPORTED_RENDERER_MODES:
        theme["renderer_mode"] = mode

    if "vars" not in document:
        for key, fallback in DEFAULT_OVERLAY_THEME.items():
            if key in {"layout", "renderer_mode"}:
                continue
            value = document.get(key)
            if key.startswith("font_") and key.endswith("_size"):
                theme[key] = _integer(value, fallback, 6, 72)
            elif key.startswith("font_"):
                theme[key] = _font_family(value, fallback)
            else:
                theme[key] = _color(value, fallback)
        theme["layout"] = _parse_layout(document)
        return theme

    variables = _mapping(document.get("vars"))
    colors = _mapping(variables.get("colors"))
    fonts = _mapping(variables.get("fonts"))

    color_map = {
        "combat_bg": "card_bg",
        "combat_bdr": "border_idle",
        "dialog_bg": "dialog_bg",
        "dialog_bdr": "dialog_border",
        "turn_bg": "border_active",
        "text": "text",
        "metric_fill": "metric_fill",
        "metric_track": "metric_track",
        "condition_text": "condition_text",
        "condition_bg": "condition_bg",
        "condition_border": "condition_border",
        "speaker_text": "speaker_text",
    }
    for target, source in color_map.items():
        theme[target] = _color(colors.get(source), theme[target])

    card_bg = theme["combat_bg"]
    text = theme["text"]
    theme["friendly_bg"] = card_bg
    theme["enemy_bg"] = card_bg
    theme["neutral_bg"] = card_bg
    theme["friendly_text"] = _color(colors.get("hp_good"), theme["friendly_text"])
    theme["enemy_text"] = _color(colors.get("hp_back"), theme["enemy_text"])
    theme["neutral_text"] = text

    family = _font_family(fonts.get("base_family"), theme["font_combat_name"])
    theme["font_combat_name"] = family
    theme["font_combat_hp"] = family
    theme["font_combat_init"] = family
    theme["font_dialog"] = family
    theme["font_base_size"] = _integer(
        fonts.get("base_size"), theme["font_base_size"], 6, 72
    )
    theme["font_dialog_size"] = _integer(
        fonts.get("dialog_size"), theme["font_dialog_size"], 6, 72
    )
    theme["font_small_size"] = _integer(
        fonts.get("small_size"), theme["font_small_size"], 6, 72
    )
    theme["layout"] = _parse_layout(document)
    return theme


def load_overlay_theme(path: Path) -> dict[str, Any]:
    try:
        with Path(path).open("r", encoding="utf-8") as source:
            return parse_overlay_theme(json.load(source))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return deepcopy(DEFAULT_OVERLAY_THEME)


def overlay_region_rect(
    theme: Mapping[str, Any],
    region_name: str,
    canvas_width: int,
    canvas_height: int,
) -> tuple[int, int, int, int]:
    fallback_layout = DEFAULT_OVERLAY_THEME["layout"]
    layout = _mapping(theme.get("layout"))
    grid = _mapping(layout.get("grid"))
    cols = _integer(grid.get("cols"), fallback_layout["grid"]["cols"], 1, 256)
    rows = _integer(grid.get("rows"), fallback_layout["grid"]["rows"], 1, 256)
    margin = _integer(grid.get("margin"), fallback_layout["grid"]["margin"], 0, 256)
    gutter = _integer(grid.get("gutter"), fallback_layout["grid"]["gutter"], 0, 128)
    regions = _mapping(layout.get("regions"))
    region = _mapping(regions.get(region_name))
    fallback = (
        fallback_layout["regions"].get(
            region_name, {"gridRect": [0, 0, cols, rows]}
        )["gridRect"]
        if cols == fallback_layout["grid"]["cols"] and rows == fallback_layout["grid"]["rows"]
        else _default_region_rect(region_name, cols, rows)
    )
    grid_rect = _grid_rect(region.get("gridRect"), fallback, cols, rows)

    usable_width = canvas_width - margin * 2 - gutter * (cols - 1)
    usable_height = canvas_height - margin * 2 - gutter * (rows - 1)
    if usable_width <= 0 or usable_height <= 0:
        return overlay_region_rect(
            DEFAULT_OVERLAY_THEME,
            region_name,
            canvas_width,
            canvas_height,
        )

    cell_width = usable_width / cols
    cell_height = usable_height / rows
    x, y, width, height = grid_rect
    left = margin + x * (cell_width + gutter)
    top = margin + y * (cell_height + gutter)
    pixel_width = width * cell_width + max(0, width - 1) * gutter
    pixel_height = height * cell_height + max(0, height - 1) * gutter
    return (
        max(0, round(left)),
        max(0, round(top)),
        max(1, round(pixel_width)),
        max(1, round(pixel_height)),
    )
