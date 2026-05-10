/**
 * api/inventory.js — Vercel Serverless Functions
 * 已更新：指向 OPS Base（運營總表）
 */
const axios = require('axios');

const APP_ID = process.env.FEISHU_APP_ID;
const APP_SECRET = process.env.FEISHU_APP_SECRET;
const BASE_APP_TOKEN = 'A6tEbHzUCakECGsX8n8cZgEMnQh'; // OPS Base
const FEISHU_BASE_URL = `https://open.feishu.cn/open-apis/bitable/v1/apps/${BASE_APP_TOKEN}/tables`;

// 產品表 ID
const TABLE_INVENTORY = 'tblspZZr5mWRQdio';  // 货品库存台账
const TABLE_INBOUND   = 'tblXP1nxIQjCqzyT';  // 库存入库管理
const TABLE_OUTBOUND  = 'tblxF2VdPfO3Ma3V';  // 货品出库明细
const TABLE_BATCHES   = 'tblfq6qynqWMI2KU';  // 批次明细表（FIFO）

// 缓存 App Access Token
let _cachedToken = null;
let _tokenExpiresAt = 0;

async function getAppAccessToken() {
  const now = Date.now();
  if (_cachedToken && now < _tokenExpiresAt - 60000) return _cachedToken;
  const resp = await axios.post('https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal', {
    app_id: APP_ID, app_secret: APP_SECRET,
  }, { timeout: 10000 });
  const data = resp.data;
  if (data.code !== 0) throw new Error(`Token error ${data.code}: ${data.msg}`);
  _cachedToken = data.app_access_token;
  _tokenExpiresAt = now + (data.expire || 5000) * 1000;
  return _cachedToken;
}

async function fetchBitableRecords(tableId, params = {}) {
  const token = await getAppAccessToken();
  const records = [];
  let pageToken = '';
  do {
    const query = { page_size: 500, ...params };
    if (pageToken) query.page_token = pageToken;
    const resp = await axios.get(`${FEISHU_BASE_URL}/${tableId}/records`, {
      headers: { Authorization: `Bearer ${token}` },
      params: query, timeout: 30000,
    });
    const data = resp.data;
    if (data.code !== 0) throw new Error(`Feishu API error ${data.code}: ${data.msg}`);
    records.push(...(data.data?.items || []));
    pageToken = data.data?.page_token;
  } while (pageToken);
  return records;
}

function flatText(val) {
  if (!val) return '';
  if (typeof val === 'string') return val.trim();
  if (Array.isArray(val)) return val.map(v => typeof v === 'object' ? v.text || '' : v).join(' ').trim();
  if (typeof val === 'object' && val.text) return val.text.trim();
  return String(val);
}

function flatNum(val) {
  if (!val && val !== 0) return 0;
  if (typeof val === 'number') return val;
  const s = String(val).replace(/[¥,，\s]/g, '');
  return parseFloat(s) || 0;
}

module.exports = async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.status(200).end();

  const path = req.url || '';
  try {
    if (path.startsWith('/api/inventory')) {
      const records = await fetchBitableRecords(TABLE_INVENTORY);
      const items = records.map(r => ({
        id: r.record_id,
        name: flatText(r.fields?.['货品名称']),
        spec: flatText(r.fields?.['规格型号']),
        unit: '',
        stock: flatNum(r.fields?.['当前库存']),
        cost: flatNum(r.fields?.['库存总价值']),
        dept: flatText(r.fields?.['所属部门']),
      }));
      return res.status(200).json({ items });
    }
    if (path.startsWith('/api/inbound')) {
      const records = await fetchBitableRecords(TABLE_INBOUND);
      const items = records.map(r => ({
        id: r.record_id,
        name: flatText(r.fields?.['货品名称']),
        spec: flatText(r.fields?.['规格型号']),
        qty: flatNum(r.fields?.['入库数量']),
        price: flatNum(r.fields?.['单价']),
        date: flatText(r.fields?.['入库提示']),
      }));
      return res.status(200).json({ items });
    }
    if (path.startsWith('/api/outbound')) {
      const records = await fetchBitableRecords(TABLE_OUTBOUND);
      const items = records.map(r => ({
        id: r.record_id,
        name: '',
        spec: '',
        qty: flatNum(r.fields?.['出库数量']),
        date: flatText(r.fields?.['出库时间']),
        dept: flatText(r.fields?.['出库提示']),
      }));
      return res.status(200).json({ items });
    }
    if (path.startsWith('/api/batches')) {
      if (!TABLE_BATCHES) return res.status(200).json({ items: [], note: '等待批次表ID' });
      const records = await fetchBitableRecords(TABLE_BATCHES);
      const items = records.map(r => ({
        id: r.record_id,
        name: flatText(r.fields?.['商品名称']),
        spec: flatText(r.fields?.['商品规格']),
        initQty: flatNum(r.fields?.['初始数量']),
        allocated: flatNum(r.fields?.['剩余数量']),
        sourceInboundNo: flatText(r.fields?.['入库批次号']),
      }));
      return res.status(200).json({ items });
    }
    if (path === '/api/health') {
      await getAppAccessToken();
      return res.status(200).json({ ok: true });
    }
    return res.status(404).json({ error: 'not found' });
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
};
