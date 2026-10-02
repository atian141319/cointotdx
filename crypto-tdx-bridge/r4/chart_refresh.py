"""Opt-in public same-period toolbar reload for the observed isolated minute chart."""
import ctypes as C
from ctypes import wintypes as W
import struct

POSITIONS = {'1m':76,'5m':116,'15m':162,'30m':207,'1h':251,'1d':291}


def observed_period(bitmap):
    if len(bitmap)<54 or bitmap[:2]!=b'BM':
        raise ValueError('Unknown chart capture')
    offset=struct.unpack_from('<I',bitmap,10)[0]
    width,height=struct.unpack_from('<ii',bitmap,18)
    bits=struct.unpack_from('<H',bitmap,28)[0]
    compression=struct.unpack_from('<I',bitmap,30)[0]
    if (width,height,bits,compression)!=(1024,526,32,0) or offset<54 or len(bitmap)!=offset+width*height*4:
        raise ValueError('Only observed 1024x526 toolbar layout is enabled')
    selected=[]
    for name,cx in POSITIONS.items():
        count=0
        for y in range(28,47):
            for x in range(cx-18,cx+18):
                index=offset+((height-1-y)*width+x)*4
                blue,green,red=bitmap[index:index+3]
                if blue>150 and green>150 and red<80:
                    count+=1
        if count>=15:
            selected.append(name)
    if len(selected)!=1 or selected[0]=='1d':
        raise ValueError('Active minute period is absent/ambiguous/unsupported; no click')
    return selected[0]


def reload_active(client, pairs, history_guard=None):
    windows=[w for w in client.windows() if 'V7.73' in w[1]]
    if len(windows)!=1:
        return {'requested':False,'reason':'No unique selected-client window'}
    main,title,pid=windows[0]
    matching=[p for p in pairs if p['enabled'] and title.endswith('[分析图表-'+p['display_name']+']')]
    if len(matching)!=1:
        return {'requested':False,'reason':'Active chart is not a configured owned instrument'}
    if history_guard is None:
        return {'requested':False,'reason':'History protection unavailable; no click'}
    history_guard.watch(client, main, pid)
    class GuiInfo(C.Structure):
        _fields_=[('cbSize',W.DWORD),('flags',W.DWORD),('hwndActive',W.HWND),('hwndFocus',W.HWND),
                  ('hwndCapture',W.HWND),('hwndMenuOwner',W.HWND),('hwndMoveSize',W.HWND),
                  ('hwndCaret',W.HWND),('rcCaret',W.RECT)]
    info=GuiInfo();info.cbSize=C.sizeof(info)
    thread=client.user.GetWindowThreadProcessId(W.HWND(main),None)
    if not client.user.GetGUIThreadInfo(thread,C.byref(info)) or info.flags & (4|8|16):
        return {'requested':False,'reason':'Menu or GUI state unknown; no click'}
    class LastInput(C.Structure):
        _fields_=[('cbSize',W.UINT),('dwTime',W.DWORD)]
    last=LastInput();last.cbSize=C.sizeof(last)
    kind=C.create_unicode_buffer(256)
    if info.hwndFocus:
        client.user.GetClassNameW(info.hwndFocus,kind,256)
        if 'Edit' in kind.value or 'ComboBox' in kind.value:
            return {'requested':False,'reason':'User editing input; no click'}
    first=client.capture(None)
    if first['title']!=title:
        return {'requested':False,'reason':'User changed chart; no click'}
    period=observed_period(first['bitmap'])
    from history_guard import fixed_cursor_visible
    reason = history_guard.observe(fixed_cursor_visible(first['bitmap']))
    if reason:
        return {'requested':False,'reason':reason,'history_paused':True,
                'collection_continues':True,'publication_continues':True}
    client.user.GetForegroundWindow.restype = W.HWND
    foreground_pid = W.DWORD()
    client.user.GetWindowThreadProcessId(client.user.GetForegroundWindow(), C.byref(foreground_pid))
    if foreground_pid.value == pid and (not client.user.GetLastInputInfo(C.byref(last)) or
            ((client.kernel.GetTickCount()-last.dwTime)&0xffffffff)<1500):
        return {'requested':False,'reason':'User input active; defer reload'}
    second=client.capture(None)
    if first['title']!=second['title'] or observed_period(second['bitmap'])!=period:
        return {'requested':False,'reason':'User changed chart/period; no click'}
    reason = history_guard.observe(fixed_cursor_visible(second['bitmap']))
    if reason:
        return {'requested':False,'reason':reason,'history_paused':True}
    operation=client.period(period)
    return {'requested':True,'symbol':matching[0]['symbol'],'code':matching[0]['code'],
            'period':period,'client_pid':pid,'mechanism':'public same-period toolbar click',
            'operation':operation,'chart_update_verified':False}
