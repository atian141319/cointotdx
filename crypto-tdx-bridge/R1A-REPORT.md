# CRYPTO-TDX-R1A 补正报告

复核状态：READY_FOR_GPT_R1A_REVIEW。整体 PARTIAL；通达信分钟接入 BLOCKED。工作目录：D:\project\cointotdx\crypto-tdx-bridge。本轮只修复 R1 复核发现，F1、F3 既有通过范围保留；F2 补正提交 GPT 复核，不自行登记 PASS。

## 空区间与实际记录交集

Store.ingest 在同一事务内逐条使用响应记录的实际 open_ms 更新空区间，条件为 start_ms <= open_ms < end_ms，并限定 binance/spot、交易对和周期。响应首尾跨度不再作为数据出现依据。

新增回归：00:01–00:02 空区间收到仅 00:00、00:02 的响应后，仍为 pending_verification，重查截止时间保留，00:01 缺口保留；进程重新打开数据库后状态保持；随后确实返回 00:01，才更新为 data_observed，缺口消失。没有填充价格或把空响应标为完整。

## LC1 真实非零尾部

纠正 LC1-P0-REPORT.md 的尾部描述。sh600000、sz000001 各 3360 条尾部均为零；bj899050 2400 条全部非零，1262 个不同值，首条 19660816、原始四字节 10002c01。新增真实样本测试检查统计和逐字节回编码，并与既有 .roundtrip 比较；尾部语义保持 UNCONFIRMED，不推测用途，不清零。

新增 validation/r1a/native-tail-verification.json 及 POSIX 路径版 native-format.json，保留旧 validation/lc1-p0/native-format.json 及其哈希。全部核查来自项目内只读样本，不写客户端，不生成可发布币种 LC1。

## 跨平台路径

新生成的包清单、offline_inputs、LC1 副本引用统一使用 POSIX 相对路径。验证器先规范化旧 Windows 反斜杠，再验证路径和查找清单；规范化后重复及大小写碰撞均拒绝。拒绝 POSIX/Windows 绝对路径、UNC、盘符相对路径、父目录跳转、冒号/数据流及解析后越界的路径。来源安装目录等绝对定位信息仅是溯源字段，不能作为包内读取路径。

测试同时覆盖旧 Windows 清单路径、真实旧 LC1 证据路径及恶意路径，不重写旧证据。独立验证器仍以 mode=ro&immutable=1 打开封存数据库，报告写到包外。

## 验证与交付

Windows 完整 unittest 共 29 项。新包由 tools/package_r1a.py 在独立时间戳目录构建，ZIP 在 Windows 全新解包后执行 tools/offline_review.py；Ubuntu WSL 使用独立 Linux /tmp 目录再次从 ZIP 全新解包，运行同一套 29 项测试和同一离线复验入口，无需改写输入。Linux 测试进程运行于 unshare --net 网络命名空间，仅有 loopback；离线复验另外禁止 Python socket 审计事件。全过程比较包内文件 SHA-256，确认输入不变。

执行结果以包外 tests.txt、offline-receipt/、linux-receipt/ 和 delivery.json 为准；工具失败则停止交付，不伪报通过。新包、源码版本、两端回执 SHA-256 记录于 delivery.json 和相邻 .sha256 文件。新包内含源码、测试、原始响应、数据库快照、CSV、旧证据和新增尾部核查证据。

旧 review-package.zip 哈希保持 944f8898f649162501d2a0fd6048f9727b7af12393fffeb9ec002cbc4b2b5cd4；R1 包哈希保持 8f5b69c980d35c572cb928b18b7b68a8946daeeada73a2cc77ac5149ab832b3c。未 push，未调用账户/交易接口，未进入客户端试导。下一步仅由 GPT 复核 R1A 修复与证据。
