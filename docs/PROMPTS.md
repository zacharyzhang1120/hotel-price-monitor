# 酒店竞对价格监控系统 — AI 开发 Prompts

> 本文档提供各开发阶段的 AI Prompt，可直接用于 Claude Code / Cursor / Copilot 等 AI 编码工具。

---

## 总览 Prompt（项目启动用）

```
我要构建一个酒店竞对价格监控系统，分为两期开发。

【一期 — 桌面端浏览器插件】
- 后端：Python FastAPI + SQLAlchemy 2.0 (async) + SQLite + Playwright
- 前端：WXT 框架 + Vue 3 + ECharts 5 + Tailwind CSS
- 抓取目标：携程、去哪儿、同程 3 个 OTA 平台
- 抓取内容：每家酒店在每个平台的起价房型 + 起价
- 抓取范围：1 家我方酒店 + 5 家竞对酒店
- 抓取维度：立即刷新和后台定时默认抓当日入住价格；远期 7 天价格作为单独补抓任务
- 定时调度：当前线上每天 08:00、11:00、14:00、17:00、20:00、23:00 自动抓取今日价
- 浏览器插件：独立弹出面板（Popup），展示远期价格日历热力图 + 当日竞对对比表 + 可收起的运营判断/抓取证据
- 支持手动触发抓取按钮

【二期 — 企业微信推送（未来）】
- 默认使用 OpenClaw WeCom 插件推送到企业微信，也可替换为企业微信 Webhook 或自建应用 API
- 每次抓取完成后推送格式化的日报文本

【核心架构约束】
二期必须最大程度复用一期代码。所有业务逻辑（抓取、存储、价格对比、推送文案生成）
必须在 Python 后端实现。浏览器插件和微信推送都是后端 API 的纯消费者。
二期预估新增代码 < 100 行。

请参考 docs/PRD.md 了解完整需求，并严格按照 docs/PLAN.md 的 P0 → P1 → P2 顺序开发。
优先完成 P0 MVP：先用种子数据和 MockScraper 跑通完整闭环，再逐个平台替换为真实 OTA 抓取器。
```

---

## Phase 1: P0 后端骨架 + 数据模型 + Mock 抓取器

### Prompt 1.1 — 初始化后端项目

```
创建一个 Python FastAPI 后端项目，结构如下：

hotel-price-monitor/backend/
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI 入口，注册路由，启动时 init_db()
│   ├── config.py        # 配置（数据库路径、平台列表、抓取时间等）
│   ├── database.py      # SQLAlchemy async engine + session + Base
│   ├── models/
│   │   ├── __init__.py
│   │   ├── hotel.py     # Hotel ORM: id, name, is_mine, distance_km
│   │   ├── hotel_platform.py  # HotelPlatformMapping ORM: hotel_id, platform, platform_hotel_id, hotel_url, default_room_name
│   │   ├── scrape_run.py      # ScrapeRun ORM: trigger_type, status, started_at, finished_at, task stats
│   │   └── price_record.py    # PriceRecord ORM: batch_id, hotel_id(FK), platform, check_in_date, cheapest_room, cheapest_price, scraped_at
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── hotel.py     # Pydantic: HotelCreate, HotelResponse
│   │   └── price.py     # Pydantic: CalendarPriceItem, CalendarResponse, ScrapeTriggerResponse
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── hotels.py    # GET /api/v1/hotels
│   │   ├── prices.py    # GET /api/v1/prices/calendar
│   │   └── scrape.py    # POST /api/v1/scrape/trigger, GET /api/v1/scrape/status/{task_id}
│   └── services/
│       ├── __init__.py
│       └── scraper/
│           ├── __init__.py
│           ├── base.py  # BaseScraper 抽象基类
│           └── mock.py  # Mock 抓取器，P0 阶段用于快速跑通 MVP
├── data/                # SQLite 数据库文件（gitignore）
├── tests/
├── requirements.txt
└── README.md

要求：
1. 使用 SQLAlchemy 2.0 async 模式，engine 用 aiosqlite
2. 所有数据库操作通过 async session
3. FastAPI lifespan 中自动 init_db() 创建表
4. CORS 允许所有来源（开发阶段）
5. price_records 表需要 3 个索引：(batch_id)、(hotel_id, platform, check_in_date, scraped_at)、(scraped_at)
6. hotel_platform_mappings 表有 UNIQUE(platform, platform_hotel_id) 约束
7. 配置文件中 SCRAPE_SCHEDULE_HOURS = [12, 18, 22]
8. 数据库 URL 默认 sqlite+aiosqlite:///./data/hotel_prices.db
```

### Prompt 1.2 — Mock 抓取器与种子数据

```
编写 MockScraper 和种子数据脚本，用于 P0 阶段快速跑通 MVP。真实 OTA 抓取器在 P1 阶段逐个平台替换。

BaseScraper 接口：
- async fetch_calendar(hotel_url: str, check_in_dates: list[date]) -> list[PricePoint]
- PricePoint = {check_in_date, cheapest_room, cheapest_price}

MockScraper 要求：
1. 继承 BaseScraper
2. 根据 hotel/platform/date 生成稳定但有波动的模拟价格
3. 每次手动刷新允许产生小幅随机变化，便于测试价格对比和日报变化
4. 返回 8 天价格：今日 + 未来 7 天
5. 不访问外网，不依赖 Playwright
6. 可通过配置 SCRAPER_MODE=mock|real|mixed 切换

种子数据要求：
1. 创建 1 家我方酒店 + 5 家竞对酒店
2. 每个真实酒店只创建一条 Hotel 记录
3. 每个酒店创建 3 条 HotelPlatformMapping：携程、去哪儿、同程
4. 写入 distance_km、platform_hotel_id、hotel_url、default_room_name
5. 重复执行脚本不重复插入

验收：
- 执行种子脚本后有 6 家真实酒店和 18 条平台映射
- 触发一次 Mock 抓取后生成 1 条 scrape_run 和 144 条 price_records
- 连续触发多次后，trend API 可以看到同一入住日的历史价格变化
```

### Prompt 1.3 — 携程抓取器（P1 阶段使用）

```
编写携程（Ctrip）酒店价格抓取器，继承 BaseScraper 抽象基类。注意：该 Prompt 属于 P1 真实抓取阶段，P0 MVP 不依赖它完成。

BaseScraper 接口：
- async fetch_calendar(hotel_url: str, check_in_dates: list[date]) -> list[PricePoint]
- PricePoint = {check_in_date, cheapest_room, cheapest_price}

携程抓取策略（优先级从高到低）：

【优先方案】API 逆向
1. 分析携程酒店详情页的 Network 请求
2. 找到价格日历的 AJAX/JSONP 接口（通常包含 calendar/price/detail 等关键词）
3. 直接 HTTP 请求该接口，构造不同日期的请求参数
4. 解析 JSON 响应中的最低价格和房型

【兜底方案】Playwright UI 自动化
1. 启动无头浏览器，访问酒店详情页
2. 等待页面加载完成
3. 查找日期选择器（通常 class 包含 "date" / "calendar"）
4. 循环点击每个目标日期
5. 等待价格区域刷新
6. 提取起价房型名称和价格
7. 每次点击间隔 1-3 秒（随机），模拟人类操作

要求：
- 使用 Playwright async API（playwright.async_api）
- 设置合理的超时（30s）
- 异常处理：单个日期抓取失败不影响其他日期
- 日志记录每次抓取的关键步骤
- PricePoint 中日期格式为 Python date 对象
- 价格提取后去掉 ¥、, 等符号，转为 float

酒店 URL 格式示例：
https://hotels.ctrip.com/hotel/1234567.html
```

---

## Phase 2: P1 真实平台抓取

### Prompt 2.1 — 去哪儿抓取器（P1 阶段使用）

```
编写去哪儿（Qunar）酒店价格抓取器，继承 BaseScraper。注意：该 Prompt 属于 P1 真实抓取阶段，P0 MVP 不依赖它完成。

与携程的区别：
- 去哪儿 URL 中包含 fromDate 参数，可直接通过修改 URL 来切换日期
- URL 格式：https://hotel.qunar.com/city/城市/酒店名?fromDate=2026-06-25
- 优先方案：遍历 8 个日期，构造不同 fromDate 的 URL，Playwright 访问后提取起价
- 页面结构相对简单，价格通常在 .price 或 .room-price 类名下

要求同携程抓取器。
```

### Prompt 2.2 — 同程抓取器（P1 阶段使用）

```
编写同程（Tongcheng）酒店价格抓取器，继承 BaseScraper。注意：该 Prompt 属于 P1 真实抓取阶段，P0 MVP 不依赖它完成。

同程特点：
- 三平台中反爬最弱，移动端 API 可能更易抓取
- URL 格式：https://www.ly.com/hotel/酒店ID/
- 优先抓取移动端页面 (m.ly.com) 或移动端 API
- 日期切换后价格通过 AJAX 局部刷新

要求同携程抓取器。
```

### Prompt 2.3 — ScraperManager 与平台切换

```
编写 ScraperManager 和平台切换机制。P0 阶段默认调用 MockScraper；P1 阶段按平台逐个切换到真实抓取器。

ScraperManager 职责：
- 接收所有需要抓取的 (酒店, 平台) 组合
- 使用 asyncio.gather 并发执行所有抓取任务
- 每次 scrape_all() 创建一个 ScrapeRun 批次，收集结果后统一写入数据库，并返回 batch_id
- 单个任务失败不阻塞其他任务
- 返回抓取统计：{batch_id, total, success, failed, errors[]}
- 支持 SCRAPER_MODE=mock|real|mixed
- 支持 ENABLED_PLATFORMS=ctrip,qunar,tongcheng
- mixed 模式下，已接入真实抓取器的平台使用真实抓取，未接入的平台继续使用 MockScraper

手动触发接口：
- POST /api/v1/scrape/trigger -> {task_id, status: "started"}
- GET /api/v1/scrape/status/{task_id} -> {status, progress}
- 使用 asyncio.create_task 在后台执行，不阻塞 API 响应
- 用内存 dict 跟踪 task 状态

要求：
- P0 阶段只要求手动触发，不实现 APScheduler
- 定时调度放到 P2 阶段实现
```

---

## Phase 3: 报告服务 + 价格 API

### Prompt 3.1 — 报告服务

```
编写 ReportService（services/report_service.py）。

职责：将最新的价格数据生成为结构化日报，支持多种输出格式。

接口：
class ReportService:
    async def generate_daily_summary(date: date, batch_id: int | None = None) -> dict:
        """
        查询 date 这天入住的指定批次或最新成功批次价格，生成结构化摘要。
        返回格式：
        {
            "date": "2026-06-25",
            "scrape_time": "2026-06-25T18:00:00",
            "my_hotel": {
                "name": "亚朵·西湖店",
                "baseline_platform": "tongcheng",
                "baseline_room": "尊享大床房",
                "baseline_price": 668,
                "platforms": {
                    "ctrip": {"room": "豪华大床房", "price": 688},
                    "qunar": {"room": "豪华大床房", "price": 678},
                    "tongcheng": {"room": "尊享大床房", "price": 668}
                }
            },
            "competitors": [
                {
                    "name": "竞对A",
                    "distance_km": 0.8,
                    "platforms": {
                        "ctrip": {"room": "商务大床房", "price": 638, "vs_mine_same_platform": -50},
                        "qunar": {"room": "商务大床房", "price": 658, "vs_mine_same_platform": -20},
                        "tongcheng": {"room": "舒享大床房", "price": 628, "vs_mine_same_platform": -40}
                    },
                    "lowest_price": 628,
                    "lowest_platform": "tongcheng",
                    "vs_mine": -40  // 与我方 baseline_price 比较，负数=竞对更低, 正数=竞对更高
                },
                ...
            ]
        }
        """

    def format_for_push(summary: dict, format: str) -> str:
        """
        format='json' -> JSON 字符串
        format='wechat_text' -> 格式化的微信推送文本（见 PRD 附录 A）
        format='wechat_markdown' -> Markdown 格式
        """

路由 (routers/reports.py)：
- POST /api/v1/reports/generate?format=json|wechat_text|wechat_markdown&date=2026-06-25&batch_id=1
- GET /api/v1/reports/latest -> 最新报告 JSON

要求：
- format_for_push 使用模板方法，不同 format 调用不同的渲染函数
- 微信文本格式使用缩进列表，不使用 Unicode 表格线，避免企业微信手机端非等宽字体导致错位
- 价格对比逻辑：
  1. 我方基准价 baseline_price = 我方各平台起价中的最低价，用于“低于我方最低价”和竞对总览 vs_mine
  2. 平台差价 vs_mine_same_platform = 竞对某平台价格 - 我方同平台价格，用于逐平台展示
  3. 竞对最低价 lowest_price = 该竞对各平台起价中的最低价，lowest_platform 记录最低价所在平台
  4. 不使用我方均价作为基准
- wechat_text 输出示例：
  📊 6月25日 18:00 竞对价格日报
  ━━━━━━━━━━━━━━━━━━━━
  🏨 我方：亚朵·西湖店
  最低起价：同程 尊享大床房 ¥668
  平台价格：携程 ¥688 | 去哪儿 ¥678 | 同程 ¥668

  竞对价格：
  竞对A（0.8km）
    携程 ¥638（较我方同平台 -¥50）
    去哪儿 ¥658（较我方同平台 -¥20）
    同程 ¥628（较我方同平台 -¥40）⚠️最低

  ⚠️ 低于我方最低价：
  竞对A·同程 ¥628（低 ¥40）
```

### Prompt 3.2 — 价格查询 API

```
编写价格查询相关的 API 路由 (routers/prices.py)。

接口：

1. GET /api/v1/prices/calendar
   参数：date (起始日期), days (天数, 默认8), hotel_ids (可选, 逗号分隔), batch_id (可选)
   返回：{
     "data": [
       {
         "hotel_id": 1,
         "hotel_name": "竞对A",
         "is_mine": false,
         "platform": "ctrip",
         "check_in_date": "2026-06-25",
         "cheapest_room": "商务大床房",
         "cheapest_price": 638.0
       },
       ...
     ]
   }
   逻辑：
   - 默认取最新成功 ScrapeRun 批次；传 batch_id 时取指定批次
   - CalendarPriceItem 不含 scraped_at 字段（减小响应体积），但必须包含 cheapest_room 供当日对比表展示
   - 如果某个组合没有价格数据，cheapest_price 为 null，cheapest_room 为 null

2. GET /api/v1/scrape/runs/{batch_id}/tasks/{task_result_id}/evidence
   返回：{
     "evidence": {
       "points": [
         {
           "selected": {"room": "大床房", "price": 276.0},
           "scraper_evidence": {
             "source": "dom",
             "candidates": [{"room": "大床房", "price": 276.0}],
             "timings": {"goto": 3.2, "wait_render": 6.2, "extract": 3.9}
           }
         }
       ]
     }
   }
   逻辑：解释每个任务为什么选中该房型和价格，并辅助定位页面加载、登录、验证或解析问题。

实现要点：
- 使用 ScrapeRun 查询最新成功批次，避免不同平台按最大 scraped_at 混批
- price_service.py 封装查询逻辑，router 只做参数校验和响应格式化
```

---

## Phase 4: 浏览器插件

### Prompt 4.1 — WXT 项目初始化

```
创建一个 WXT (webextension-tools) 浏览器插件项目，放在 hotel-price-monitor/extension/。

技术栈：WXT + Vue 3 + TypeScript + Tailwind CSS + ECharts 5

初始化要求：
1. 使用 npm create wxt@latest 初始化
2. 选择 Vue + TypeScript 模板
3. 安装依赖：
   - echarts
   - vue-echarts (Vue 3 ECharts 组件)
   - tailwindcss @tailwindcss/vite (WXT 支持 Vite 插件)
4. 配置 wxt.config.ts：
   - manifest.permissions: ["storage"]
   - manifest.host_permissions: ["http://localhost:8080/*"]
   - popup 入口指向 entrypoints/popup/
5. Tailwind 配置 content 路径包含 entrypoints/ 和 components/
6. 插件 popup 尺寸 800×600px

最终可运行：npm run dev 能正常加载插件
```

### Prompt 4.2 — 核心组件实现

```
实现以下 Vue 3 组件（使用 Composition API + <script setup>）：

【CalendarHeatmap.vue — 远期价格日历热力图】
Props：hotelFilter (可选酒店 ID 筛选)
数据来源：GET /api/v1/prices/calendar?date=today&days=8
使用 ECharts heatmap 类型：
- X 轴：日期（今天 ~ D+7），type='category'
- Y 轴：(酒店, 平台) 组合标签，如 "竞对A-携程"、"竞对A-去哪儿"
- 视觉映射 visualMap：按同平台差价计算颜色，竞对某平台价格低于我方同平台价格为红色（威胁），高于我方同平台价格为绿色（安全）
- 若展示我方酒店行，可使用中性色或作为基准行，不参与威胁/安全判断
- 空数据单元格显示灰色 "—"
- 点击事件：emit('cell-click', {hotel_id, platform, check_in_date})
- 顶部切换 tabs：全部 | 竞对A | 竞对B | ... | 竞对E

【ComparisonTable.vue — 当日对比表】
Props：无（自动取最新数据）
数据来源：GET /api/v1/prices/calendar?date=today&days=1
- 表格列：酒店 | 平台 | 起价房型 | 起价 | VS我方
- 我方酒店行高亮（背景色区分）
- 价格排序：从低到高
- VS我方列：正数绿色显示 "+¥XX"，负数红色显示 "-¥XX"
- VS我方列默认按同平台价格比较；底部汇总展示几个竞对最低价低于我方最低价、最低价是哪个

【InsightPanel.vue — 运营判断】
Props：selectedHotelId, calendarRows, comparisonRows
数据来源：前端已加载价格数据，必要时调用报告或分析 API
- 默认收起，不占用巡检页主视觉
- 展示谁比我便宜
- 展示是否需要关注调价
- 展示未来价格是否异常
- 每条判断必须能追溯到价格数据，不输出无依据结论

【OperationsPanel.vue — 运行状态与证据】
数据来源：GET /api/v1/scrape/runs、GET /api/v1/scrape/runs/{batch_id}/tasks、GET /api/v1/scrape/runs/{batch_id}/tasks/{task_result_id}/evidence
- 展示最近批次、任务数、成功/失败、耗时
- 每个任务提供“查看证据”
- 证据中展示候选房型、候选价格、最终选择、页面信号、耗时、错误

【HotelSelector.vue】
- 横向 tabs 组件
- Props：hotels (酒店列表), modelValue (当前选中)
- Emit：update:modelValue

【RefreshButton.vue】
- 按钮 + 状态展示
- 点击触发 POST /api/v1/scrape/trigger
- 轮询 GET /api/v1/scrape/status/{task_id}（每 2 秒）
- 状态：空闲 | 抓取中... (3/18) | 完成 ✓ | 失败 ✗
- 完成后 emit('done')

【StatusBadge.vue】
- 显示最后抓取时间和状态
- Props：lastScrapeTime, status
- 相对时间显示："3 分钟前" / "1 小时前"
```

### Prompt 4.3 — Composables 和类型定义

```
编写 Vue 3 Composables 和 TypeScript 类型定义。

【types/index.ts】
定义与后端 Pydantic Schema 对应的 TS 接口：
- CalendarPriceItem { hotel_id, hotel_name, is_mine, platform, check_in_date, cheapest_room, cheapest_price }
- CalendarResponse { data: CalendarPriceItem[] }
- TrendItem { scraped_at, platform, cheapest_price }
- TrendResponse { data: TrendItem[] }
- ScrapeTriggerResponse { task_id, status, message }
- ScrapeStatusResponse { status, progress, error }
- ReportSummary { date, scrape_time, my_hotel, competitors[] }

【composables/useApi.ts】
const API_BASE = 'http://localhost:8080/api/v1'

- fetchCalendar(date: string, days: number, hotelIds?: number[]): Promise<CalendarResponse>
- fetchTrend(hotelId: number, checkInDate: string, platform?: string): Promise<TrendResponse>
- triggerScrape(): Promise<ScrapeTriggerResponse>
- getScrapeStatus(taskId: string): Promise<ScrapeStatusResponse>

使用 fetch API，统一错误处理；P0 阶段先用组件内错误状态展示，后续可接 toast 组件

【composables/usePrices.ts】
- 管理价格数据的响应式状态
- calendarData: Ref<CalendarPriceItem[]>
- trendData: Ref<TrendItem[]>
- loading: Ref<boolean>
- error: Ref<string|null>
- 提供 refreshCalendar() 和 loadTrend() 方法

【composables/useScrape.ts】
- 管理手动抓取状态
- isScraping: Ref<boolean>
- progress: Ref<string>
- lastScrapeTime: Ref<Date|null>
- trigger(): Promise<void> — 触发 + 轮询直到完成
```

### Prompt 4.4 — Popup 主界面组装

```
组装 Popup 主界面 (entrypoints/popup/App.vue)：

布局（从上到下）：
┌──────────────────────────────────────────┐
│ 🏨 酒店竞对价格监控      最后抓取: 18:00  [立即刷新] │  ← 顶部栏
├──────────────────────────────────────────┤
│ [全部] [竞对A] [竞对B] [竞对C] [竞对D] [竞对E] │  ← HotelSelector
├──────────────────────────────────────────┤
│                                          │
│          📅 远期价格日历热力图             │  ← CalendarHeatmap
│          (ECharts 热力图, 占 50% 高度)     │
│                                          │
├──────────────────────────────────────────┤
│  📊 今日价格对比              [复制文本]   │
│  ┌────────┬──────┬────────┬──────┬─────┐ │  ← ComparisonTable
│  │  酒店   │ 平台  │  房型   │ 起价  │VS我 │ │
│  ├────────┼──────┼────────┼──────┼─────┤ │
│  │ ...    │ ...  │ ...    │ ...  │ ... │ │
│  └────────┴──────┴────────┴──────┴─────┘ │
├──────────────────────────────────────────┤
│  运营判断（默认收起）                     │  ← InsightPanel
│  运行状态 / 查看证据                      │  ← OperationsPanel
└──────────────────────────────────────────┘

逻辑：
- 打开 popup 时自动 fetchCalendar(today, 8)
- HotelSelector 切换时过滤 CalendarHeatmap 和 ComparisonTable 数据
- CalendarHeatmap 的 cell-click 事件 → 聚焦对应日期价格明细
- RefreshButton 点击 → 默认触发 scope=today，完成后刷新今日价格；远期使用“补抓远期”
- ComparisonTable 的"复制文本"按钮 → 生成纯文本表格写入剪贴板
```

---

## Phase 5: P0 MVP 联调验收

### Prompt 5.1 — MVP 联调验收

```
基于 Prompt 1.2 已创建的 seed_hotels.py、seed_data.json 和 MockScraper，完成 P0 MVP 联调验收。不要重复创建第二套种子脚本或第二份种子数据。

验收步骤：
1. 启动后端服务
2. 执行种子数据脚本，确认有 6 家真实酒店和 18 条平台映射
3. 调用 POST /api/v1/scrape/trigger 触发 Mock 抓取
4. 轮询 GET /api/v1/scrape/status/{task_id} 直到完成
5. 调用 GET /api/v1/prices/calendar?date=today&days=8，确认有 144 条价格数据
6. 调用 POST /api/v1/reports/generate?format=wechat_text，确认日报为缩进文本且差价口径正确
7. 打开浏览器插件，确认热力图、当日对比表、运营判断、抓取证据、手动刷新都可用

通过标准：
- P0 MVP 不依赖真实 OTA 抓取
- 手动刷新会生成新 scrape_run 批次
- 前端展示和日报内容都来自最新成功批次
- 任一平台 Mock 数据缺失时，前端能展示空状态，不崩溃
```

---

## Phase 6: P2 定时调度与稳定性

### Prompt 6.1 — APScheduler 定时调度

```
编写定时调度模块 scheduler.py。注意：该 Prompt 属于 P2 阶段，P0 MVP 不依赖它完成。

定时调度要求：
- 使用 APScheduler AsyncIOScheduler
- 6 个 Cron 任务：每天 08:00、11:00、14:00、17:00、20:00、23:00
- 每个任务调用 scrape_and_report(scope="today") 函数，只抓当前有效门店组
- scrape_and_report() 流程：
  1. 调用 ScraperManager.scrape_all()，创建 ScrapeRun 并写入 price_records
  2. 获取返回的 batch_id
  3. 基于本批次生成日报（调用 ReportService）
  4. 如已配置推送通道，则推送 wechat_text
  5. 记录日志和错误摘要

要求：
- APScheduler 在 FastAPI lifespan 中启动和关闭
- 提供配置开关 SCHEDULER_ENABLED，开发阶段默认 false
- 同一时间只允许一个 scrape_run 运行，避免重复抓取
- 定时任务失败不影响手动触发接口
```

### Prompt 6.2 — 备份与抓取稳定性

```
补充 P2 稳定性能力：

1. 数据库备份
   - 每日 copy SQLite 数据库到 data/backups/
   - 文件名包含日期时间
   - 保留最近 30 份备份

2. 抓取稳定性
   - 单日期失败可重试
   - 平台级超时
   - 并发限制
   - partial_success 状态
   - 错误摘要写入 scrape_runs.error_summary

3. 日志
   - 记录平台、酒店、入住日期、错误原因
   - 不在日志中输出敏感凭证
```

---

## Phase 7: P2.4 企业微信推送（未来）

### Prompt 7.1 — 企业微信推送配置（默认 OpenClaw WeCom）

```
配置企业微信推送通道，实现定时调用后端报告 API 并推送。默认使用 OpenClaw WeCom 插件；如果项目已有企业微信 Webhook 或自建应用 API，也可以替换为等价实现。

前置条件：
- 企业微信已注册（200人以内免费）
- 默认方案需要 OpenClaw 已部署（Docker 或本地）
- 默认方案需要 WeCom 插件已安装：npx -y @dingxiang-me/openclaw-wecom-cli install

配置步骤：
1. 在企业微信后台创建自建应用，获取 CorpId、AgentId、Secret
2. 配置 OpenClaw WeCom 插件 YAML 或等价推送配置：
   - 设置定时任务 Cron：08:10, 11:10, 14:10, 17:10, 20:10, 23:10（晚于抓取 10 分钟，确保数据已就绪）
   - 设置 HTTP 回调：POST http://localhost:8080/api/v1/reports/generate?format=wechat_text
   - 将返回的文本通过 WeCom 消息接口发送给指定用户/群

3. 推送消息将直接显示在微信的企业微信中（企业微信与个人微信互通后）。

预估新增代码量：
- scheduler.py 中增加推送通道调用
- ~50 行 OpenClaw 插件 YAML 配置或等价企业微信推送配置
- 无需新增任何业务逻辑代码
```
