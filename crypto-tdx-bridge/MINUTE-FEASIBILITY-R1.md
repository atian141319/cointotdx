# CRYPTO-TDX-R1：分钟接入技术可行性

复核状态 READY_FOR_GPT_R1_REVIEW；整体 PARTIAL，分钟接入 BLOCKED。本轮没有操作 GUI、调用客户端写入接口或发布候选行情。

## 核查范围及证据

安装目录 D:\Programs\tdx；目标 V7.73 / 6.4.15(x64) / Build 26080415 由既有截图确认。静态文件检查见 evidence/r1/technical/inventory.json：10 个二进制的哈希及 PE 导出名、SDK/文档/压缩包文件清单。只读取二进制，没有加载或修改。

已检查根目录与非账户/行情缓存子目录中的文档、头文件及归档；T0002 仅定向检查 dlls。没有遍历私人账户数据、股票导出内容或 GUI 菜单。清单中的排除范围明确保留，不能把有限搜索解释为整个程序不存在接口。

官方资料原始快照及 SHA-256 在 technical/official/、official-followup/、official-sdk-complete/。在线说明书索引发布标记为 2026-09-21，其中定制品种章文本可读；索引指向的四个独立章节 URL 返回 404，已保留请求结果，不把失败页当作正文。30 MB TdxQuant PDF 下载未完成，保留部分文件及超时记录，不宣称完整审阅该 PDF。官方 DLL SDK 通过续传完整获取，RAR 完整性测试通过，仅解压并静态阅读头文件/示例，未执行代码。

## 五项核查结论

| 项目 | 分类 | 直接依据与边界 |
|---|---|---|
| 外部独立品种注册 | 已确认：手工文本品种管理入口；自动注册/分钟关联未找到依据 | docs/setting.jpg 的代码前缀397、名称及文本导入设置；官方在线说明书定制品种章描述添加外部品种。没有实际注册 BTCUSDT/ETHUSDT，没有确认该命名空间的 .lc1 文件映射。 |
| 外部1分钟历史写入/导入 | 未找到依据 | 已见外部文本入口只有日期字段；原生 .lc1 存在并可回编码，但没有文档把独立币种注册与 minute cache 路径关联。未找到受支持的外部 OHLCV 写入接口签名。 |
| 全天与周末交易时间 | 未找到依据 | 外部设置截图无交易日历或时段项；dsmarket.dat 存在，但没有随附可用字段规范；原生样本仅股票/指数时段。格式可编码分钟数/日期不证明渲染或聚合允许这些时段。 |
| 价格/币数量/金额精度范围 | 已确认候选二进制数值类型及样本误差；外部品种单位/存储语义未找到依据 | .lc1 9120记录满足 <HHfffffII；float32 误差及 uint32 分数量阻断见 LC1-P0-REPORT.md。外部文本精度选项0–3位，但显示精度与内部精度的关系未验证。 |
| 历史行情重新加载 | 已确认文档有手动重新导入文本动作；外部分钟自动刷新未找到依据 | 官方定制品种章描述从先前路径重新导入；PYPlugins/TPythClient.dll 的 ReFreshCacheKLine、ReFreshCacheAll 仅有导出名，没有参数、目标、文件锁/缓存语义契约。没有调用它们或完成增量显示验收。 |

官方文本入口与再导入依据：[金融终端在线说明书索引](https://www.tdx.com.cn/products/helpfile/tdxw/left.html)，具体章节在本地 manual-findings.json 的 official_section_paths 与 manual_sections 中。官方版本说明另确认定制外部品种可设置小数位：[V7.64 更新说明](https://www.tdx.com.cn/article/soft_7_64.html)；较早版本说明不能单独证明当前分钟能力。

## 已验证不适用的接口类别

以下“已验证不适用”指已核对官方资料/头文件的接口用途，不表示已经运行插件或客户端验收：

- 官方 DLL SDK 的 PluginTCalcFunc.h、TCalcFuncSets.cpp、TCalcFuncSets.h：RegisterTdxFunc 注册计算函数；pPluginFUNC 输入为长度和 float 数组，示例生成输出数组。不是注册证券/市场或写入 OHLCV 历史的接口。完整 SDK 哈希 dbd7117e481dd6bff4fd9fd13bc9da8419356bd66bc46af1c286a38e056ed279，源地址见 [官方 SDK 列表](https://www.tdx.com.cn/products/user_redbook_style2.html)。
- get_market_data 是取行情；TdxAiData 从通达信后台取得数据。这些下载/读取能力不能证明向金融终端注入外部行情。[官方 HTTP 调用说明](https://help.tdx.com.cn/quant/docs/markdown/mindoc-1hdhbmi50d038.html)、[TdxAiData 简介](https://help.tdx.com.cn/quant/docs/markdown/mindoc-1hjbgqpdhv114.html)。
- send_file 把文件路径交给策略数据浏览，支持文档类型；没有外部分钟行情入库契约。[官方 send_file](https://help.tdx.com.cn/quant/docs/markdown/ctx.stock.md/mindoc-1h10u17ue9464.html)。
- EXTERNVALUE、EXTERNSTR、SIGNALS_USER、EXTDATA_USER 为当前品种的外部数值/字符串/序列读取。TDXDLL 为公式计算调用，均不能直接认定为外部币种行情写入。[官方公式函数列表](https://help.tdx.com.cn/gspt/docs/markdown/redword/functionlist.html)。
- datatool/wintool.rar 仅列有 v3/v4 DataTool.exe；downit.zip 是下载配置/提示；tick/newday 是数据下载和工具脚本，没有独立市场注册及外部分钟写入规范。没有执行这些下载或 DataTool.exe。

## 本地导出名的限制

taapi.dll/taapix64.dll 的 TaApi_CreateInstance 等只证明存在应用接口工厂；TDataParse.dll 的 fn_sync_getdata 等没有外部历史写入契约；TCalc64.dll 的 AutoImportExport/SaveIndex 与计算接口关联；tdxrpc64.dll 的通用 RPC 注册/调用名不等于注册金融品种。以上均为“未找到依据”，不通过猜参数、调用私有符号或修改程序来验证。

## 继续所需的官方说明/支持答复

请 GPT 决定后续是否向官方技术支持询证；本工具没有自行发消息。至少需要：

1. 此 Build 支持的外部独立市场/证券注册接口、代码范围、名称与持久配置文件、BTCUSDT/ETHUSDT 到历史目录的关联规则。
2. 外部1分钟历史写入/导入契约，包含文件布局版本、日期/时区、开盘或收盘时间标签、量额单位、浮点/整数范围和尾部含义。
3. 00:00–23:59 连续交易、周末、跨日及 UTC 日/周/月聚合的受支持配置。
4. 精确的基础币分数数量表示方式及价格/金额精度；若必须改变精度或单位，先由 GPT 决策。
5. 文件更新后缓存失效/历史重载接口及参数、刷新时机、文件占用规则；是否需要人工导入或重启。

当前没有足以满足上述要求的可信完整候选接入方案。隔离试验的前置条件、备份/恢复和验收设计在 LC1-P0-REPORT.md；不把 .lc1 布局猜测升级为客户端实施方案。
