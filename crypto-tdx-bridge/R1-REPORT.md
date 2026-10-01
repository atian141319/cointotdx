# CRYPTO-TDX-R1 补正及复核报告

本轮完成状态：**READY_FOR_GPT_R1_REVIEW**。项目整体 **PARTIAL**；通达信分钟接入 **BLOCKED**。没有自行 PASS、提交或 push。

目录：D:\project\cointotdx\crypto-tdx-bridge。未覆盖旧 review-package.zip、review-package.sha256 或旧 evidence 的测试/回读/包清单；新交付在 artifacts/CRYPTO-TDX-R1-时间戳/。精确源码版本为新 PACKAGE-MANIFEST.json 的 source_version_sha256。

## F1：跨进程持久限流

新增 rate_control.py。429/418 的原始 Retry-After、HTTP头、raw_id、观测时间、响应哈希、解析错误及截止时间进入 SQLite 冷却账本和事件历史。账本默认位于本 Windows 用户的 %LOCALAPPDATA%\CryptoTdxBridge\rate-control.sqlite3，独立于交易对、data_dir、官方主机和命令。

本工具只调用公开行情端点，因此按直接出口 IP 的公共请求范围协调，两个配置官方主机及所有公开请求都受同一 scope 阻断。SQLite BEGIN IMMEDIATE 覆盖预检查至本次响应状态记录，避免其他本工具进程在新冷却尚未提交时继续发请求。不能控制同 NAT 下其他软件、用户或机器；网络出口变化时继续保守等待，不自动清除旧冷却。

依据为币安官方 REST 的 IP Limits 与 HTTP Retry-After：[官方 REST 说明](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md)。原始文档及哈希在 technical/official/binance-rest.source。数字秒及带时区 HTTP 日期可解析；秒数以本地观测和有效服务端 Date 较晚者为基准，保存 UTC 截止。最后一次响应先持久化，再判断重试耗尽。未到期的新 check/sync/run 进程立即退出；到期后重新执行恢复。无效/缺失头不推测冷却期，持久 manual_review 阻断并保留理由。status 可查看账本状态，不提供无依据绕过命令。

测试包括：最后一次429带较长 Retry-After、前后截止延长、429跨进程 check/sync/run、更换data_dir与主机、418跨进程、到期恢复、HTTP日期，以及缺失/NaN/负数/坏日期/超范围的持久阻断。都是模拟HTTP响应，没有主动触发真实币安封禁。系统时钟和持久账本必须可信；删除账本或换 Windows 用户属于人为破坏协调，不声称能阻止这种操作。

## F2：空区间观测、退避和重查

新增 empty_ranges 当前观测表与 empty_events 历史表。成功空响应保留请求开盘范围、raw_id、观测/服务端时间、attempts、next_check_ms、分类和重查策略。默认60秒指数退避，最多3600秒，可配置初始值与上限。

到期前从补抓窗口中扣除已经观测为空的范围；涉及当前分钟时按完整开盘桶暂缓，避免仅因结束时间多了几秒就重抓同一根未收盘区间。缺口仍由实际已收盘 bars 推导；空响应不等于未上市，也不将缺口标完整。pending_verification 表示历史待核实空区间，unclosed_absent 表示当前尚未结束的桶没有记录；已存历史缺失与这些证据分别显示。不会把机器中缺少的记录直接称作交易所永久缺失。

到期自动重查，sync --force-recheck 允许提前复查空区间但不能绕过F1。区间后来出现数据时旧“整个区间为空”结论失效，状态更新为 data_observed；尚未返回的其他时间仍从真实 bars 计算缺口。暂停/删除配置不删除空观测或历史。

测试覆盖新币种元数据通过、第一次为空、数据库关闭重开后不重复请求、显式复查、到期自动发现数据、退避上限、缺口保留及当前桶分类。此类异常响应为测试模拟，没有把它们伪称为真实 NEWUSDT 交易对行情。

## F3：可直接离线审查的包

tools/verify.py 是独立读取路径，不导入 bridge、不发请求。显式参数为 --db、--raw-dir、--export-dir、--manifest、--report-dir。检查文件存在后以 mode=ro&immutable=1 打开已封存快照，并启用 query_only；拒绝活跃 WAL 数据库，不创建空库或旁路文件。

验证包清单 SHA-256/大小/路径、原始响应来源及哈希、bars/revisions/metadata/empty_events 与响应的对应关系，以及 CSV 的完整最终记录覆盖、准确十进制字符串、时间、raw_id、来源与批次。报告只能写到包目录之外的全新报告位置。SHA-256 用于完整性，ZIP 外部哈希必须单独核对，不把自述清单当签名。

tools/offline_review.py 是全新解包的一条命令入口：从包清单读取已有快照路径，用 Python audit hook 拒绝所有 socket 事件，关闭字节码写入并验证包内文件前后哈希/文件集合完全一致。无需联网、重抓或手动复制数据库。

tools/package_r1.py 产生新的时间戳包，使用 SQLite backup 封存快照，仅从既有数据库生成审计 CSV。然后将 ZIP 解到新的 fresh-unpack 目录，执行离线入口，将回执、stdout/stderr 和 SHA-256 放在 ZIP 外。旧包保持原 SHA-256：944f8898f649162501d2a0fd6048f9727b7af12393fffeb9ec002cbc4b2b5cd4。

离线测试覆盖全新目录、零网络、包输入不变、缺库不创建、篡改哈希、原始请求交易对身份不一致及拒绝包内报告路径。最终实际解包复验回执在本次 artifacts 目录。

## 附加 LC1-P0 与技术核查

9120 条真实原生记录候选布局回编码逐字节一致，但独立品种注册/文件路径、全天/周末及自动刷新契约没有找到可用依据。20 根币行情候选全部因 uint32 无法表达分数成交量而阻断；float32 价格最大样本误差0.00375 USDT，金额最大样本误差0.05434420 USDT。没有 int() 截断、单位转换、价格缩放、填造尾部或客户端写入。

官方 DLL SDK 为公式计算扩展，不能当行情写入接口；公开行情读取、自定义信号、send_file 亦已按官方用途排除。详细分类、官方来源、文件哈希和有前置条件的隔离试验设计分别见 MINUTE-FEASIBILITY-R1.md、LC1-P0-REPORT.md。

## 验证与交付位置

本轮 unittest 覆盖26项，详细输出随新包 evidence/r1/tests.txt；实际数量及是否通过以该输出为准。新包 PACKAGE-MANIFEST.json 列完整文件清单及源码版本，外部 review-package-r1.sha256 校验ZIP，offline-receipt.sha256 校验全新解包离线回执。delivery.json 给出各文件绝对路径。

用户无需继续寻找菜单或改动通达信。现在停在 READY_FOR_GPT_R1_REVIEW，由 GPT 复核补正、数值阻断及官方分钟接口需求；不能以已解析 .lc1 改变实际接入状态。

