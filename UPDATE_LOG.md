# UPDATE_LOG.md — 合盛钮扣厂 出入库数据看板

## 数据更新记录

每次数据刷新时记录关键指标，供对比分析使用。

> 数据来源：飞书 Base「出入库管理（先进先出成本核算）」
> 代理服务：`server.js`（`http://localhost:18792`）

---

### 字段说明

| 指标 | 说明 |
|------|------|
| 总SKU数 | 库存信息表全部商品记录数 |
| 有库存SKU | 当前总库存 > 0 的商品数 |
| 无库存SKU | 当前总库存 = 0 的商品数（需补货） |
| 库存总金额 | 库存信息表「库存金额」字段求和 |
| 高频出库物料 | 出库记录表按商品名称统计出现次数，TOP 10 |
| 批次老化 | 批次明细表商品按最后入库日期距今天数，标红 ≥ 30 天 |

---

### 部署说明

**本地开发**
```bash
cd /tmp/hs-inventory-dashboard
export FEISHU_BOT_TOKEN=你的bot_token
npm install
node server.js   # 监听 :18792
# 然后用 http-server 或 LiveServer 打开 index.html
```

**生产部署（推荐 Cloudflare Workers）**
```toml
# wrangler.toml 示例
name = "hs-inventory-proxy"
main = "src/index.js"
compatibility_date = "2024-01-01"

[vars]
FEISHU_BOT_TOKEN = "xxx"   # 通过 Cloudflare Dashboard 设为 secret
```

Workers 代码参考 `server.js` 路由结构，只需替换 `express` 为 Workers KV / fetch 逻辑即可。

**Bot Token 获取**
```bash
npx lark-cli token get --type bot
# 或在飞书开放平台应用后台手动复制
```

---

### 更新历史

| 日期 | 总SKU | 有库存 | 无库存 | 库存总额 | 备注 |
|------|-------|--------|--------|----------|------|
| 2026-05-04 | — | — | — | — | 实时拉取上线，数据以页面显示为准 |
