# API 流量看板 v1.0

个人本机 AI API 用量面板。提供总览、输入/输出 Token 趋势、平台分布、模型排行、用量明细、项目筛选、CSV 导出、JSON 导入、官方余额、OpenAI 官方用量/费用、预算与站内阈值提醒。

**默认演示模式，演示数据不会写入数据库。勾选「使用真实数据」才能查看真实记录。**

## 1. 启动

需要 Python 3.10 或更新版本，无第三方运行时依赖。解压后在本项目目录运行：

```bash
python3 server.py
```

Windows 可使用 `python server.py`，或双击 `start.bat`。macOS/Linux 也可运行 `bash start.sh`。

打开 http://127.0.0.1:8787 。端口冲突时运行 `python3 server.py --port 8790`。

服务器仅监听 127.0.0.1，适用于单人本机使用，没有公网登录系统。不要直接把它转发至公网。停止服务按 Ctrl+C。

## 2. API Key 的准确文件与字段

克隆仓库后，相对于仓库根目录的准确路径：

```text
api-traffic-dashboard/config/settings.json
```

请在你电脑上的本地文件中填写密钥，不要在 GitHub 网页上填写。此仓库是公开仓库，切勿提交填写了密钥的配置文件。页面「账户与接入」会显示本机运行时的准确绝对路径。

注意：`.gitignore` 不会忽略已经被 Git 跟踪的文件。修改本地配置前可运行 `git update-index --skip-worktree api-traffic-dashboard/config/settings.json`，并始终检查提交中没有真实密钥。

只编辑这个文件中的三个值（保留 JSON 双引号）：

```json
{
  "deepseek_api_key": "YOUR_DEEPSEEK_API_KEY",
  "kimi_api_key": "YOUR_KIMI_API_KEY",
  "openai_admin_key": "YOUR_OPENAI_ADMIN_KEY"
}
```

此片段展示需修改的字段，**不要用它覆盖整个配置文件**；预算、汇率与价格等字段也必须保留。当前文件内只有占位符，没有任何真实密钥。

- `deepseek_api_key`：DeepSeek API Key，用于官方余额查询。
- `kimi_api_key`：Moonshot 国内平台 API Key，用于 `api.moonshot.cn` 官方余额查询；国际站账户不适用这个端点。
- `openai_admin_key`：OpenAI **组织 Admin Key**，需具备用量与费用读取权限。普通项目 API Key 无法代替。
- 没有的平台保留 `YOUR_...` 占位符，程序不会发出对应请求。

保存后，勾选「使用真实数据」，点击「同步数据」。后台启动时同步一次，随后默认每 30 分钟同步一次（服务需保持运行），同步至少间隔 5 分钟。修改密钥无需重启；同步状态显示成功时间及错误，不把错误伪装为成功。

密钥只供后端读取；静态资源采用白名单，配置文件、数据库和 Python 源码不会通过 HTTP 返回。配置文件明文存储在你自己的机器，Git 默认忽略；不要共享填写了密钥的文件或压缩包。第一版未引入密钥加密服务，建议保留本机用户的文件访问权限。

## 3. 哪些数据能够自动获取？

| 平台 | 自动获取 | Token 数据来源 |
|---|---|---|
| DeepSeek | 官方账户余额及币种 | 程序上报 / JSON 导入的调用记录 |
| Kimi / Moonshot 国内站 | 官方可用余额（人民币） | 程序上报 / JSON 导入的调用记录 |
| OpenAI | 组织 completions 用量、组织全部产品官方费用 | 选择「OpenAI 官方用量」；也可选择本地调用记录 |
| Codex API | 对应 OpenAI API 账户中的可用统计 | 受官方接口类别覆盖范围限制；订阅配额不属于 API 账单 |

**填写 DeepSeek / Kimi Key 不会自动获得完整历史 Token 消耗。** 它们的余额接口不提供这些明细。要持续统计，请在使用 API 的程序中上报响应 usage，或导入你已有的日志。

OpenAI 官方用量默认同步最近 30 天，`sync_days` 可设为 1–90 天；只接入 completions 类别，不承诺覆盖其他 API 产品的 Token。官方账单可能包含其他产品、存在延迟，故独立展示。官方日桶使用 UTC，页面按 Asia/Shanghai 标记桶起始时间，日桶不能按中国时区重新精确切分。

「调用记录」与「官方用量」是互斥的数据视图，绝不相加；不自动补全历史，也不读取浏览器控制台凭据。

## 4. 导入调用记录

在「真实数据 → 用量明细 → 导入 JSON」中选择 `examples/usage.json`（示例记录本身也非真实账单，请按需修改）。支持顶层数组或 `{"events":[...]}`。

也可由你的程序发送到本机接口：

```python
from collector import report_usage

# response 是你调用供应商 API 后获得的 JSON；request_id 必须稳定且唯一。
report_usage(
    provider="deepseek",
    request_id=response["id"],
    model=response["model"],
    usage=response["usage"],
    project="个人编程",
)
```

collector.py 只发送统计字段，不发送提示词、回答或 API Key。请在 API 调用完成后记录准确调用时间；默认上报时间为当前 Asia/Shanghai 时间。流式调用必须等待最终 usage，缺失字段传 null；不根据文本猜测 Token。采集失败将返回 False，不影响你的主业务。

原始上报格式：

```json
{
  "events": [{
    "id": "your-stable-request-id",
    "provider": "deepseek",
    "model": "deepseek-chat",
    "project": "个人编程",
    "time": "2026-10-27T10:00:00+08:00",
    "input_tokens": 1000,
    "output_tokens": 300,
    "cached_tokens": 200,
    "requests": 1
  }]
}
```

POST 到 `http://127.0.0.1:8787/api/events`，Content-Type 为 application/json。每批最多 5000 条，最大 2MB。字段 `input_tokens` 已包含 `cached_tokens`；已确认无缓存时填 0，不知道则填 null。reasoning Token 若已包含在 output_tokens 中，不再次累加。

同平台同请求 ID 只入库一次。批次中的任何记录不合法则整批拒绝。失败重试产生的新计费调用应使用新的 ID；保留供应商请求 ID 作为幂等键。不接受前端上报费用值，费用由本机配置计算。

## 5. 模型价格、预算与币种

`config/settings.json` 的 `prices` 默认为空，**未配置价格时费用显示未知，不使用可能过时的官方价格**。从平台当前价目表核对后填写：

```json
"prices": [
  {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "effective_from": "2026-10-01",
    "currency": "CNY",
    "input_per_million": "2.00",
    "output_per_million": "3.00",
    "cache_read_per_million": "0.20"
  }
]
```

**以上价格完全是格式示例，不是官方报价。** 计价单位统一为每百万 Token。平台必须为 deepseek/kimi/openai，币种为 CNY 或 USD。多个价格版本按调用日期取最新的已生效版本。

公式：`((输入 - 缓存读取) × 非缓存输入单价 + 缓存读取 × 缓存单价 + 输出 × 输出单价) / 1,000,000`。

已导入记录保留入库时计算的费用。补充历史价格后可显式执行 `python3 reprice.py`，按价格生效日期重算**本地调用记录**；不修改官方账单。

第一版不实现缓存写入、阶梯价格、批处理折扣等特殊计费规则；有这些计费项的模型不应直接套用本公式。价格版本按中国时区日期生效，暂不支持日内调价。

- 原始估算费用保存原币。总览将 USD 按配置的 `usd_to_cny` 手动参考汇率折算人民币，非实际结算汇率；原始记录仍保留 USD。
- `monthly_budget_cny` 是初始预算，页面保存后 SQLite 中的预算优先。
- 预算提醒是当前筛选范围的费用对比。查看月度预算时选择本月、全部平台、全部模型与项目。
- 未知价格和未知用量不按 0 计费。覆盖率同时显示为「已计价记录 / 全部记录」。
- 不实现订阅内 Codex 配额查询，不把 ChatGPT 订阅价格换算成 Token。

## 6. 项目结构

```text
server.py                  HTTP API、SQLite、平台同步、标准化、费用计算
collector.py               给现有 API 程序使用的轻量上报助手
reprice.py                 按历史价格版本重算本地调用费用
config/settings.json       你需要编辑的 API Key 占位符、价格、同步配置
config/settings.example.json  不含真实密钥的配置模板
public/                    HTML、CSS、JavaScript，前端无外部 CDN
examples/usage.json         导入格式示例（模拟记录）
docs/design-v1.md           第一版设计方案
docs/review-and-scope.md   审阅意见、实现映射和后续范围
tests/test_dashboard.py     核心测试
data/usage.sqlite3         首次运行自动生成，内含你的本地记录与同步快照
```

服务端请求只发送到代码中固定的官方 HTTPS 地址，并拒绝重定向；官方接口错误仅显示状态，不返回包含密钥的响应体。CSV 对公式前缀作转义；写接口有同源与 Host 校验。此为本机单用户架构，不是面向公网的多租户服务。

## 7. 验证与限制

运行测试：

```bash
python3 -m unittest discover -s tests -v
node --check public/app.js
```

交付时：9 项后端测试通过；Chromium 验证桌面/390px 手机布局、演示图表、平台筛选、页面导航、真实数据空状态、配置路径展示，未发现 JavaScript 运行错误。官方请求逻辑使用模拟响应验证，**没有真实账户密钥，未做官方接口端到端验证**。端点和权限可能随平台变化，以官方文档为准：

- https://api-docs.deepseek.com/api/get-user-balance
- https://platform.moonshot.cn/docs/api/balance
- https://platform.openai.com/docs/api-reference/usage
- https://platform.openai.com/docs/api-reference/organization

当前是原设计的本机 MVP。完整 PostgreSQL/多用户、网关转发、邮件提醒、自动汇率、费用预测与异常检测列入后续阶段。
