"""Hotkey engine: low-level polling + key injection + dedicated low-level keyboard hook (ctypes/user32).

Architecture:
- WH_KEYBOARD_LL runs on a dedicated thread with a blocking GetMessageW pump
  (the same reliable scheme as pynput / keyboard), avoiding global-key hangs
  that a "poll + sleep" loop causes.
- The hook callback only does O(1) checks and, while "swallowing" the custom key,
  pushes the target key onto a thread-safe queue.
- The engine main loop polls the toggles/HP, and injects target keys asynchronously.
"""
from __future__ import annotations

import time
from queue import Empty, Queue
from threading import Lock, Thread

from PySide6.QtCore import QThread, Signal

import config
from config import AppConfig

from ctypes import (
    POINTER, Structure, WINFUNCTYPE, byref, c_int, c_size_t, c_void_p,
    c_wchar_p, cast, create_unicode_buffer, windll, wintypes,
)

GET_ASYNC_KEY_STATE = 0x8000
POLL_INTERVAL = 0.02  # main-loop poll interval (sec), ~50 Hz

# ── Low-level keyboard hook (swallow custom keys) ──
HC_ACTION = 0
WH_KEYBOARD_LL = 13
LLKHF_INJECTED = 0x10      # injected keys carry this flag; allow them to avoid loops

# ── Messages ──
WM_QUIT = 0x0012
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104

# War3 built-in HP-bar keys (targeted send, no Alt simulation): '[' = ally,
# ']' = enemy; show ALL HP = press both simultaneously.
VK_ALLY_BAR = 0xDB     # '['
VK_ENEMY_BAR = 0xDD    # ']'
_SHOW_ALLY_KEY = VK_ALLY_BAR
_SHOW_ENEMY_KEY = VK_ENEMY_BAR

_FindWindowW = windll.user32.FindWindowW
_FindWindowW.argtypes = [c_wchar_p, c_wchar_p]
_FindWindowW.restype = c_void_p
_IsWindow = windll.user32.IsWindow
_IsWindow.restype = c_int
_GetForegroundWindow = windll.user32.GetForegroundWindow
_GetForegroundWindow.restype = c_void_p
_PostMessageW = windll.user32.PostMessageW

# Calls needed for the fallback window lookup (title match)
_EnumWindows = windll.user32.EnumWindows
_EnumWindows.argtypes = [c_void_p, wintypes.LPARAM]
_EnumWindows.restype = c_int
_IsWindowVisible = windll.user32.IsWindowVisible
_IsWindowVisible.argtypes = [wintypes.HWND]
_IsWindowVisible.restype = c_int
_GetWindowTextLengthW = windll.user32.GetWindowTextLengthW
_GetWindowTextLengthW.argtypes = [wintypes.HWND]
_GetWindowTextLengthW.restype = c_int
_GetWindowTextW = windll.user32.GetWindowTextW
_GetWindowTextW.argtypes = [wintypes.HWND, c_wchar_p, c_int]
_GetWindowTextW.restype = c_int

# ── Win32 calls needed by the low-level hook thread ──
_SetWindowsHookExW = windll.user32.SetWindowsHookExW
_SetWindowsHookExW.argtypes = [c_int, c_void_p, c_void_p, wintypes.DWORD]
_SetWindowsHookExW.restype = c_void_p
_UnhookWindowsHookEx = windll.user32.UnhookWindowsHookEx
_UnhookWindowsHookEx.argtypes = [c_void_p]
_UnhookWindowsHookEx.restype = c_int
_CallNextHookEx = windll.user32.CallNextHookEx
_CallNextHookEx.argtypes = [c_void_p, c_int, wintypes.WPARAM, wintypes.LPARAM]
_CallNextHookEx.restype = c_int
_GetMessageW = windll.user32.GetMessageW
_TranslateMessage = windll.user32.TranslateMessage
_DispatchMessageW = windll.user32.DispatchMessageW
_PostThreadMessageW = windll.user32.PostThreadMessageW
_GetCurrentThreadId = windll.kernel32.GetCurrentThreadId


class _KBDLLHOOKSTRUCT(Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", c_size_t),
    ]


# Low-level keyboard hook callback prototype
_LLKBDProc = WINFUNCTYPE(c_int, c_int, wintypes.WPARAM, wintypes.LPARAM)


def _pressed(code: int) -> bool:
    return bool(windll.user32.GetAsyncKeyState(code) & GET_ASYNC_KEY_STATE)


def war3_hwnd() -> int:
    """Return the Warcraft III top-level window handle; 0 if not running.

    First looks up class name "Warcraft III" exactly (classic/RoC/TFT/Re:forged);
    if not found, enumerates visible top-level windows and matches a title
    containing "Warcraft", for compatibility with modified versions.
    """
    h = _FindWindowW("Warcraft III", None)
    if h:
        return int(h)

    holder: list[int] = []

    @WINFUNCTYPE(c_int, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd: int, lparam: int) -> int:
        if _IsWindowVisible(hwnd):
            n = _GetWindowTextLengthW(hwnd) + 1
            if n > 1:
                buf = create_unicode_buffer(n)
                _GetWindowTextW(hwnd, buf, n)
                if buf.value and "Warcraft" in buf.value:
                    holder.append(int(hwnd))
                    return 0  # stop enumerating once found
        return 1

    if _EnumWindows(_cb, 0):
        return holder[0] if holder else 0
    return 0


class ShowHp:
    """HP-bar control: holds the bar key (WM_KEYDOWN) while the game is foreground,
    and releases it when focus is lost / engine stops."""

    def __init__(self):
        self._held: list[int] = []

    def _post(self, hwnd: int, vk: int, down: bool) -> bool:
        """Send a key message; True on success, False when the window is invalid."""
        return bool(_PostMessageW(hwnd, WM_KEYDOWN if down else WM_KEYUP, vk, 0))

    def set(self, hwnd: int, vks: list[int]) -> None:
        for vk in vks:
            if vk not in self._held:
                if self._post(hwnd, vk, True):
                    self._held.append(vk)  # only remember on success, to avoid stuck keys
        for vk in list(self._held):
            if vk not in vks:
                self._held.remove(vk)
                self._post(hwnd, vk, False)

    def keep(self, hwnd: int) -> None:
        """Heartbeat: repeatedly re-send press while foreground to avoid game state loss."""
        for vk in list(self._held):
            if not self._post(hwnd, vk, True):
                # send failed (e.g. window destroyed): remove and send release to avoid stuck key
                self._held.remove(vk)
                self._post(hwnd, vk, False)

    def release_all(self, hwnd: int) -> None:
        for vk in self._held:
            self._post(hwnd, vk, False)
        self._held.clear()


class AssistantEngine(QThread):
    """Background thread: polls custom hotkeys, detects toggles, triggers inventory key injection."""

    active_changed = Signal(bool)
    hp_status = Signal(str)
    log = Signal(str)

    def __init__(self, cfg: AppConfig, parent=None):
        super().__init__(parent)
        self._lock = Lock()
        self._cfg = cfg
        self._reset_pending = False
        self._running = False
        self._active_cached = bool(cfg.active_default)
        # ── low-level hook thread state ──
        self._hook = None          # hook handle from SetWindowsHookEx
        self._proc = None          # keep callback reference to prevent GC crashes
        self._hook_thread: Thread | None = None
        self._hook_tid: int = 0
        # hook callback -> main loop pending-send queue (thread-safe)
        self._hook_queue: Queue = Queue()
        # live snapshot for the callback, refreshed by the main loop; callback only does O(1) checks
        self._cache_active = bool(cfg.active_default)
        self._cache_focused = False
        self._cache_codes: frozenset[int] = frozenset()   # enabled custom-key set
        self._cache_map: dict[int, tuple] = {}            # custom key -> (default, idx, label)

    @property
    def cfg(self) -> AppConfig:
        """Thread-safe read of the current config."""
        with self._lock:
            return self._cfg

    def update_cfg(self, cfg: AppConfig) -> None:
        """Hot-update config at runtime; flags edge-state reset to keep old/new slots consistent."""
        with self._lock:
            self._cfg = cfg
            self._reset_pending = True

    def run(self) -> None:
        self._running = True
        active = self.cfg.active_default
        self._active_cached = active
        show_all = self.cfg.show_all_default
        show_ally = self.cfg.show_ally_default
        show_enemy = self.cfg.show_enemy_default
        self.active_changed.emit(active)
        self.show_hp = ShowHp()
        hh = self.show_hp
        self._emit_hp(show_all, show_ally, show_enemy)
        # start the dedicated low-level hook thread (swallow custom keys, no duplicate game effects)
        self._hook_thread = Thread(target=self._hook_loop, daemon=True)
        self._hook_thread.start()
        last_toggle = False
        last_all = last_ally = last_enemy = False
        cur = (show_all, show_ally, show_enemy)
        self.log.emit("Hotkey engine started.")
        while self._running:
            # parse config snapshot
            with self._lock:
                cfg = self._cfg
                if self._reset_pending:
                    self._reset_pending = False
                    last_toggle = last_all = last_ally = last_enemy = False
                    self._active_cached = active = self.cfg.active_default

            # refresh live snapshot for the hook callback (O(1) checks)
            hwnd = war3_hwnd()
            focused = bool(hwnd) and int(_GetForegroundWindow() or 0) == hwnd
            self._cache_active = active
            self._cache_focused = focused
            codes, mapping = set(), {}
            for s in cfg.slots:
                if s.enabled and s.custom_code > 0:
                    codes.add(s.custom_code)
                    mapping[s.custom_code] = (
                        s.default_code, s.slot_index, s.label, s.custom_code)
            self._cache_codes = frozenset(codes)
            self._cache_map = mapping

            # drain the hook queue: send the target key to the game window on the
            # main loop (outside the hook thread). HP uses the same PostMessage send,
            # ensuring the key enters the game's own message queue
            # (SendInput scan-code injection is ignored by some War3 versions).
            while True:
                try:
                    default_code, slot_index, label, custom_code = \
                        self._hook_queue.get_nowait()
                except Empty:
                    break
                if hwnd:
                    _PostMessageW(hwnd, WM_KEYDOWN, default_code, 0)
                    _PostMessageW(hwnd, WM_KEYUP, default_code, 0)
                    self.log.emit(
                        f"{label}: {config.code_name(custom_code)} → "
                        f"{config.code_name(default_code)}")

            # ── toggle key (default Delete) toggles inventory hotkeys ──
            t = _pressed(cfg.toggle_code)
            if t and not last_toggle:
                active = not active
                self._active_cached = active
                self.active_changed.emit(active)
                self.log.emit("Inventory hotkeys: " + ("enabled" if active else "disabled"))
            last_toggle = t

            # ── the three HP toggles (default ScrollLock / PageDown / PageUp) ──
            a = _pressed(cfg.show_all_toggle_code)
            if a and not last_all:
                show_all = not show_all
                self.log.emit("Show HP (all): " + ("on" if show_all else "off"))
            last_all = a
            y = _pressed(cfg.show_ally_toggle_code)
            if y and not last_ally:
                show_ally = not show_ally
                self.log.emit("Show HP (ally): " + ("on" if show_ally else "off"))
            last_ally = y
            e = _pressed(cfg.show_enemy_toggle_code)
            if e and not last_enemy:
                show_enemy = not show_enemy
                self.log.emit("Show HP (enemy): " + ("on" if show_enemy else "off"))
            last_enemy = e

            # ── HP injection: hold the bar keys while game is foreground, release on loosing focus ──
            if focused:
                vks = []
                if show_all:
                    vks.append(_SHOW_ALLY_KEY)
                    vks.append(_SHOW_ENEMY_KEY)
                if show_ally:
                    vks.append(_SHOW_ALLY_KEY)
                if show_enemy:
                    vks.append(_SHOW_ENEMY_KEY)
                hh.set(hwnd, vks)
                hh.keep(hwnd)  # keep-alive heartbeat (every iteration)
            else:
                hh.release_all(hwnd)
            if (show_all, show_ally, show_enemy) != cur:
                cur = (show_all, show_ally, show_enemy)
                self._emit_hp(show_all, show_ally, show_enemy)

            time.sleep(POLL_INTERVAL)
        # engine exit: post WM_QUIT to the hook thread to unhook and exit
        if self._hook_tid:
            _PostThreadMessageW(self._hook_tid, WM_QUIT, 0, 0)
        if self._hook_thread:
            self._hook_thread.join(timeout=1.0)

    # ──────── dedicated low-level hook thread: blocking message pump, swallow custom keys ────────
    def _hook_loop(self) -> None:
        """Low-level hook thread: installs the hook, then runs a GetMessageW pump.

        This thread does nothing but serve hook messages, using a blocking
        GetMessageW so keys are handled immediately and the global keyboard is
        never suspended by a "poll + sleep" pattern.
        """
        self._hook_tid = int(_GetCurrentThreadId())
        self._proc = _LLKBDProc(self._kb_proc)
        self._hook = _SetWindowsHookExW(
            WH_KEYBOARD_LL, self._proc, c_void_p(0), 0)
        if not self._hook:
            self.log.emit("Failed to enable key interception.")
            return
        self.log.emit("Keyboard hook enabled.")
        msg = wintypes.MSG()
        while True:
            r = _GetMessageW(byref(msg), 0, 0, 0)
            if r == 0:      # WM_QUIT
                break
            if r == -1:     # error
                break
            _TranslateMessage(byref(msg))
            _DispatchMessageW(byref(msg))
        if self._hook:
            _UnhookWindowsHookEx(self._hook)
            self._hook = None
        self._proc = None

    def _kb_proc(self, n_code: int, w_param: int, l_param: int) -> int:
        """Low-level hook callback: swallow an enabled custom key and queue the target action.

        Note: the callback is a synchronous system call; never inject keys or do
        expensive work here. Only do O(1) checks and enqueue; the actual send is
        done asynchronously by the main loop.
        """
        if n_code == HC_ACTION:
            kb = cast(c_void_p(l_param), POINTER(_KBDLLHOOKSTRUCT)).contents
            # allow keys injected by this tool, so the target key itself is not swallowed (no loops)
            if not (kb.flags & LLKHF_INJECTED):
                vk = int(kb.vkCode)
                # O(1) set lookups against the snapshot refreshed by the main loop
                if (self._cache_active and self._cache_focused
                        and vk in self._cache_codes):
                    item = self._cache_map[vk]
                    if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        self._hook_queue.put(item)
                    # swallow both press and release; the custom key no longer reaches the game
                    return 1
        return _CallNextHookEx(None, n_code, w_param, l_param)

    def _emit_hp(self, show_all: bool, show_ally: bool, show_enemy: bool) -> None:
        parts = []
        if show_all:
            parts.append("All")
        if show_ally:
            parts.append("Ally")
        if show_enemy:
            parts.append("Enemy")
        self.hp_status.emit(", ".join(parts))

    def stop(self) -> None:
        self._running = False
        if self._hook_tid:
            _PostThreadMessageW(self._hook_tid, WM_QUIT, 0, 0)
        if self._hook_thread:
            self._hook_thread.join(timeout=1.0)
        self.wait(1000)
        hwnd = war3_hwnd()
        if hwnd and hasattr(self, "show_hp"):
            self.show_hp.release_all(hwnd)  # release all held HP-bar keys on stop