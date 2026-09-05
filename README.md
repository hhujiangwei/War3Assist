# Warcraft III Assistant

A lightweight Windows helper for Warcraft III, rebuilt with Python 3.12 + PySide6.
It remaps the six inventory slots to your own custom shortcuts and shows HP bars
using the game's built-in bar keys.

## Features

- **Inventory hotkeys** — Bind any key to any of the 6 inventory slots. While the
  toggle is on, pressing your *Custom* key plays that slot's *Target* key for you
  (default target layout matches War3's phone-dialpad map: Num7/8 · Num4/5 · Num1/2).
- **Full custom rebinding** — Click any keycap in the **Hotkey Overview** or the
  inventory table, then press the key you want to bind.
- **Enable on Startup** — Choose which functions turn on automatically when the
  engine starts.
- **HP bars** — Hold the built-in bar key (`[` = ally, `]` = enemy) to show HP for
  your own or enemy units, or both for "show all". Each faction has its own toggle.
- **Apply & Save** — Persist all settings to `config.json`; reuse them next launch.
- **Restore Defaults** — Instantly reset the six inventory slots to the game
  defaults (Z X C V B N → Num7 8 4 5 1 2).

## Usage

1. Run the program (`War3Assist.exe` for the packaged build, or `python main.py`).
2. Click **▶ Start Engine** to begin listening for hotkeys.
3. In the game, press your custom keys to use the inventory slots; press
   `Delete` to toggle inventory hotkeys on/off at runtime.

### Default keys

| Function            | Default key          | In-game effect                              |
| ------------------- | -------------------- | ------------------------------------------- |
| Inventory hotkeys on/off | `Delete`        | toggles remapping on/off                    |
| Show all HP         | `Scroll Lock`        | holds `[` + `]`                             |
| Show ally HP        | `PageDown`           | holds `[`                                   |
| Show enemy HP       | `PageUp`             | holds `]`                                   |
| Slot 1–6 (custom)   | `Z` `X` `C` `V` `B` `N` | triggers Target Num7 8 4 5 1 2         |

All keys are rebindable; changes are saved to `config.json`.

## Requirements (source build)

- Windows 10/11
- Python 3.12+ with `PySide6`

## Building the single-file EXE

Icon: `assets/app_icon.ico` (EXE shell icon) and `assets/app_icon.jpeg` (window
icon) are bundled automatically.

```
pip install pyinstaller pillow
pyinstaller --clean --noconfirm War3Assist.spec
```

Output: `dist/War3Assist.exe`.

> Note: In the single-file build, `config.json` lives in PyInstaller's temporary
> extraction folder, so saved settings are not retained across runs unless the
> config path is moved next to the EXE.

## Files

- `main.py` — entry point
- `ui.py` — main window and controls
- `engine.py` — hotkey polling, key injection, low-level keyboard hook
- `config.py` — configuration models and keymap
- `config.json` — user settings
- `War3Assist.spec` — PyInstaller build script
- `assets/` — application icons