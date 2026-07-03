# 阿里云部署说明

> 企业微信推送暂不启用，部署后只运行后端抓取、定时任务、备份和插件 API。

## 1. 服务器要求

- Ubuntu 22.04 / 24.04
- 2 核 2G 起步，建议 2 核 4G
- 安全组放行 TCP `8080`
- 能通过 SSH 登录

## 2. 一键部署

在本机项目根目录执行：

```bash
DEPLOY_HOST=服务器公网IP ./scripts/deploy_aliyun.sh
```

如果不是 root 用户：

```bash
DEPLOY_HOST=服务器公网IP DEPLOY_USER=ubuntu ./scripts/deploy_aliyun.sh
```

脚本会做这些事：

- 同步项目代码到 `/opt/hotel-price-monitor`
- 创建 Python 虚拟环境
- 安装后端依赖和 Playwright Chromium
- 生成服务器 `.env`
- 注册并启动 `hotel-price-monitor` systemd 服务

## 3. 检查后端

```bash
curl http://服务器公网IP:8080/health
curl http://服务器公网IP:8080/api/v1/scrape/readiness
```

返回 `{"status":"ok"}` 表示后端已启动。

如果安全组不开放 `8080`，可以通过 nginx 路径代理访问。本次部署使用：

```bash
curl http://8.163.49.150/hotel-price-monitor/health
curl http://8.163.49.150/hotel-price-monitor/api/v1/scrape/readiness
```

## 4. 构建连接服务器的插件

后端部署完成后，在本机重新构建插件：

```bash
./scripts/build_extension.sh http://服务器公网IP:8080/api/v1
```

本次部署的插件构建地址是：

```bash
./scripts/build_extension.sh http://8.163.49.150/hotel-price-monitor/api/v1
```

然后在 Chrome 扩展管理页重新加载：

```text
/Users/zhangshuaichi/Desktop/work/hotel-price-monitor/extension-chrome-mv3
```

## 5. 常用服务器命令

```bash
ssh root@服务器公网IP
systemctl status hotel-price-monitor
journalctl -u hotel-price-monitor -f
systemctl restart hotel-price-monitor
```

## 6. 重要数据

服务器数据默认在：

```text
/opt/hotel-price-monitor/data/hotel_prices.db
/opt/hotel-price-monitor/data/ctrip_state.json
/opt/hotel-price-monitor/data/backups/
```

如果携程登录失效，需要重新生成 `ctrip_state.json`，再重启服务。

## 7. 当前生产配置

服务器默认配置文件：

```text
/opt/hotel-price-monitor/backend/.env
```

当前建议：

```bash
SCRAPER_MODE=real
ENABLED_PLATFORMS=ctrip
REAL_PLATFORMS=ctrip
FUTURE_DAYS=1
SCRAPE_CONCURRENCY=1
SCRAPE_MAPPING_TIMEOUT=300
SCRAPE_PROBE_TIMEOUT=90
SCRAPE_GOTO_WAIT_UNTIL=domcontentloaded
SCHEDULER_ENABLED=true
SCRAPE_SCHEDULE_HOURS=8,11,14,17,20,23
SCHEDULED_SCRAPE_SCOPE=today
REPORT_PUSH_ENABLED=false
```

当前携程真实抓取已跑通 6/6，可开启 `SCHEDULER_ENABLED=true`。建议后台定时先使用 `SCHEDULED_SCRAPE_SCOPE=today`，每 3 小时更新今日价；远期价格仍通过插件里的“补抓远期”手动执行，避免后台任务过重。
