/**
 * api/inventory.js — Vercel Serverless Functions 格式
 * 
 * Vercel 会自动注入 process.env
 * 前端通过 /api/inventory, /api/inbound 等调用
 */

const axios = require('axios');

const BOT_TOKEN = process.env.FEISHU_BOT_TOKEN;
const FEISHU_BASE_URL = 'https://open.feishu.cn/open-apis/bitable/v1/apps';

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
  // CORS
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
      return res.status(200).json({ ok: true, tokenSet: !!BOT_TOKEN });
    }
    return res.status(404).json({ error: 'not found' });
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
};
