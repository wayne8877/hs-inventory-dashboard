/**
 * server.js — 合盛物料看板 · 飞书 Base 数据代理
 *
 * 用法:
 *   export FEISHU_BOT_TOKEN=your_bot_token_here
 *   node server.js
 *
 * 端口: 18792
 * 前端 dev server 指向 http://localhost:18792
 */

const express = require('express');
const axios = require('axios');

const app = express();
const PORT = 18792;

const BOT_TOKEN = process.env.FEISHU_BOT_TOKEN;
const FEISHU_BASE_URL = 'https://open.feishu.cn/open-apis/bitable/v1/apps';

// 代理鉴权中间件（CORS）
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Headers', 'Origin, X-Requested-With, Content-Type, Accept');
  next();
});

// 通用飞书请求封装
async function fetchBitableRecords(tableId, params = {}) {
  const records = [];
  let pageToken = '';
  do {
    const query = { ...params, page_size: 500 };
    if (pageToken) query.page_token = pageToken;
    const resp = await axios.get(`${FEISHU_BASE_URL}/${tableId}/records`, {
      headers: { Authorization: `Bearer ${BOT_TOKEN}` },
      params: query,
      timeout: 30000,
    });
    const data = resp.data;
    if (data.code !== 0) throw new Error(`Feishu API error ${data.code}: ${data.msg}`);
    records.push(...(data.data?.items || []));
    pageToken = data.data?.page_token;
  } while (pageToken);
  return records;
}

// 提取多行文本字段（飞书返回可能是数组或字符串）
function flatText(val) {
  if (!val) return '';
  if (typeof val === 'string') return val.trim();
  if (Array.isArray(val)) return val.map(v => typeof v === 'object' ? v.text || '' : v).join(' ').trim();
  if (typeof val === 'object' && val.text) return val.text.trim();
  return String(val);
}

// 提取数字（库存、金额）
function flatNum(val) {
  if (!val && val !== 0) return 0;
  if (typeof val === 'number') return val;
  const s = String(val).replace(/[¥,，\s]/g, '').replace(/,/g, '');
  return parseFloat(s) || 0;
}

// ========== API Routes ==========

// GET /api/inventory — 库存信息表
app.get('/api/inventory', async (req, res) => {
  try {
    const records = await fetchBitableRecords('tblhqfIppdvtuqd0');
    const items = records.map(r => {
      const f = r.fields || {};
      return {
        id: r.record_id,
        name: flatText(f['商品名称']),
        spec: flatText(f['规格型号']),
        unit: flatText(f['单位']),
        stock: flatNum(f['当前总库存']),
        cost: flatNum(f['库存金额']),
        dept: flatText(f['归属部门']),
      };
    });
    res.json({ items });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// GET /api/inbound — 入库记录表
app.get('/api/inbound', async (req, res) => {
  try {
    const records = await fetchBitableRecords('tblds51GEmG1TqtL');
    const items = records.map(r => {
      const f = r.fields || {};
      return {
        id: r.record_id,
        inboundNo: flatText(f['入库单号']),
        name: flatText(f['商品名称']),
        spec: flatText(f['商品规格']),
        qty: flatNum(f['入库数量']),
        price: flatNum(f['入库单价']),
        date: flatText(f['入库日期']),
      };
    });
    res.json({ items });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// GET /api/outbound — 出库记录表
app.get('/api/outbound', async (req, res) => {
  try {
    const records = await fetchBitableRecords('tblSR30YvhkGluOx');
    const items = records.map(r => {
      const f = r.fields || {};
      return {
        id: r.record_id,
        outboundNo: flatText(f['出库单号']),
        name: flatText(f['商品名称']),
        spec: flatText(f['商品规格']),
        qty: flatNum(f['申请出库数']),
        date: flatText(f['出库日期']),
        dept: flatText(f['领用部门']),
      };
    });
    res.json({ items });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// GET /api/batches — 先进先出批次明细表
app.get('/api/batches', async (req, res) => {
  try {
    const records = await fetchBitableRecords('tblol79pK8WIRzLH');
    const items = records.map(r => {
      const f = r.fields || {};
      return {
        id: r.record_id,
        name: flatText(f['商品名称']),
        spec: flatText(f['商品规格']),
        initQty: flatNum(f['初始数量']),
        allocated: flatNum(f['已分配数量']),
        sourceInboundNo: flatText(f['来源入库单']),
      };
    });
    res.json({ items });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 健康检查
app.get('/api/health', (req, res) => {
  res.json({ ok: true, tokenSet: !!BOT_TOKEN });
});

app.listen(PORT, () => {
  console.log(`[${new Date().toISOString()}] 合盛物料代理已启动 :${PORT}`);
  console.log(`Bot token: ${BOT_TOKEN ? '✓ 已设置' : '✗ 未设置 (请 export FEISHU_BOT_TOKEN=...)'}`);
});
