/**
 * api/inventory.js — Vercel Serverless Functions 格式
 * 修复：改用 App Access Token（运行时动态获取，避免 Bot Token 2小时过期问题）
 */

const axios = require('axios');

const APP_ID = process.env.FEISHU_APP_ID;
const APP_SECRET = process.env.FEISHU_APP_SECRET;
const BASE_APP_TOKEN = 'Pe1CbQuAfaPsOhs4unzczHgQnVe';
const FEISHU_BASE_URL = `https://open.feishu.cn/open-apis/bitable/v1/apps/${BASE_APP_TOKEN}/tables';

// 缓存 App Access Token（有效期约 5000 秒）
let _cachedToken = null;
let _tokenExpiresAt = 0;

async function getAppAccessToken() {
  const now = Date.now();
  if (_cachedToken && now < _tokenExpiresAt - 60000) {
    return _cachedToken;
  }
  const resp = await axios.post('https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal', {
    app_id: APP_ID,
    app_secret: APP_SECRET,
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
  const s = String(val).replace(/[¥,，\s]/g, '').replace(/,/g, '');
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
      const records = await fetchBitableRecords('tblhqfIppdvtuqd0');
      const items = records.map(r => ({
        id: r.record_id,
        name: flatText(r.fields?.['商品名称']),
        spec: flatText(r.fields?.['规格型号']),
        unit: flatText(r.fields?.['单位']),
        stock: flatNum(r.fields?.['当前总库存']),
        cost: flatNum(r.fields?.['库存金额']),
        dept: flatText(r.fields?.['归属部门']),
      }));
      return res.status(200).json({ items });
    }
    if (path.startsWith('/api/inbound')) {
      const records = await fetchBitableRecords('tblds51GEmG1TqtL');
      const items = records.map(r => ({
        id: r.record_id,
        inboundNo: flatText(r.fields?.['入库单号']),
        name: flatText(r.fields?.['商品名称']),
        spec: flatText(r.fields?.['商品规格']),
        qty: flatNum(r.fields?.['入库数量']),
        price: flatNum(r.fields?.['入库单价']),
        date: flatText(r.fields?.['入库日期']),
      }));
      return res.status(200).json({ items });
    }
    if (path.startsWith('/api/outbound')) {
      const records = await fetchBitableRecords('tblSR30YvhkGluOx');
      const items = records.map(r => ({
        id: r.record_id,
        outboundNo: flatText(r.fields?.['出库单号']),
        name: flatText(r.fields?.['商品名称']),
        spec: flatText(r.fields?.['商品规格']),
        qty: flatNum(r.fields?.['申请出库数']),
        date: flatText(r.fields?.['出库日期']),
        dept: flatText(r.fields?.['领用部门']),
      }));
      return res.status(200).json({ items });
    }
    if (path.startsWith('/api/batches')) {
      const records = await fetchBitableRecords('tblol79pK8WIRzLH');
      const items = records.map(r => ({
        id: r.record_id,
        name: flatText(r.fields?.['商品名称']),
        spec: flatText(r.fields?.['商品规格']),
        initQty: flatNum(r.fields?.['初始数量']),
        allocated: flatNum(r.fields?.['已分配数量']),
        sourceInboundNo: flatText(r.fields?.['来源入库单']),
      }));
      return res.status(200).json({ items });
    }
    if (path === '/api/health') {
      const token = await getAppAccessToken();
      return res.status(200).json({ ok: true, tokenOk: true });
    }
    return res.status(404).json({ error: 'not found' });
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
};
