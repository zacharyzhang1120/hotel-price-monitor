# Claude Code 交接说明

> 日期：2026-07-03  
> 项目：hotel-price-monitor  
> 当前目标：继续完善酒店竞对价格监控系统，优先保持后台自动抓取后的可测试性、可观测性和稳定性。

---

## 1. 项目目录

主项目目录：

```bash
/Users/zhangshuaichi/Desktop/work/hotel-price-monitor
```

需要 Claude Code 打开这个目录，不要打开 `Documents/酒店价格监控小助手`。

关键目录：

```text
backend/                 FastAPI 后端
extension/               WXT + Vue 3 浏览器插件源码
extension-chrome-mv3/    Chrome 当前加载的插件产物目录
docs/                    PRD、计划、优化日志、测试说明
data/                    本地数据与备份
```

---

## 2. 当前线上状态

阿里云后端：

```text
http://8.163.49.150/hotel-price-monitor
```

API base：

```text
http://8.163.49.150/hotel-price-monitor/api/v1
```

当前线上配置：

```text
SCRAPER_MODE=real
ENABLED_PLATFORMS=ctrip
REAL_PLATFORMS=ctrip
SCHEDULER_ENABLED=true
SCRAPE_SCHEDULE_HOURS=8,11,14,17,20,23
SCHEDULED_SCRAPE_SCOPE=today
SCRAPE_CONCURRENCY=1
SCRAPE_FAST_MAPPING_TIMEOUT=120
SCHEDULED_SCRAPE_FAST_MAPPING_TIMEOUT=120
SCHEDULED_SCRAPE_RETRY_FAILED_TODAY=true
PRICE_FALLBACK_MAX_AGE_HOURS=24
REPORT_PUSH_ENABLED=false
```

当前有效门店组：

```text
我方酒店 id=7：皇马假日大酒店(海口骑楼老街省政府店)
竞对酒店 ids=8,9,10,11,12
```

最近线上验证结果：

```text
health: ok
最新批次: Batch #61
触发方式: scheduled
结果: 6/6 success
耗时: 402.6s
调度健康: ok
今日 2026-07-03 日历: 本轮 6、兜底 0、缺价 0
```

后台从 Batch #55 到 #61 已连续多轮 6/6，自动补抓机制有效。

---

## 3. 本地验证命令

后端测试：

```bash
cd /Users/zhangshuaichi/Desktop/work/hotel-price-monitor/backend
python3 -m pytest tests -q
```

当前基线：

```text
49 passed
```

插件生产构建：

```bash
cd /Users/zhangshuaichi/Desktop/work/hotel-price-monitor/extension
VITE_API_BASE=http://8.163.49.150/hotel-price-monitor/api/v1 npm run build
```

同步插件产物到 Chrome 加载目录：

```bash
rsync -a --delete \
  /Users/zhangshuaichi/Desktop/work/hotel-price-monitor/extension/.output/chrome-mv3/ \
  /Users/zhangshuaichi/Desktop/work/hotel-price-monitor/extension-chrome-mv3/
```

阿里云部署后端：

```bash
rsync -az --delete \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  --exclude 'data/*.db' \
  -e 'ssh -i /Users/zhangshuaichi/Desktop/crm_key.pem -o StrictHostKeyChecking=no' \
  /Users/zhangshuaichi/Desktop/work/hotel-price-monitor/backend/app/ \
  root@8.163.49.150:/opt/hotel-price-monitor/backend/app/

ssh -i /Users/zhangshuaichi/Desktop/crm_key.pem -o StrictHostKeyChecking=no \
  root@8.163.49.150 \
  'systemctl restart hotel-price-monitor && sleep 2 && systemctl is-active hotel-price-monitor'
```

---

## 4. 重要线上检查命令

```bash
python3 - <<'PY'
import json, urllib.request

base='http://8.163.49.150/hotel-price-monitor'
paths=[
    '/health',
    '/api/v1/scheduler/status',
    '/api/v1/scrape/config',
    '/api/v1/scrape/runs?limit=10',
    '/api/v1/prices/calendar?date=2026-07-03&days=1&hotel_ids=7,8,9,10,11,12',
]

for path in paths:
    print('\n##', path)
    with urllib.request.urlopen(base+path, timeout=25) as resp:
        data=json.load(resp)
    print(json.dumps(data, ensure_ascii=False, indent=2)[:5000])
PY
```

---

## 5. 已完成的关键能力

### 多门店组

- 用户可选择不同我方门店。
- 每个我方门店维护自己的竞对组。
- 当前组抓取、配置、日报、运行状态都按当前门店组过滤。

### 携程真实抓取

- 当前只启用携程真实抓取。
- 抓取目标是当前可见起价房型 + 起价。
- 需要 `data/ctrip_state.json` 登录态。

### 后台定时

- 每天 `08:00,11:00,14:00,17:00,20:00,23:00` 自动抓今日价。
- 只抓当前有效门店组。
- 后台健康接口会显示 ok/warning/stale/running/down。

### 失败自动补抓

- `SCHEDULED_SCRAPE_RETRY_FAILED_TODAY=true`
- 后台 scheduled today 首轮失败/超时的酒店，会自动补抓一次。
- 实测 Batch #55 中两家首轮超时，二次补抓成功，最终 6/6。

### 兜底价格新鲜度

- `PRICE_FALLBACK_MAX_AGE_HOURS=24`
- 超过 24 小时的历史价格不再作为“最近有效价格”兜底。
- 过旧价格会显示缺价，避免误导。

### 缺价可解释

- 日历 API 返回：
  - `task_status`
  - `task_error_message`
- 插件今日价格表会显示“抓取超时/登录失效/缺少URL/抓取失败”。
- 热力图 tooltip 也显示缺价原因。
- 日报会列出 `missing_competitors` 和“缺价酒店”段落。

### 数据污染防护

- SQLite 可能复用 `scrape_runs.id`。
- 新批次创建后会清理同 batch_id 的旧 `price_records` / `scrape_task_results`，避免旧明细混入新批次。
- 已清理线上 Batch #55 中混入的 6 条旧 task 和 48 条旧 price。

---

## 6. 重要文件

```text
backend/app/services/scrape_manager.py      抓取编排、失败补抓、批次清理
backend/app/services/price_service.py       日历查询、兜底窗口、任务状态合并
backend/app/services/report_service.py      日报、缺价酒店展示
backend/app/services/scheduler.py           APScheduler、后台事件
backend/app/routers/scheduler.py            调度健康状态
backend/app/routers/scrape.py               抓取触发、配置、任务明细
backend/app/services/scraper/ctrip.py       携程真实抓取器

extension/components/ComparisonTable.vue    今日价格对比表
extension/components/CalendarHeatmap.vue    未来价格热力图
extension/components/OperationsPanel.vue    配置/运行状态/诊断面板
extension/entrypoints/popup/App.vue         插件主界面
extension/types/index.ts                    前端类型

docs/OPTIMIZATION_LOG.md                    优化日志
docs/TESTING.md                             测试说明
docs/PLAN.md                                实施计划
docs/PRD.md                                 产品需求
```

---

## 7. 当前已知问题和建议优先级

### P0：不要大改，先观察下一轮自动抓取

当前后台已恢复稳定，最近多轮 6/6。建议 Claude Code 不要马上重构抓取器，先观察：

```text
11:00 / 14:00 / 17:00 自动抓取是否继续 6/6
是否出现连续 warning
是否出现登录失效
```

### P1：任务明细列表展示最终口径

当前 `/scrape/runs/{batch_id}/tasks` 会同时展示首轮 failed 和 retry_success。  
这是审计上正确的，但 UI 的“最近失败”如果只取第一条非 success，可能会把已补抓成功的酒店仍显示为失败。

建议下一步：

- 在前端 `OperationsPanel.vue` 中，把同一 `hotel_id + platform` 的任务按最终结果聚合。
- 如果有 `retry_success`，则该酒店最终显示成功，但保留首轮超时作为历史说明。

### P1：截图/证据入口优化

已保存 evidence，但用户在巡检页缺价时只能看到原因文字。后续可加：

- 缺价行“查看证据”按钮
- 跳转或展开对应 task evidence

### P2：企业微信

当前企业微信仍然暂缓：

```text
REPORT_PUSH_ENABLED=false
WECOM_WEBHOOK_URL 未配置
```

不要在没有用户 webhook / 企业微信配置前启用推送。

### P2：去哪儿/同程

代码有骨架，但真实抓取未进入验收。不要贸然启用：

```text
ENABLED_PLATFORMS=ctrip
REAL_PLATFORMS=ctrip
```

---

## 8. 给 Claude Code 的启动 Prompt

可以直接复制下面这段给 Claude Code：

```text
我正在开发 hotel-price-monitor 酒店竞对价格监控系统。请打开项目目录：

/Users/zhangshuaichi/Desktop/work/hotel-price-monitor

请先阅读：
1. docs/PRD.md
2. docs/PLAN.md
3. docs/TESTING.md
4. docs/OPTIMIZATION_LOG.md
5. docs/HANDOFF_TO_CLAUDE.md

当前状态：
- 后端 FastAPI + SQLite + APScheduler 已部署到阿里云。
- 浏览器插件 WXT + Vue 3 已构建，Chrome 加载目录是 extension-chrome-mv3。
- 当前只启用携程真实抓取。
- 当前有效门店组：我方酒店 id=7，竞对 ids=8,9,10,11,12。
- 后台定时每天 08/11/14/17/20/23 抓今日价。
- 最新线上批次 Batch #61，scheduled，6/6 success，耗时 402.6s。
- 后台健康 ok。
- 后端测试当前基线是 49 passed。

重要约束：
- 不要大批量重构。
- 不要贸然启用去哪儿/同程。
- 不要启用企业微信推送，除非用户提供 webhook 或明确要求。
- 不要改动阿里云数据库文件。
- 每次小改后必须跑：
  cd backend && python3 -m pytest tests -q
  cd extension && VITE_API_BASE=http://8.163.49.150/hotel-price-monitor/api/v1 npm run build
- 如果改后端，需要同步 backend/app 到阿里云并重启 hotel-price-monitor。
- 如果改插件，需要同步 extension/.output/chrome-mv3 到 extension-chrome-mv3。

下一步建议：
优先处理“任务明细/运行状态的最终口径”。现在后台 scheduled today 有自动补抓，可能出现同一酒店首轮 failed、二轮 retry_success。审计明细可以保留两条，但配置页/最近失败提示应该按最终结果聚合，不要把已补抓成功的酒店继续显示成失败。

请先确认线上状态，再制定一个小步修改方案并执行。
```

---

## 9. 最近验证快照

```text
日期：2026-07-03
后端测试：49 passed
插件构建：通过
线上 health：ok
调度健康：ok
最新批次：#61
最新批次结果：6/6 success
当前日历：本轮 6，兜底 0，缺价 0
```

