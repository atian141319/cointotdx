"""Local tkinter settings window; no server, browser, or trading credentials."""
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from client_control import Client
from display import Publisher
from engine import Engine
from settings import ENDPOINTS, app_home, default_settings, load, registration_check, save, validate
from streams import probe


class Desktop:
    def __init__(self, root, config_path=None):
        self.root = root
        self.path = Path(config_path or app_home() / 'settings.json')
        # A moved/missing client must not prevent opening the window that repairs its paths.
        # Only startup editing defers path checks; gather/save/start retain strict validation.
        self.config = load(self.path, check_paths=False) if self.path.exists() else default_settings()
        self.startup_path_error = None
        try:
            validate(self.config)
        except ValueError as error:
            self.startup_path_error = str(error)
        self.engine = None
        self.reload_requested = False
        self.messages = queue.Queue()
        self.vars = {}
        root.title('币安 → 通达信 · 本地同步（显示试验）')
        root.geometry('1040x780')
        root.minsize(900, 650)
        style = ttk.Style()
        style.theme_use('vista' if 'vista' in style.theme_names() else 'clam')
        notebook = ttk.Notebook(root)
        notebook.pack(fill='both', expand=True, padx=12, pady=8)
        terminal = ttk.Frame(notebook, padding=12)
        pairs = ttk.Frame(notebook, padding=12)
        connection = ttk.Frame(notebook, padding=12)
        status = ttk.Frame(notebook, padding=12)
        for frame, name in ((terminal, '通达信与数据'), (pairs, '币种'), (connection, '连接'), (status, '状态与日志')):
            notebook.add(frame, text=name)
        self.notebook = notebook
        self.field(terminal, 'installation', '通达信安装目录', self.config['tdx']['installation'], 0, self.browse_installation)
        self.field(terminal, 'executable', '启动程序', self.config['tdx']['executable'], 1, lambda: self.browse('executable', False))
        self.field(terminal, 'tdx_data', '实际行情目录（vipdoc）', self.config['tdx']['data_directory'], 2, lambda: self.browse('tdx_data', True))
        self.field(terminal, 'exact_data', '精确数据目录（独立）', self.config['data_directory'], 3, lambda: self.browse('exact_data', True))
        ttk.Button(terminal, text='检查配置', command=self.check).grid(row=4, column=0, pady=10)
        ttk.Button(terminal, text='启动通达信', command=self.start_client).grid(row=4, column=1, sticky='w')
        ttk.Button(terminal, text='恢复管理文件', command=self.restore).grid(row=4, column=2)
        ttk.Label(terminal, text='仅管理已注册的397xxx外部品种。首次写入先备份；联调请选择隔离副本。\n'
            '实时精确库与显示文件分开。停用、删除币种默认保留历史。', wraplength=780).grid(row=5, column=0, columnspan=3, sticky='w', pady=12)
        if self.startup_path_error:
            warning = ('路径配置需要修正：' + self.startup_path_error + '\n当前启动程序：' +
                       self.config['tdx']['executable'] + '\n请选择正确的隔离通达信目录，再检查并保存配置。同步尚未启动。')
            ttk.Label(terminal, text=warning, foreground='#b00020', wraplength=800).grid(
                row=6, column=0, columnspan=3, sticky='w', pady=8)
            self.inform(warning)
        self.tree = ttk.Treeview(pairs, columns=('symbol', 'name', 'code', 'market', 'enabled', 'start'), show='headings', height=13)
        for key, heading, width in (('symbol','交易对',130), ('name','显示名称',150), ('code','通达信代码',100),
                                    ('market','市场',60), ('enabled','启用',60), ('start','UTC历史起点',290)):
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=width)
        self.tree.pack(fill='both', expand=True)
        buttons = ttk.Frame(pairs)
        buttons.pack(fill='x', pady=8)
        for text, action in [('添加',lambda: self.edit_pair()), ('编辑',lambda: self.edit_pair(True)),
            ('启用/停用',self.toggle_pair), ('删除（保留历史）',self.delete_pair),
            ('校验交易对',self.validate_pair), ('准备外部注册',self.prepare_registration)]:
            ttk.Button(buttons, text=text, command=action).pack(side='left', padx=3)
        ttk.Label(pairs, text='BTC保留397901。未完成注册的币种可接收精确行情，但显示文件暂停；不影响其他币种。').pack(anchor='w')
        self.field(connection, 'endpoint', '官方WebSocket端点', self.config['endpoint'], 0, choices=ENDPOINTS)
        self.field(connection, 'proxy', '应用内WS代理（可空）', self.config['proxy'], 1)
        self.field(connection, 'connection_timeout', '连接超时（秒）', self.config['connection_timeout'], 2)
        self.field(connection, 'rest_endpoint', '官方REST端点', self.config['rest_endpoint'], 3,
            choices=('https://data-api.binance.vision','https://api.binance.com'))
        self.field(connection, 'rest_timeout', 'REST超时（秒）', self.config['rest_timeout'], 4)
        self.field(connection, 'rest_retries', 'REST有限重试次数', self.config['rest_retries'], 5)
        self.field(connection, 'publish_seconds', '文件合并写入间隔（秒）', self.config['publish_seconds'], 6)
        ttk.Button(connection, text='真实连接测试', command=self.test_connection).grid(row=7,column=1,sticky='w',pady=12)
        ttk.Label(connection,text='代理支持http://host:port / socks5://host:port，仅用于WebSocket；REST沿用直连。\n'
            '1m与1M不同；60分钟订阅1h。无交易API密钥。',wraplength=780).grid(row=8,column=0,columnspan=3,sticky='w')
        self.status_text = tk.Text(status, height=15, wrap='word', state='disabled')
        self.status_text.pack(fill='both', expand=True)
        bar = ttk.Frame(status)
        bar.pack(fill='x',pady=6)
        ttk.Button(bar,text='查看日志',command=self.open_log).pack(side='left')
        ttk.Button(bar,text='重绘图表（不等于重读缓存）',command=self.redraw).pack(side='left',padx=6)
        ttk.Button(bar,text='记录当前图表证据',command=self.capture).pack(side='left')
        footer = ttk.Frame(root,padding=10)
        footer.pack(fill='x')
        for text, action in [('保存配置',self.save),('导入配置',self.import_config),('导出配置',self.export_config),
            ('开始同步',self.start),('停止同步',self.stop),('补历史',self.backfill)]:
            ttk.Button(footer,text=text,command=action).pack(side='left',padx=4)
        ttk.Label(root,text='显示试验：float32价格/金额、整数截断基础币量；日线价格3位表示。误差逐条保存，不是准确行情认证。',
            foreground='#9c4200').pack(anchor='w',padx=12,pady=(0,8))
        self.refresh_pairs()
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.after(300,self.poll)

    def field(self, frame, key, label, value, row, browse=None, choices=None):
        ttk.Label(frame,text=label).grid(row=row,column=0,sticky='w',padx=(0,12),pady=7)
        self.vars[key]=tk.StringVar(value=str(value))
        widget=ttk.Combobox(frame,textvariable=self.vars[key],values=choices,width=64,state='readonly') if choices else ttk.Entry(frame,textvariable=self.vars[key],width=70)
        widget.grid(row=row,column=1,sticky='ew')
        if browse:
            ttk.Button(frame,text='选择',command=browse).grid(row=row,column=2,padx=6)
        frame.columnconfigure(1,weight=1)

    def gather(self):
        c=copy.deepcopy(self.config)
        c['tdx']={key:self.vars[var].get() for key,var in [('installation','installation'),('executable','executable'),('data_directory','tdx_data')]}
        c['data_directory']=self.vars['exact_data'].get()
        for key in ('endpoint','proxy','rest_endpoint'):
            c[key]=self.vars[key].get()
        for key in ('connection_timeout','rest_timeout','publish_seconds'):
            c[key]=float(self.vars[key].get())
        c['rest_retries']=int(self.vars['rest_retries'].get())
        return validate(c)

    def inform(self,text):
        self.messages.put(text)

    def background(self,action):
        def work():
            try:
                result=action()
                if result is not None:self.inform(json.dumps(result,ensure_ascii=False,indent=2) if isinstance(result,(dict,list)) else str(result))
            except Exception as error:self.inform('错误：'+str(error))
        threading.Thread(target=work,daemon=True).start()

    def browse(self,key,directory):
        selected=filedialog.askdirectory() if directory else filedialog.askopenfilename(filetypes=[('程序','*.exe')])
        if selected:self.vars[key].set(selected)

    def browse_installation(self):
        selected=filedialog.askdirectory()
        if selected:
            self.vars['installation'].set(selected)
            self.vars['executable'].set(str(Path(selected)/'tdxw.exe'))
            self.vars['tdx_data'].set(str(Path(selected)/'vipdoc'))

    def save(self):
        try:
            self.config=save(self.path,self.gather())
            if self.engine and self.engine.is_alive():
                self.reload_requested = True
                self.engine.stop()
                self.root.after(300,self.reload_wait)
                self.inform('配置已保存；正在安全停止旧连接并重连补缺。')
            else:self.inform('配置已保存。')
            return True
        except Exception as error:messagebox.showerror('配置错误',str(error));return False

    def reload_wait(self):
        if not self.reload_requested:
            return
        if self.engine and self.engine.is_alive():
            self.root.after(300,self.reload_wait)
        elif any(pair['enabled'] for pair in self.config['pairs']):
            self.reload_requested = False
            self.engine=Engine(copy.deepcopy(self.config));self.engine.start()

    def apply_fields(self):
        for key,var in [('installation','installation'),('executable','executable'),('data_directory','tdx_data')]:
            self.vars[var].set(self.config['tdx'][key])
        for key,var in [('data_directory','exact_data'),('endpoint','endpoint'),('proxy','proxy'),
            ('connection_timeout','connection_timeout'),('rest_endpoint','rest_endpoint'),
            ('rest_timeout','rest_timeout'),('rest_retries','rest_retries'),('publish_seconds','publish_seconds')]:
            self.vars[var].set(str(self.config[key]))
        self.refresh_pairs()

    def check(self):
        try:
            c=self.gather()
            checks={pair['symbol']:registration_check(c,pair)[1] for pair in c['pairs']}
            self.inform({'配置':'有效','注册检查':checks})
        except Exception as error:self.inform('配置检查失败：'+str(error))

    def start_client(self):
        try:self.inform(Client(self.gather()).start())
        except Exception as error:self.inform('启动失败：'+str(error))

    def start(self):
        if self.engine and self.engine.is_alive():self.inform('同步已运行');return
        if self.save():
            if not any(p['enabled'] for p in self.config['pairs']):self.inform('没有启用币种');return
            if not self.config['tdx']['installation']:self.inform('请配置通达信副本目录');return
            self.engine=Engine(copy.deepcopy(self.config))
            self.engine.start()
            self.notebook.select(3)

    def stop(self):
        self.reload_requested = False
        if self.engine:self.engine.stop()
        self.inform('已请求停止；等待有限REST请求和安全发布退出。')

    def backfill(self):
        if self.engine and self.engine.is_alive():self.engine.backfill_requested.set()
        else:self.start()

    def refresh_pairs(self):
        for item in self.tree.get_children():self.tree.delete(item)
        for index,pair in enumerate(self.config['pairs']):
            self.tree.insert('', 'end',iid=str(index),values=(pair['symbol'],pair['display_name'],pair['code'],pair['market'],
                '是' if pair['enabled'] else '否',pair['history_start']))

    def selected(self):
        selection=self.tree.selection()
        if not selection:raise ValueError('请先选择币种')
        return int(selection[0])

    def edit_pair(self,edit=False):
        try:index=self.selected() if edit else None
        except Exception as error:self.inform(str(error));return
        pair=copy.deepcopy(self.config['pairs'][index]) if index is not None else {'symbol':'','display_name':'','code':'397903',
            'market':'sz','enabled':True,'history_start':default_settings()['pairs'][0]['history_start']}
        dialog=tk.Toplevel(self.root);dialog.title('编辑币种' if edit else '添加币种');dialog.transient(self.root)
        variables={}
        for row,(key,label) in enumerate([('symbol','现货交易对'),('display_name','显示名称'),('code','外部代码397xxx'),('market','市场关联（已验证sz）'),('history_start','历史起点（含UTC偏移）')]):
            ttk.Label(dialog,text=label).grid(row=row,column=0,padx=10,pady=8,sticky='w')
            variables[key]=tk.StringVar(value=pair[key]);ttk.Entry(dialog,textvariable=variables[key],width=42).grid(row=row,column=1,padx=10)
        enabled=tk.BooleanVar(value=pair['enabled']);ttk.Checkbutton(dialog,text='启用同步',variable=enabled).grid(row=5,column=1,sticky='w')
        def done():
            try:
                replacement={key:var.get().strip() for key,var in variables.items()};replacement['enabled']=enabled.get()
                c=copy.deepcopy(self.config)
                if index is None:c['pairs'].append(replacement)
                else:c['pairs'][index]=replacement
                validate(c);self.config=c;self.refresh_pairs();dialog.destroy()
            except Exception as error:messagebox.showerror('币种配置错误',str(error),parent=dialog)
        ttk.Button(dialog,text='保存',command=done).grid(row=6,column=1,pady=12)

    def toggle_pair(self):
        try:
            pair=self.config['pairs'][self.selected()];pair['enabled']=not pair['enabled'];self.refresh_pairs()
        except Exception as error:self.inform(str(error))

    def delete_pair(self):
        try:del self.config['pairs'][self.selected()];self.refresh_pairs();self.inform('已移除同步配置；历史及已管理文件保留。')
        except Exception as error:self.inform(str(error))

    def validate_pair(self):
        try:
            pair=copy.deepcopy(self.config['pairs'][self.selected()]);c=self.gather()
            def check():
                import bridge
                from urllib.parse import urlencode
                api=bridge.API({'base_url':c['rest_endpoint'],'data_dir':c['data_directory'],'timeout_seconds':c['rest_timeout'],
                    'retries':c['rest_retries'],'request_spacing_seconds':.3})
                data,_=api.get('exchangeInfo',symbol=pair['symbol']);item=data['symbols'][0]
                return {'symbol':item['symbol'],'status':item['status'],'spot':item['isSpotTradingAllowed'],
                    'registration':registration_check(c,pair)[1]}
            self.background(check)
        except Exception as error:self.inform(str(error))

    def prepare_registration(self):
        try:
            pair=copy.deepcopy(self.config['pairs'][self.selected()]);c=self.gather()
            def prepare():
                allowed, reason = registration_check(c, pair)
                if not allowed and 'pending' not in reason and 'missing' not in reason:
                    raise ValueError(reason)
                import bridge
                import sqlite3
                from contextlib import closing
                path=Path(c['data_directory'])/'market.sqlite3'
                if not path.exists():raise ValueError('请先同步精确日线或补历史')
                with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
                    rows=[json.loads(x[0]) for x in db.execute("SELECT payload FROM bars WHERE symbol=? AND interval='1d' AND final=1 ORDER BY open_ms",(pair['symbol'],))]
                if not rows:raise ValueError('没有已收盘日线；注册入口不能用分钟TXT替代')
                folder=Path(c['data_directory'])/'registration';folder.mkdir(parents=True,exist_ok=True)
                output=folder/(pair['symbol']+'-DAY.txt')
                lines=['\t'.join([bridge.dt(row[0]).strftime('%Y-%m-%d')]+[row[i] for i in (1,2,3,4,5,7)]) for row in rows]
                output.write_bytes(('\r\n'.join(lines)+'\r\n\r\n').encode('ascii'))
                return ('日线注册TXT：'+str(output)+'\n在已知外部品种入口导入：日期/开/高/低/收/基础币量/报价币额，Tab、0忽略行、YYYY-MM-DD、原始比例、3位。填写代码后3位'+pair['code'][3:]+
                    '，简称'+pair['display_name']+'。导入后检查配置；未完成时仅该币种显示暂停。')
            self.background(prepare)
        except Exception as error:self.inform(str(error))

    def test_connection(self):
        try:c=self.gather();self.background(lambda:probe(c,seconds=c['connection_timeout']+5))
        except Exception as error:self.inform(str(error))

    def open_log(self):
        path=Path(self.vars['exact_data'].get())/'runtime.log'
        if path.exists():subprocess.Popen(['notepad.exe',str(path)])
        else:self.inform('日志尚未创建')

    def redraw(self):
        try:self.inform(Client(self.gather()).redraw())
        except Exception as error:self.inform(str(error))

    def capture(self):
        try:
            c=self.gather();path=Path(c['data_directory'])/'evidence'/('chart-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.bmp')
            self.inform(Client(c).capture(path))
        except Exception as error:self.inform(str(error))

    def restore(self):
        try:
            if self.engine and self.engine.is_alive():raise ValueError('请先停止同步并正常关闭通达信')
            c=self.gather()
            if Client(c).windows():raise ValueError('请正常关闭所选客户端；不会强杀')
            Publisher(c,lambda **x:None).restore();self.inform('已恢复首次写入备份；精确历史保留。')
        except Exception as error:self.inform(str(error))

    def import_config(self):
        path=filedialog.askopenfilename(filetypes=[('JSON','*.json')])
        if path:
            try:
                c=load(path);self.config=c;self.apply_fields();self.save();self.inform('配置已导入并载入窗口。')
            except Exception as error:self.inform(str(error))

    def export_config(self):
        path=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('JSON','*.json')])
        if path:
            try:save(path,self.gather());self.inform('已导出配置（可能含代理凭据，请自行保管）')
            except Exception as error:self.inform(str(error))

    def poll(self):
        while not self.messages.empty():
            text=self.messages.get();self.status_text.configure(state='normal');self.status_text.insert('end',str(text)+'\n');self.status_text.see('end');self.status_text.configure(state='disabled')
        if self.engine:
            self.root.title('币安 → 通达信 · '+self.engine.snapshot()['connection']+'（显示试验）')
            state=self.engine.snapshot()
            # Stable status panel, without exposing precision loss as hidden implementation detail.
            if not hasattr(self,'state_label'):
                self.state_label=ttk.Label(self.root,wraplength=1000);self.state_label.pack(anchor='w',padx=12)
            self.state_label.configure(text='连接：'+state['connection']+' | 已入库：'+str(state['applied'])+
                ' | 最后行情：'+str(state.get('last_event_ms','—'))+' | 文件更新：'+str(state.get('last_file_ms','—'))+
                '\n补缺：'+state.get('history','—')+' | 错误：'+str(state.get('error') or state.get('file_error') or state.get('history_error') or state.get('connection_error') or '无')+
                '\n品种：'+str({k:v for k,v in state.items() if k.startswith(('registration_', 'pair_error_'))}))
        self.root.after(500,self.poll)

    def close(self):
        self.stop()
        if self.engine and self.engine.is_alive():self.root.after(300,self.close_wait)
        else:self.root.destroy()

    def close_wait(self):
        if self.engine and self.engine.is_alive():self.root.after(300,self.close_wait)
        else:self.root.destroy()
