# 携程价格抓取代码复用说明

更新时间：2026-07-07

## 结论

当前项目里的携程抓取代码有较高复用价值，但建议按“单酒店抓取能力”拆出来复用，不建议把整个后端项目原样搬走。

最值得复用的是：

1. 携程酒店详情页价格抓取器：`backend/app/services/scraper/ctrip.py`
2. 房型和价格解析工具：`backend/app/services/scraper/playwright_utils.py`
3. 携程酒店名称自动匹配 URL：`backend/app/services/ctrip_search.py`
4. 携程登录态生成脚本：`backend/scripts/login_ctrip.py`
5. 单 URL 探测入口：`backend/app/services/probe_service.py`
6. 批量抓取、超时、进度和证据记录思路：`backend/app/services/scrape_manager.py`

可以复用成一个独立能力：

```text
输入：携程酒店 URL + 入住日期列表
输出：每个日期的起价房型、起价价格、抓取证据、耗时明细
```

## 可直接复用的模块

### 1. 携程真实抓取器

文件：`backend/app/services/scraper/ctrip.py`

职责：

- 读取 `data/ctrip_state.json` 登录态
- 用 Playwright 打开携程酒店详情页
- 给 URL 自动加 `checkIn/checkOut/checkin/checkout` 参数
- 拦截图片、字体、视频等非必要资源，加快加载
- 等待房型区域渲染
- 从 DOM 中提取房型和价格候选
- 选择最低价房型
- 保存证据：目标 URL、最终 URL、候选房型、选中房型、耗时、页面信号

复用价值：

- 这是当前最核心的“携程详情页 -> 起价房型和价格”能力。
- 适合抽到其他项目作为 `CtripHotelPriceScraper`。

复用注意：

- 它依赖项目里的配置项，例如 `SCRAPE_TIMEOUT`、`HEADLESS`、`CTRIP_STATE_FILE`。
- 它依赖 `BaseScraper` 和 `PricePoint` 数据结构。
- 如果脱离本项目使用，需要把配置改成构造参数或独立 settings。

### 2. 房型价格解析工具

文件：`backend/app/services/scraper/playwright_utils.py`

职责：

- `with_check_in_params()`：给携程 URL 拼入住和离店日期
- `extract_lowest_price()`：从文本里提取最低价格
- `extract_room_price_candidates()`：从携程房型文本里提取“同一房型卡片内”的房型和价格
- `extract_cheapest_room_price_candidate()`：选出最低价候选
- `RoomPriceCandidate`：房型和价格候选结构

复用价值：

- 这部分和数据库、FastAPI、调度器无关，最容易直接抽出来。
- 当前项目之前遇到“价格对但房型名不准”的问题，后续已经把逻辑改成尽量按同一卡片配对，而不是全页最低价再倒推房型。

复用注意：

- 解析逻辑是针对携程网页端中文 DOM 文本调过的。
- 如果携程改版，优先调整这里的关键词和噪声词。

### 3. 携程酒店名称自动匹配

文件：`backend/app/services/ctrip_search.py`

职责：

- 根据酒店名称调用携程搜索建议接口
- 返回候选酒店 ID、名称、详情页 URL、匹配分
- 按匹配分选择最佳候选

复用价值：

- 可以解决“只输入酒店名称，自动获取携程 URL”的需求。
- 当前配置页的一键匹配就是依赖它。

复用注意：

- 默认城市是海口 `city_id=42`。
- 换城市必须传新的 `city_id`。
- 名称相似酒店较多时仍可能误匹配，需要保留候选列表给人工确认。

### 4. 携程登录态脚本

文件：`backend/scripts/login_ctrip.py`

职责：

- 打开可视化 Chromium
- 让用户扫码或短信登录携程
- 保存 cookies/localStorage 到 `data/ctrip_state.json`
- 抓取器后续复用该登录态

复用价值：

- 比在服务器上手动处理登录简单。
- 可以在本地登录后，把 `ctrip_state.json` 复制到服务器。

复用注意：

- `ctrip_state.json` 是敏感登录态文件，不要提交到 GitHub。
- 登录态会过期，过期后抓取会出现登录页、解锁优惠、价格不可见等现象。

### 5. 单 URL 探测服务

文件：`backend/app/services/probe_service.py`

职责：

- 输入平台、酒店 URL、入住日期、房型名
- 调用真实抓取器或 mock 抓取器
- 设置单次探测超时
- 返回抓取成功/失败和价格点

复用价值：

- 适合做“配置 URL 后先测一下能不能抓”的能力。
- 可以给运营后台、调试脚本、自动验收使用。

## 可参考但不建议直接搬的模块

### 1. 批量抓取管理器

文件：`backend/app/services/scrape_manager.py`

职责：

- 从数据库读取酒店平台映射
- 按并发数批量抓取
- 支持今日优先、远期补抓、快速超时、失败重试
- 每家酒店完成后立即写入数据库
- 记录任务结果、证据、错误摘要

复用价值：

- 里面的“今日优先”“超时不中断全局”“完成一家写一家”“保留证据链”都值得复用。

不建议直接搬的原因：

- 强依赖当前数据库模型：`Hotel`、`HotelPlatformMapping`、`PriceRecord`、`ScrapeRun`、`ScrapeTaskResult`
- 强依赖当前产品里的“我方酒店 + 竞对酒店组”逻辑
- 如果换项目，建议只复制思路，不直接复制整个类。

### 2. 抓取 API 路由

文件：`backend/app/routers/scrape.py`

职责：

- `POST /scrape/trigger` 启动抓取
- `GET /scrape/status/{task_id}` 查看进度
- `GET /scrape/readiness` 检查配置是否完整
- `POST /scrape/probe` 探测单个 URL
- `POST /scrape/login` 触发携程登录

复用价值：

- API 设计可以参考。

不建议直接搬的原因：

- 它绑定了当前前端、当前状态结构和当前数据库。
- 更适合把接口形态复制到新项目，再接入独立抓取服务。

## 最小复用包建议

如果要把携程抓取能力拆给别的项目，建议抽成这样：

```text
ctrip_price_scraper/
  __init__.py
  models.py              # PricePoint, RoomPriceCandidate
  settings.py            # 超时、headless、登录态路径、资源拦截开关
  url_utils.py           # with_check_in_params
  parser.py              # extract_room_price_candidates 等解析函数
  scraper.py             # CtripScraper
  search.py              # search_ctrip_hotel_by_name
  login.py               # 生成 storage_state
```

对外暴露两个主要函数即可：

```python
async def fetch_ctrip_prices(
    hotel_url: str,
    check_in_dates: list[date],
    state_file: str | None = None,
) -> list[PricePoint]:
    ...

async def search_ctrip_hotel_url(
    hotel_name: str,
    city_id: int,
) -> list[CtripHotelCandidate]:
    ...
```

## 当前项目里的推荐调用方式

单酒店抓取：

```python
from datetime import date
from app.services.scraper.ctrip import CtripScraper

scraper = CtripScraper()
points = await scraper.fetch_calendar(
    "https://hotels.ctrip.com/hotels/detail/?cityId=42&hotelId=436575",
    [date.today()],
)
```

按酒店名称匹配携程 URL：

```python
from app.services.ctrip_search import search_ctrip_hotel_by_name, best_ctrip_match

candidates = await search_ctrip_hotel_by_name("温德森酒店(海口高铁东站美兰机场店)", city_id=42)
match = best_ctrip_match(candidates)
```

单 URL 探测：

```python
from datetime import date
from app.services.probe_service import probe_scraper

result = await probe_scraper(
    platform="ctrip",
    hotel_url="https://hotels.ctrip.com/hotels/detail/?cityId=42&hotelId=436575",
    check_in_date=date.today(),
    mode="real",
)
```

## 必要运行条件

真实抓取至少需要：

```text
SCRAPER_MODE=real
ENABLED_PLATFORMS=ctrip
REAL_PLATFORMS=ctrip
HEADLESS=true
SCRAPE_TIMEOUT=45000
SCRAPE_GOTO_WAIT_UNTIL=domcontentloaded
SCRAPE_BLOCK_RESOURCES=true
SCRAPE_BLOCK_STYLESHEET=false
SCRAPE_RENDER_WAIT_MAX_MS=5000
SCRAPE_RENDER_WAIT_INTERVAL_MS=500
```

服务器上建议：

```text
SCRAPE_CONCURRENCY=1
SCHEDULED_SCRAPE_SCOPE=today
SCRAPE_FAST_MAPPING_TIMEOUT=120
SCRAPE_MAPPING_TIMEOUT=300
```

关键文件：

```text
data/ctrip_state.json
```

没有这个登录态文件时，携程可能显示登录页、解锁优惠或隐藏会员价，价格就容易抓不到。

## 当前已验证效果

根据 `docs/REAL_SCRAPE_ACCEPTANCE.md`：

- 阿里云环境下，`SCRAPE_CONCURRENCY=1`、`scope=today` 时，6 家海口酒店今日价抓取曾达到 6/6 成功。
- 当并发过高或抓远期太多时，主要瓶颈是携程页面加载慢，不是解析代码本身。
- 当前测试版更适合“今日价定时后台抓取 + 远期价格按需补抓”。

根据 `docs/OPTIMIZATION_LOG.md`：

- 本地 6 家酒店抓取从 169s 优化到约 85s。
- 优化重点包括资源拦截、智能等待、跳过不必要展开、减少全页扫描、耗时明细记录。

## 已知限制

1. 携程网页结构变化会影响解析准确率。
2. 阿里云访问携程页面较慢，`goto` 是最大耗时来源。
3. 登录态过期后，价格可能不可见。
4. 酒店名称自动匹配可能误选相似酒店，需要候选列表和人工确认兜底。
5. 当前抓取器目标是“起价房型和价格”，不是完整房型库存、取消政策、早餐权益全量结构化。
6. 价格是网页端可见价，可能受会员、优惠券、设备、登录状态、地区和时间影响。

## 建议后续优化

优先级从高到低：

1. 把 `ctrip.py` 和 `playwright_utils.py` 抽成独立包，减少对当前项目配置的依赖。
2. 给 `extract_room_price_candidates()` 增加更多真实页面文本样本测试，尤其是套餐价、券后价、会员价、品牌首单。
3. 给自动匹配 URL 增加人工确认模式：低于匹配分阈值时返回候选，不直接保存。
4. 抓取证据里保存更多“候选卡片原文”，方便排查房型价格错配。
5. 后台定时优先抓今日价，远期价格分散到低峰期补抓。
6. 如果后续规模变大，考虑把携程抓取服务从主后端拆出来，作为独立 worker 队列运行。

## 复用判断

| 模块 | 是否适合复用 | 复用方式 |
| --- | --- | --- |
| `ctrip.py` | 适合 | 抽成独立 `CtripScraper`，配置改为参数 |
| `playwright_utils.py` | 非常适合 | 直接抽 parser/url 工具 |
| `ctrip_search.py` | 适合 | 抽成酒店名搜索服务，保留候选确认 |
| `login_ctrip.py` | 适合 | 改成独立 CLI 登录工具 |
| `probe_service.py` | 适合参考 | 适合做调试接口或健康检查 |
| `scrape_manager.py` | 只适合参考 | 复制调度思路，不建议直接搬数据库逻辑 |
| `routers/scrape.py` | 只适合参考 | 复制 API 形态，不建议直接搬状态实现 |

