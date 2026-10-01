"""Public Windows process/window operations; never patches TongdaXin or kills it."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import struct
import subprocess
import time


class Client:
    def __init__(self, config):
        self.config = config
        self.executable = Path(config['tdx']['executable']).resolve()
        self.user = C.WinDLL('user32', use_last_error=True)
        self.kernel = C.WinDLL('kernel32', use_last_error=True)
        self.user.SendMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        self.user.SendMessageW.restype = C.c_ssize_t
        self.user.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        self.user.GetParent.argtypes = [W.HWND]
        self.user.GetParent.restype = W.HWND
        self.kernel.OpenProcess.restype = W.HANDLE
        self.kernel.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
        self.kernel.CloseHandle.argtypes = [W.HANDLE]

    def windows(self):
        found = []
        callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        @callback_type
        def callback(handle, argument):
            if not self.user.IsWindowVisible(handle):
                return True
            pid = W.DWORD()
            self.user.GetWindowThreadProcessId(handle, C.byref(pid))
            process = self.kernel.OpenProcess(0x1000, False, pid.value)
            if process:
                try:
                    buffer = C.create_unicode_buffer(32768)
                    length = W.DWORD(len(buffer))
                    if self.kernel.QueryFullProcessImageNameW(process, 0, buffer, C.byref(length)):
                        if Path(buffer.value).resolve() == self.executable:
                            text = C.create_unicode_buffer(512)
                            self.user.GetWindowTextW(handle, text, 512)
                            if text.value:
                                found.append((int(handle), text.value, pid.value))
                finally:
                    self.kernel.CloseHandle(process)
            return True
        self.user.EnumWindows(callback, 0)
        return found

    def start(self):
        if self.windows():
            return 'Selected client already running'
        subprocess.Popen([str(self.executable)], cwd=str(self.executable.parent))
        return 'Started selected client; guest login may require a click'

    def redraw(self):
        windows = self.windows()
        for handle, _, _ in windows:
            self.user.RedrawWindow(W.HWND(handle), None, None, 0x181)
        return {'operation': 'public RedrawWindow', 'windows': windows,
                'cache_reload_verified': False}

    def children(self, root):
        items=[]
        callback_type=C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        @callback_type
        def callback(handle, argument):
            name=C.create_unicode_buffer(512)
            kind=C.create_unicode_buffer(256)
            self.user.GetWindowTextW(handle,name,512)
            self.user.GetClassNameW(handle,kind,256)
            items.append({'handle':int(handle),'name':name.value,'class':kind.value,
                          'id':self.user.GetDlgCtrlID(handle)})
            return True
        self.user.EnumChildWindows(W.HWND(root),callback,0)
        return items

    def guest_login(self):
        for root, _, _ in self.windows():
            for item in self.children(root):
                if item['class']=='Button' and item['name']=='游客登录':
                    self.user.SendMessageW(W.HWND(item['handle']),0xF5,0,0)
                    return {'requested':'guest login','control':item,'completed':False}
        return {'requested':'guest login','error':'No identified public guest button'}

    def period(self, period):
        # Click the visible chart's observed toolbar in its own client coordinates.
        # Root ClientToScreen/ScreenToClient conversions can select the wrong period at 125% DPI.
        positions={'1m':76,'5m':116,'15m':162,'30m':207,'1h':251,'1d':291}
        windows=[w for w in self.windows() if '分析图表' in w[1]]
        if not windows or period not in positions:
            raise RuntimeError('No observed analysis chart or unsupported toolbar period')
        root=windows[0][0]
        chart=next((item['handle'] for item in self.children(root) if item['name'].startswith('分析图表')),None)
        if not chart:
            raise RuntimeError('Visible MDI analysis chart missing')
        class Rect(C.Structure):
            _fields_=[('left',W.LONG),('top',W.LONG),('right',W.LONG),('bottom',W.LONG)]
        root_rect=Rect();self.user.GetWindowRect(W.HWND(root),C.byref(root_rect))
        candidates=[]
        for item in self.children(chart):
            if item['id']==213 and item['class']=='CFQS_SwitchEx' and self.user.IsWindowVisible(W.HWND(item['handle'])):
                rect=Rect();self.user.GetWindowRect(W.HWND(item['handle']),C.byref(rect))
                if rect.right>rect.left and rect.bottom>rect.top:
                    candidates.append((item['handle'],rect))
        if len(candidates)!=1:
            raise RuntimeError('Observed chart toolbar is not unique')
        handle,rect=candidates[0]
        x=positions[period]-(rect.left-root_rect.left)
        y=(rect.bottom-rect.top)//2
        if not 0<=x<rect.right-rect.left:
            raise RuntimeError('Observed toolbar layout changed')
        packed=(y<<16)|(x&65535)
        self.user.PostMessageW(W.HWND(handle),0x201,1,packed)
        self.user.PostMessageW(W.HWND(handle),0x202,0,packed)
        return {'operation':'standard chart-toolbar click','period_requested':period,
                'handle':handle,'client_point':[x,y],'cache_reload_verified':False}

    def capture(self, path):
        windows = self.windows()
        if not windows:
            raise RuntimeError('Selected client is not running')
        handle, title, pid = next((item for item in windows if '金融终端' in item[1]), windows[0])
        class Rect(C.Structure):
            _fields_ = [('left', W.LONG), ('top', W.LONG), ('right', W.LONG), ('bottom', W.LONG)]
        rect = Rect()
        self.user.GetWindowRect(W.HWND(handle), C.byref(rect))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if not 1 <= width <= 10000 or not 1 <= height <= 10000:
            raise RuntimeError('Invalid capture dimensions')
        gdi = C.WinDLL('gdi32')
        self.user.GetDC.restype = W.HDC
        gdi.CreateCompatibleDC.argtypes = [W.HDC]
        gdi.CreateCompatibleDC.restype = W.HDC
        gdi.CreateCompatibleBitmap.argtypes = [W.HDC, C.c_int, C.c_int]
        gdi.CreateCompatibleBitmap.restype = W.HBITMAP
        gdi.SelectObject.argtypes = [W.HDC, W.HGDIOBJ]
        gdi.SelectObject.restype = W.HGDIOBJ
        gdi.GetDIBits.argtypes = [W.HDC, W.HBITMAP, W.UINT, W.UINT, W.LPVOID, W.LPVOID, W.UINT]
        gdi.DeleteObject.argtypes = [W.HGDIOBJ]
        gdi.DeleteDC.argtypes = [W.HDC]
        self.user.ReleaseDC.argtypes = [W.HWND, W.HDC]
        self.user.PrintWindow.argtypes = [W.HWND, W.HDC, W.UINT]
        dc = self.user.GetDC(W.HWND(handle))
        memory = gdi.CreateCompatibleDC(dc)
        bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
        old = gdi.SelectObject(memory, bitmap)
        try:
            if not self.user.PrintWindow(W.HWND(handle), memory, 2):
                raise RuntimeError('PrintWindow failed; no desktop screenshot fallback')
            gdi.SelectObject(memory, old)
            data = C.create_string_buffer(width * height * 4)
            header = struct.pack('<IiiHHIIIIII', 40, width, height, 1, 32, 0, len(data), 0, 0, 0, 0)
            info = C.create_string_buffer(header)
            if not gdi.GetDIBits(memory, bitmap, 0, height, data, info, 0):
                raise RuntimeError('Capture readback failed')
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(struct.pack('<2sIHHI', b'BM', 54 + len(data), 0, 0, 54) + header + data.raw)
            evidence = {'actual_executable': str(self.executable), 'pid': pid, 'title': title,
                        'observed_ms': int(time.time() * 1000), 'capture': path.name}
            path.with_suffix('.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
            return evidence
        finally:
            gdi.SelectObject(memory, old)
            gdi.DeleteObject(bitmap)
            gdi.DeleteDC(memory)
            self.user.ReleaseDC(W.HWND(handle), dc)
