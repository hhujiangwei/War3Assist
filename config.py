"""Configuration models and default keymap. (English build)"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field

# Common virtual key codes -> display names
COMMON_KEYS: dict[int, str] = {
    **{k: chr(k) for k in range(65, 91)},                     # A..Z
    **{k: chr(k) for k in range(48, 58)},                     # 0..9
    **{112 + i: f"F{i + 1}" for i in range(12)},               # F1..F12
    8: "Backspace", 9: "Tab", 13: "Enter", 16: "Shift",
    17: "Ctrl", 18: "Alt", 20: "CapsLock", 32: "Space",
    33: "PageUp", 34: "PageDown", 35: "End", 36: "Home",
    37: "Left", 38: "Up", 39: "Right", 40: "Down",
    45: "Insert", 46: "Delete", 145: "ScrollLock",
    96: "Num0", 97: "Num1", 98: "Num2", 103: "Num7",
    100: "Num4", 101: "Num5", 102: "Num6", 104: "Num8", 105: "Num9",
    186: ";", 187: "=", 188: ",", 189: "-", 190: ".", 191: "/",
    192: "`", 219: "[", 220: "\\", 221: "]", 222: "'",
}
NAME_TO_CODE: dict[str, int] = {name: code for code, name in COMMON_KEYS.items()}


def code_name(code: int) -> str:
    return COMMON_KEYS.get(code, f"VK_{code}")


def name_code(name: str) -> int:
    return NAME_TO_CODE.get(name.upper(), 0)


@dataclass
class SlotConfig:
    """An inventory slot: default_code is the key sent to the game,
    custom_code is the player's custom shortcut. (English build)"""
    slot_index: int
    label: str
    default_code: int
    custom_code: int
    enabled: bool = True


@dataclass
class AppConfig:
    toggle_code: int = 46            # inventory-hotkeys toggle, default Delete
    # HP bars: natively hold the War3 bar key to show ally/enemy HP per faction
    show_all_toggle_code: int = 145  # show ALL hp, default Scroll Lock
    show_ally_toggle_code: int = 34  # show ally hp (hold '['), default PageDown
    show_enemy_toggle_code: int = 33  # show enemy hp (hold ']'), default PageUp
    show_all_default: bool = False
    game_path: str = ""                      # path to War3 executable for "Launch Game"
    slots: list[SlotConfig] = field(default_factory=list)

    @staticmethod
    def default_slots() -> list[SlotConfig]:
        # War3 inventory hotkeys use the phone-dialpad layout (2 cols x 3 rows):
        #   Slot 1/2 -> Num7/Num8, Slot 3/4 -> Num4/Num5, Slot 5/6 -> Num1/Num2
        defaults = [103, 104, 100, 101, 97, 98]
        custom = [90, 88, 67, 86, 66, 78]  # default shortcuts Z X C V B N
        return [
            SlotConfig(slot_index=i, label=f"Slot {i + 1}",
                       default_code=defaults[i], custom_code=custom[i])
            for i in range(6)
        ]


# Persisted config dir for frozen single-file builds (cached after first hit).
_CONFIG_DIR: str | None = None


def _config_path() -> str:
    if not getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "config.json")
    # Single-file build: keep persistent config outside the temp unpack dir so
    # it survives restarts. Try candidates in order and use the first writable
    # one, so the tool never crashes on a locked-down user data folder.
    global _CONFIG_DIR
    if _CONFIG_DIR:
        return os.path.join(_CONFIG_DIR, "config.json")
    candidates = []
    for base in (os.environ.get("LOCALAPPDATA"),
                 os.environ.get("APPDATA"),
                 os.path.dirname(sys.executable)):
        if base:
            candidates.append(os.path.join(base, "War3Assist"))
    for data_dir in candidates:
        try:
            os.makedirs(data_dir, exist_ok=True)
            _CONFIG_DIR = data_dir
            return os.path.join(data_dir, "config.json")
        except OSError:
            continue
    # Last resort: exe folder (may be read-only under Program Files, best effort).
    _CONFIG_DIR = os.path.dirname(sys.executable)
    return os.path.join(_CONFIG_DIR, "config.json")


def _log_config_error(path: str) -> None:
    print(f"[config] Unreadable or malformed config, using defaults: {path}",
          file=sys.stderr)


def load_config() -> AppConfig:
    cfg = AppConfig(slots=AppConfig.default_slots())
    path = _config_path()
    if not os.path.exists(path):
        return cfg
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        _log_config_error(path)
        return cfg
    if not isinstance(data, dict):
        _log_config_error(path)
        return cfg
    # Each toggle key: fall back to default on invalid type
    for key in ("toggle_code", "show_all_toggle_code",
                "show_ally_toggle_code", "show_enemy_toggle_code"):
        v = data.get(key, getattr(cfg, key))
        setattr(cfg, key, v if isinstance(v, int) else getattr(cfg, key))
    # Each default switch: fall back to default on invalid type
    for key in ("show_all_default",):
        v = data.get(key, getattr(cfg, key))
        setattr(cfg, key, v if isinstance(v, bool) else getattr(cfg, key))
    v = data.get("game_path", cfg.game_path)
    cfg.game_path = v if isinstance(v, str) else cfg.game_path
    slots = data.get("slots")
    if isinstance(slots, list):
        base = cfg.slots
        loaded: list[SlotConfig] = []
        for i, item in enumerate(slots):
            if not isinstance(item, dict):
                continue
            defaults = asdict(base[i]) if i < len(base) else {
                "slot_index": i, "label": f"Slot {i + 1}",
                "default_code": 0, "custom_code": 0, "enabled": True}
            merged = {**defaults, **item}
            loaded.append(SlotConfig(**merged))
        if loaded:
            cfg.slots = loaded
    return cfg


def save_config(cfg: AppConfig) -> bool:
    """Persist cfg to disk. Returns True on success, False on write failure."""
    data = {
        "toggle_code": cfg.toggle_code,
        "show_all_toggle_code": cfg.show_all_toggle_code,
        "show_ally_toggle_code": cfg.show_ally_toggle_code,
        "show_enemy_toggle_code": cfg.show_enemy_toggle_code,
        "show_all_default": cfg.show_all_default,
        "game_path": cfg.game_path,
        "slots": [asdict(s) for s in cfg.slots],
    }
    try:
        with open(_config_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        return True
    except OSError as exc:
        print(f"[config] Failed to persist config: {exc}", file=sys.stderr)
        return False