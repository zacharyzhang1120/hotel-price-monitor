# 酒店竞对价格监控后端

## 本地启动

推荐在项目根目录使用启动脚本：

```bash
./scripts/start_backend.sh
```

启动脚本会自动读取 `backend/.env`，可从 `backend/.env.example` 复制。`HOST` 和 `PORT` 默认是 `127.0.0.1:8080`。

如需手动启动：

```bash
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
python3 scripts/seed_hotels.py
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

## P0 Mock 模式

默认使用 MockScraper，不访问 OTA 网站：

```bash
SCRAPER_MODE=mock python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

手动触发抓取：

```bash
curl -X POST http://127.0.0.1:8080/api/v1/scrape/trigger
curl http://127.0.0.1:8080/api/v1/scrape/readiness
curl http://127.0.0.1:8080/api/v1/scrape/runs
curl http://127.0.0.1:8080/api/v1/scrape/runs/批次ID/tasks
```

维护酒店和平台链接：

```bash
curl http://127.0.0.1:8080/api/v1/hotels
curl -X PUT http://127.0.0.1:8080/api/v1/hotels/1/platforms/ctrip \
  -H "Content-Type: application/json" \
  -d '{"hotel_url":"https://hotels.ctrip.com/hotels/detail/?cityId=42&hotelId=真实酒店ID","default_room_name":"豪华大床房"}'
```

## P1 平台切换

抓取模式：

- `SCRAPER_MODE=mock`：全部平台使用 MockScraper
- `SCRAPER_MODE=real`：全部平台要求真实抓取器已实现，否则批次失败
- `SCRAPER_MODE=mixed`：`REAL_PLATFORMS` 中的平台使用真实抓取器，其余平台继续 Mock

示例：

```bash
SCRAPER_MODE=mixed REAL_PLATFORMS=ctrip python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

当前真实抓取器文件已预留：

- `app/services/scraper/ctrip.py`
- `app/services/scraper/qunar.py`
- `app/services/scraper/tongcheng.py`

实现某个平台后，在 `registry.py` 中注册对应 factory 即可接入。

## 真实抓取试运行

携程、去哪儿、同程真实抓取器已接入注册表，但需要真实酒店 URL 和 Playwright 浏览器运行环境：

```bash
python3 -m playwright install chromium
python3 scripts/list_mappings.py
python3 scripts/probe_scraper.py --platform ctrip --url 'https://hotels.ctrip.com/hotels/detail/?cityId=42&hotelId=真实酒店ID'
curl -X POST http://127.0.0.1:8080/api/v1/scrape/probe \
  -H "Content-Type: application/json" \
  -d '{"platform":"ctrip","hotel_url":"https://hotels.ctrip.com/hotels/detail/?cityId=42&hotelId=真实酒店ID","check_in_date":"2026-06-26","mode":"real"}'
SCRAPER_MODE=mixed REAL_PLATFORMS=ctrip python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

多个平台可用逗号分隔：

```bash
SCRAPER_MODE=mixed REAL_PLATFORMS=ctrip,qunar,tongcheng python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

真实抓取准备状态：

```bash
curl http://127.0.0.1:8080/api/v1/scrape/readiness
```

其中 `ready_for_mock=true` 表示 MVP 测试数据链路已具备条件；`ready_for_real=true` 表示当前启用的真实平台 URL 已配置完整，可以先做单链接探测，再做批量抓取。

`readiness` 会把明显不能用于真实抓取的 URL 放到 `invalid_real_urls`，例如去哪儿首页 `https://hotel.qunar.com/`。真实抓取前应把它们替换为对应酒店详情页。

注意：

- `scripts/seed_data.json` 当前已包含 6 家海口酒店的携程真实详情页 URL；替换城市或门店时需要更新为对应酒店详情页。
- 携程真实抓取器会动态读取起价房型和价格；单日期超时或无可靠房价会记录为空值，登录失效会中断并提示重新登录。
- 真实抓取器默认每个页面等待 2-5 秒，可通过 `SCRAPE_DELAY_MIN_MS` / `SCRAPE_DELAY_MAX_MS` 调整。
- 页面结构和反爬策略可能变化，抓取失败会记录到 `scrape_runs.error_summary`，不会影响未启用真实抓取的平台继续使用 Mock。

## P2 定时调度与备份

默认不启动定时任务。需要启用时：

```bash
SCHEDULER_ENABLED=true SCRAPE_SCHEDULE_HOURS=12,18,22 python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

定时任务：

- 每天 12:00、18:00、22:00 自动抓取
- 每天 03:00 备份 SQLite 数据库
- 同一时间只允许一个抓取批次运行

手动备份：

```bash
curl -X POST http://127.0.0.1:8080/api/v1/backups/create
curl http://127.0.0.1:8080/api/v1/backups
```

备份文件保存到项目根目录的 `data/backups/`，默认保留最近 30 份。

查看调度状态：

```bash
curl http://127.0.0.1:8080/api/v1/scheduler/status
```

## 可选企业微信推送

默认不推送，只生成日报文本。配置企业微信机器人 webhook 后可启用：

```bash
REPORT_PUSH_ENABLED=true \
WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx" \
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

推送内容复用 `ReportService` 的 `wechat_text` 格式。
