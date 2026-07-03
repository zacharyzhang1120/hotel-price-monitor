# 酒店竞对价格监控系统

这是当前可测试的 MVP 版本：后端支持 Mock 数据闭环，也已接入携程真实抓取。当前种子数据为 1 家我方酒店 + 5 家海口竞对，携程单平台可用于真实抓取测试。企业微信推送暂不启用。

## 一键准备

```bash
./scripts/prepare_mvp.sh
```

该脚本会：

- 安装后端依赖
- 安装真实抓取所需的 Playwright Chromium
- 初始化 1 家我方酒店 + 5 家竞对
- 安装插件依赖
- 构建一个非隐藏的 Chrome 插件目录：`extension-chrome-mv3`

## 启动后端

```bash
./scripts/start_backend.sh
```

后端地址：

```text
http://127.0.0.1:8080
```

后端启动时会自动读取 `backend/.env`。可以从示例文件复制一份后调整：

```bash
cp backend/.env.example backend/.env
```

## 启动完整开发环境

如果想同时启动后端和插件开发服务：

```bash
./scripts/start_all_dev.sh
```

插件开发目录会生成在：

```text
extension/.output/chrome-mv3-dev
```

## 冒烟测试

后端启动后，在另一个终端运行：

```bash
python3 scripts/smoke_test.py
```

通过后会看到：

```text
Smoke test passed.
```

如果要检查阿里云服务器：

```bash
BASE_URL=http://服务器公网IP:8080 python3 scripts/smoke_test.py
```

## 构建插件

本地测试默认连接 `localhost:8080`：

```bash
./scripts/build_extension.sh
```

如果后端部署到服务器，构建插件时传入服务器 API 地址：

```bash
./scripts/build_extension.sh http://服务器公网IP:8080/api/v1
```

输出目录：

```text
extension-chrome-mv3
```

## 阿里云部署

部署说明见：

```text
docs/DEPLOY_ALIYUN.md
```

有服务器 SSH 权限后，可以在本机项目根目录执行：

```bash
DEPLOY_HOST=服务器公网IP ./scripts/deploy_aliyun.sh
```

部署后检查：

```bash
./scripts/server_health_check.sh http://服务器公网IP:8080
```

当前阿里云实例已通过 nginx 暴露为：

```text
http://8.163.49.150/hotel-price-monitor
```

对应插件 API 地址：

```text
http://8.163.49.150/hotel-price-monitor/api/v1
```

## 导出诊断包

测试时如果遇到问题，可以导出当前本地状态：

```bash
python3 scripts/export_diagnostics.py
```

输出目录在 `diagnostics/`，包含酒店映射、抓取准备状态、调度状态、最近批次、最近日报和备份列表。

## 更新真实 OTA 链接

后续要试真实抓取时，可以先在插件右上角点击“配置”，选择酒店和平台，填入 OTA 酒店详情页 URL 与默认房型，点击“保存”。“探测”默认使用 Mock 模式验证链路；切换为“真实”后会访问 OTA 页面做单 URL 验证。

也可以用工具更新某个酒店的平台链接：

```bash
cd backend
python3 scripts/list_mappings.py

python3 scripts/update_platform_mapping.py \
  --hotel 亚朵 \
  --platform ctrip \
  --url 'https://hotels.ctrip.com/hotels/detail/?cityId=42&hotelId=真实酒店ID' \
  --room 豪华大床房
```

也可以通过后端 API 更新某家酒店的平台链接：

```bash
curl -X PUT http://127.0.0.1:8080/api/v1/hotels/1/platforms/ctrip \
  -H "Content-Type: application/json" \
  -d '{"hotel_url":"https://hotels.ctrip.com/hotels/detail/?cityId=42&hotelId=真实酒店ID","default_room_name":"豪华大床房"}'
```

支持平台：

- `ctrip`
- `qunar`
- `tongcheng`

正式写入数据库前，也可以先只探测一个真实链接：

```bash
cd backend
python3 scripts/probe_scraper.py \
  --platform ctrip \
  --url 'https://hotels.ctrip.com/hotels/detail/?cityId=42&hotelId=真实酒店ID' \
  --date 2026-06-25 \
  --room 豪华大床房
```

或通过 API 探测。`mode=mock` 只验证链路，`mode=real` 会访问真实 OTA：

```bash
curl -X POST http://127.0.0.1:8080/api/v1/scrape/probe \
  -H "Content-Type: application/json" \
  -d '{"platform":"ctrip","hotel_url":"https://hotels.ctrip.com/hotels/detail/?cityId=42&hotelId=真实酒店ID","check_in_date":"2026-06-26","room_name":"豪华大床房","mode":"real"}'
```

然后用 mixed 模式启用某个平台真实抓取：

```bash
SCRAPER_MODE=mixed REAL_PLATFORMS=ctrip ./scripts/start_backend.sh
```

定时抓取默认关闭。需要测试时可以这样启动：

```bash
SCHEDULER_ENABLED=true SCRAPE_SCHEDULE_HOURS=12,18,22 ./scripts/start_backend.sh
```

## 加载 Chrome 插件

1. 打开 Chrome 扩展管理页：`chrome://extensions`
2. 打开“开发者模式”
3. 点击“加载已解压的扩展程序”
4. 选择项目下的非隐藏目录：

```text
extension-chrome-mv3
```

也可以加载开发目录：

```text
extension/.output/chrome-mv3-dev
```

`.output` 是隐藏目录，Finder 里需要按 `Command + Shift + .` 才能看到。

## 当前测试范围

已可测试：

- 酒店与平台映射
- 插件内新增/编辑酒店档案，包括名称、我方/竞对身份；误建且没有价格记录的酒店可安全删除
- 插件内维护平台 URL、默认房型，并进行 Mock/真实单链接探测
- 插件内查看 Mock/真实抓取准备状态、定时状态、最近备份，并手动创建数据库备份
- 插件内复制诊断摘要，便于测试时反馈问题
- 手动刷新生成新批次
- 当前门店下的今日 + 未来 7 天价格巡检
- 当日竞对价格对比
- 操作菜单中进入配置、运营判断、复制日报和立即刷新
- 企业微信友好的文本日报 API
- 可选企业微信机器人推送通道
- 数据库备份和定时调度开关
- 手动备份与备份列表 API
- 定时任务状态 API，并可查看已注册任务数量和下次执行时间
- 抓取准备状态 API：`GET /api/v1/scrape/readiness`

暂未承诺稳定：

- 去哪儿、同程真实抓取仍需逐个平台验证；当前可测真实抓取重点是携程。携程支持 `/hotel/酒店ID.html` 和 `/hotels/detail/?hotelId=酒店ID` 两种详情页链接。
