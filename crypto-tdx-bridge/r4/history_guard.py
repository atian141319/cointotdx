"""Latch history navigation until an explicit return to the latest chart.

Public input notifications only; no key contents are stored or sent elsewhere.
The chart has no public scrollbar, so an unobserved viewport fails closed.
"""
import ctypes as C
from ctypes import wintypes as W
import struct
import threading
import hashlib


def fixed_cursor_visible(bitmap):
    # Observed 1024x526 layout: a dark-blue selected-date badge on the time axis.
    if len(bitmap) < 54 or bitmap[:2] != b'BM':
        raise ValueError('Unknown cursor capture')
    offset = struct.unpack_from('<I', bitmap, 10)[0]
    width, height = struct.unpack_from('<ii', bitmap, 18)
    if (width, height) != (1024, 526) or len(bitmap) != offset + width * height * 4:
        raise ValueError('Unknown history-view layout')
    for y in range(451, 467):
        run = 0
        for x in range(5, 740):
            point = offset + ((height - 1 - y) * width + x) * 4
            blue, green, red = bitmap[point:point + 3]
            run = run + 1 if blue >= 100 and green < 30 and red < 30 else 0
            if run >= 24:
                return True
    return False


def date_badge_hash(bitmap):
    if not fixed_cursor_visible(bitmap):
        return None
    offset = struct.unpack_from('<I', bitmap, 10)[0]
    coordinates = []
    for y in range(451, 467):
        for x in range(5, 740):
            point = offset + ((525 - y) * 1024 + x) * 4
            blue, green, red = bitmap[point:point + 3]
            if blue >= 100 and green < 30 and red < 30:
                coordinates.append(x)
    left, right = min(coordinates), max(coordinates) + 1
    pixels = b''.join(bitmap[offset + ((525 - y) * 1024 + left) * 4:
                             offset + ((525 - y) * 1024 + right) * 4]
                      for y in range(451, 467))
    return {'left': left, 'right': right, 'sha256': hashlib.sha256(pixels).hexdigest()}


class HistoryGuard:
    def __init__(self):
        self.lock = threading.Lock()
        self.paused = True
        self.resume_requested = False
        self.reason = 'Viewport not verified; return to latest to resume'
        self.context = None
        self.monitor = None

    def navigation(self, action):
        with self.lock:
            if action == 'latest':
                self.resume_requested = True
            elif action == 'history':
                self.paused = True
                self.resume_requested = False
                self.reason = 'History navigation; automatic reload paused'

    def observe(self, cursor):
        with self.lock:
            if cursor:
                self.paused = True
                self.reason = 'Fixed chart cursor; automatic reload paused'
            elif self.resume_requested:
                self.paused = False
                self.resume_requested = False
                self.reason = None
            return self.reason if self.paused else None

    def watch(self, client, main, pid):
        if self.monitor is None:
            self.monitor = NavigationMonitor(self)
            self.monitor.start()
            if not self.monitor.ready.wait(3) or self.monitor.error:
                raise RuntimeError(self.monitor.error or 'History input monitor did not start')
        self.monitor.target = (main, pid)

    def close(self):
        if self.monitor:
            self.monitor.close()

    def snapshot(self):
        with self.lock:
            return {'paused': self.paused, 'resume_requested': self.resume_requested,
                    'reason': self.reason, 'monitor_alive': bool(self.monitor and self.monitor.is_alive()),
                    'monitor_error': self.monitor.error if self.monitor else None,
                    'navigation_notifications': list(self.monitor.navigation_notifications) if self.monitor else []}


class NavigationMonitor(threading.Thread):
    def __init__(self, guard):
        super().__init__(daemon=True)
        self.guard = guard
        self.target = None
        self.ready = threading.Event()
        self.error = None
        self.thread_id = None
        self.navigation_notifications = []

    def run(self):
        user = C.WinDLL('user32', use_last_error=True)
        kernel = C.WinDLL('kernel32', use_last_error=True)
        user.GetForegroundWindow.restype = W.HWND
        callback_type = C.WINFUNCTYPE(C.c_ssize_t, C.c_int, W.WPARAM, W.LPARAM)
        user.SetWindowsHookExW.argtypes = [C.c_int, callback_type, W.HINSTANCE, W.DWORD]
        user.SetWindowsHookExW.restype = W.HANDLE
        user.CallNextHookEx.argtypes = [W.HANDLE, C.c_int, W.WPARAM, W.LPARAM]
        user.CallNextHookEx.restype = C.c_ssize_t
        user.UnhookWindowsHookEx.argtypes = [W.HANDLE]
        kernel.GetModuleHandleW.restype = W.HMODULE
        self.thread_id = kernel.GetCurrentThreadId()

        class Keyboard(C.Structure):
            _fields_ = [('vk', W.DWORD), ('scan', W.DWORD), ('flags', W.DWORD),
                        ('time', W.DWORD), ('extra', C.c_size_t)]

        class Mouse(C.Structure):
            _fields_ = [('point', W.POINT), ('data', W.DWORD), ('flags', W.DWORD),
                        ('time', W.DWORD), ('extra', C.c_size_t)]

        class GuiInfo(C.Structure):
            _fields_ = [('cbSize', W.DWORD), ('flags', W.DWORD), ('hwndActive', W.HWND),
                        ('hwndFocus', W.HWND), ('hwndCapture', W.HWND), ('hwndMenuOwner', W.HWND),
                        ('hwndMoveSize', W.HWND), ('hwndCaret', W.HWND), ('rcCaret', W.RECT)]

        def selected(keyboard_input=False):
            target = self.target
            if not target:
                return False
            actual = W.DWORD()
            user.GetWindowThreadProcessId(user.GetForegroundWindow(), C.byref(actual))
            if actual.value != target[1]:
                return False
            info = GuiInfo()
            info.cbSize = C.sizeof(info)
            thread = user.GetWindowThreadProcessId(user.GetForegroundWindow(), None)
            if not user.GetGUIThreadInfo(thread, C.byref(info)) or info.flags & (4 | 8 | 16):
                return False
            if keyboard_input:
                name = C.create_unicode_buffer(256)
                user.GetClassNameW(W.HWND(info.hwndFocus), name, 256)
                return name.value.endswith(':300b')
            return user.GetForegroundWindow() == target[0]

        @callback_type
        def keyboard(code, message, pointer):
            if code >= 0 and message in (0x100, 0x104):
                vk = C.cast(pointer, C.POINTER(Keyboard)).contents.vk
                allowed = selected(keyboard_input=True)
                if vk in (0x23, 0x21, 0x22, 0x24, 0x25, 0x27) and selected():
                    self.navigation_notifications.append({'action': 'latest' if vk == 0x23 else 'history', 'chart_focus_verified': allowed})
                    del self.navigation_notifications[:-16]
                if allowed and vk == 0x23:  # End: explicit latest viewport intent.
                    self.guard.navigation('latest')
                elif allowed and vk in (0x21, 0x22, 0x24, 0x25, 0x27):
                    self.guard.navigation('history')
            return user.CallNextHookEx(None, code, message, pointer)

        @callback_type
        def mouse(code, message, pointer):
            if code >= 0 and message in (0x201, 0x20A) and selected():
                event = C.cast(pointer, C.POINTER(Mouse)).contents
                rectangle = W.RECT()
                if user.GetWindowRect(W.HWND(self.target[0]), C.byref(rectangle)):
                    x, y = event.point.x - rectangle.left, event.point.y - rectangle.top
                    if 5 <= x < 740 and 50 <= y < 467:
                        self.guard.navigation('history')
                    elif message == 0x201 and 55 <= x < 275 and 27 <= y < 49:
                        self.guard.navigation('latest')
            return user.CallNextHookEx(None, code, message, pointer)

        hooks = []
        try:
            for kind, callback in ((13, keyboard), (14, mouse)):
                hook = user.SetWindowsHookExW(kind, callback, kernel.GetModuleHandleW(None), 0)
                if not hook:
                    raise C.WinError(C.get_last_error())
                hooks.append(hook)
            message = W.MSG()
            user.PeekMessageW(C.byref(message), None, 0, 0, 0)
            self.ready.set()
            while user.GetMessageW(C.byref(message), None, 0, 0) > 0:
                user.TranslateMessage(C.byref(message))
                user.DispatchMessageW(C.byref(message))
        except Exception as error:
            self.error = str(error)
            self.ready.set()
        finally:
            for hook in hooks:
                user.UnhookWindowsHookEx(hook)

    def close(self):
        if self.thread_id:
            C.WinDLL('user32').PostThreadMessageW(self.thread_id, 0x12, 0, 0)
            self.join(timeout=3)
