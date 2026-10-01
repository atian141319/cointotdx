# 币安现货本地采集工具

当前状态 **PARTIAL**：采集、SQLite 存储及精确审计导出可运行；通达信外部分钟接入 **BLOCKED**，没有完成客户端真实验收，也不称为全自动接入。

实际目录：`D:\project\cointotdx\crypto-tdx-bridge`。需要 Windows、Python 3.11+；不需要第三方依赖、交易账户或 API 密钥。网络只使用币安官方公开现货端点，直连，不更改电脑代理。

## 安装和小样本检查

在 PowerShell 中进入上述目录后运行：

```powershell
python --version
python bridge.py check --config config.smoke.json
python bridge.py sync --config config.smoke.json
python bridge.py status --config config.smoke.json
python bridge.py export --config config.smoke.json
```

smoke 配置限定 BTCUSDT/ETHUSDT 的 2026-09-26 23:55 至 09-27 00:05 UTC；各较大周期向下对齐起点。page_limit=3 用于验证分页，不会默认下载全部交易对或多年分钟数据。R1 独立回读改用下文的只读离线包入口。

## 配置和持续同步

复制 `config.example.json` 为 `config.json`，按需要设置 history_start、pairs、data_dir、output_dir、sync_seconds、timeout_seconds、retries、request_spacing_seconds 和 page_limit。较大历史范围会产生大量分钟记录，先跑 smoke。可选 history_end 限定历史样本；正常持续更新配置不设置这个参数。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File start.ps1 -Action check
powershell -NoProfile -ExecutionPolicy Bypass -File start.ps1 -Action sync
powershell -NoProfile -ExecutionPolicy Bypass -File start.ps1 -Action run
```

run 在当前控制台持续运行；另开 PowerShell，运行同一脚本的 `-Action stop` 请求停止，也可 Ctrl+C。停止请求在请求前或退避等待中检查，正在进行的网络请求需等待完成或超时。status/gaps 可在同步期间查看；export 需要获得单实例锁。启动脚本仅设置当前进程执行策略，不更改机器策略。

每轮重新读取配置：添加 pairs 项会补抓其历史，enabled=false 暂停该品种，删除配置项停止同步但保留数据库历史。运行中不能切换 data_dir。禁用品种仍可导出已有历史；移除配置的品种不在新批次导出，旧数据仍在 SQLite。

电脑关机时不运行；休眠期间不采集。恢复网络或再次启动后，从本地已保存记录查缺补抓。未安装开机任务；如需开机自动启动，可在 Windows 任务计划程序中运行上述 run 命令，工作目录设为项目目录，选用已有 Python 解释器。机器的真实无人值守、休眠恢复验收仍待完成。

## 查看、发布及错误处理

`data/market.sqlite3` 保存 bars、revisions、progress 和 metadata；`data/raw` 保存响应字节及 HTTP 状态、请求 URL、服务端头部和 SHA-256；`data/bridge.log` 保存错误日志。status 和 gaps 报告缺口。没有成交的交易所原生 K 线保留零值；没有返回记录的区间保持缺口。

审计 CSV 在 `output-audit/batch-*/`，`CURRENT.json` 指向当前完整批次。每个清单标明原生来源、量额单位和内部缺口。磁盘满、文件占用或发布失败时保留旧指针；不手动混合不同批次文件。重跑 sync 幂等，export 会产生新批次标识，但相同历史量价值保持一致。

429 遵循 Retry-After 并有限重试；418 立即停止。429/418 冷却写入 `%LOCALAPPDATA%\CryptoTdxBridge\rate-control.sqlite3`，不随数据目录、交易对、端点或官方主机变化，重启及 check/sync/run 都受阻断。未到期时立即退出，不发送网络请求；到期后重新执行可恢复。缺失/无效 Retry-After 会持久阻断并保留原头部及解析错误，等待 GPT/官方依据确认，不自动清除。不要删除账本绕过冷却。该账本协调本 Windows 用户的本工具进程，无法控制同出口 IP 上其他软件或其他机器。

403/451 立即停止当前进程请求并报告。普通断网在有限重试耗尽后记录，run 下轮重试；不自动切换代理或搭建中转。

成功但为空的 K 线请求写入 empty_ranges/empty_events，保留范围、raw_id、观测/服务端时间、重查时间及策略。默认退避 60 秒，逐步增至 3600 秒；配置 empty_backoff_seconds / empty_backoff_max_seconds 可调整。空响应仍是待核实区间，不等于未上市，也不消除缺口。使用 `sync --force-recheck` 显式复查空区间；此选项不能绕过 HTTP 限流。

## R1 全新解包离线复验

新的时间戳交付目录在 `artifacts/CRYPTO-TDX-R1-*/`，旧 review-package.zip 保留。将新 review-package-r1.zip 解压到全新目录，进入解压出的 crypto-tdx-bridge，然后执行：

```powershell
python -B tools/offline_review.py --package-dir . --report-dir ..\r1-review-receipt
```

无需联网、重新采集或复制数据库。工具从 PACKAGE-MANIFEST.json 选择随包快照、原始响应和当前导出，禁止 Python socket 操作，检查包内文件未变化。报告必须写到包目录之外，已有报告不覆盖。

独立验证器也支持显式路径：

```powershell
python -B tools/verify.py --db evidence/r1/market-snapshot.sqlite3 --raw-dir data/raw --export-dir output-audit --manifest PACKAGE-MANIFEST.json --report-dir ..\r1-explicit-receipt
```

数据库以 mode=ro、immutable=1 和 query_only 打开，仅接受已封存快照；缺文件或活跃 WAL 时失败，不创建空库。包清单 SHA-256 只是完整性校验，需同时核对外部提供的 ZIP SHA-256，不能当作签名认证。

R1 补正见 R1-REPORT.md；分钟接口核查见 MINUTE-FEASIBILITY-R1.md；.lc1 结果见 LC1-P0-REPORT.md。候选 JSON/24 字节前缀是诊断数据，不是可发布币种行情。没有将 fractional volume 截断或尾部清零。

## 通达信查看与恢复

目前没有可验证的币种显示步骤。`tdx-export` 会拒绝输出；审计 CSV 不应导入后冒称分钟行情。目标版本及入口证据见 P0-COMPATIBILITY.md；量价口径见 SEMANTICS.md。

没有实施客户端试导，无需恢复工具写入的客户端文件。后续试验必须先关闭客户端、备份将修改的配置和行情文件，记录完整路径和 SHA-256，再进行独立品种试验。恢复时关闭客户端，核对备份哈希，将备份还原到原路径；试验新增文件须有清单且仅移除清单所列文件。禁止覆盖股票数据、使用股票代码冒充币种或修改程序二进制。

## 测试

```powershell
python -m unittest discover -s tests -v
```

测试包括分页续传、修订与去重、闰月/跨年、部分聚合、双实例、429/封禁/断网及原子发布失败。故障注入测试不是实际断网、断电或通达信刷新验收的替代。最终结果见 VALIDATION.md。
