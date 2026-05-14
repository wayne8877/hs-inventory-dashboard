#!/usr/bin/env python3
"""构建合盛库存仪表盘 — 从飞书API拉数据，生成静态HTML，零外部依赖"""
import subprocess, json, datetime, os
from collections import defaultdict

# ── 配置 ──
OPS_BASE = "A6tEbHzUCakECGsX8n8cZgEMnQh"
MASTER_TBL = "tblspZZr5mWRQdio"
INBOUND_TBL = "tblXP1nxIQjCqzyT"
APP_ID = "cli_a94bdf0fc3b89bb7"
APP_SECRET = "p8QsSAq2zb8dVazJkE487gXkFVQx3Mr3"

def get_token():
    r = subprocess.run(["curl", "-s", "--max-time", "10",
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        "-H", "Content-Type: application/json",
        "-d", json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET})],
        capture_output=True, text=True)
    return json.loads(r.stdout).get("tenant_access_token", "")

def fetch_all(base, table):
    token = get_token()
    records = []
    pt = None
    while True:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base}/tables/{table}/records?page_size=500"
        if pt: url += f"&page_token={pt}"
        r = subprocess.run(["curl", "-s", "--max-time", "20", url,
            "-H", f"Authorization: Bearer {token}"], capture_output=True, text=True)
        data = json.loads(r.stdout)
        if data.get("code") != 0:
            print(f"API错误: {data.get('msg','')}")
            break
        records.extend(data.get("data", {}).get("items", []))
        if not data["data"].get("has_more"): break
        pt = data["data"]["page_token"]
    return records

def safe_num(v):
    if v is None: return 0
    if isinstance(v, (int, float)): return v
    s = str(v).strip().replace("¥","").replace(",","")
    try: return float(s)
    except: return 0

def safe_str(v):
    if not v: return ""
    if isinstance(v, list): return " ".join(str(x) for x in v)
    return str(v).strip()

def short(s, n=18):
    s = str(s).strip()
    return s[:n] + "…" if len(s) > n else s

# ── 1. 拉数据 ──
print("拉取数据...")
items = fetch_all(OPS_BASE, MASTER_TBL)
inbound_recs = fetch_all(OPS_BASE, INBOUND_TBL)
OUTBOUND_TBL = "tblxF2VdPfO3Ma3V"
outbound_recs = fetch_all(OPS_BASE, OUTBOUND_TBL)
print(f"台账 {len(items)} 条, 入库 {len(inbound_recs)} 条, 出库 {len(outbound_recs)} 条")

records = []
for r in items:
    f = r.get("fields", {})
    name = safe_str(f.get("货品名称", ""))
    if not name: continue
    spec = safe_str(f.get("规格型号", ""))
    stock = int(safe_num(f.get("当前库存", 0)))
    cost = round(safe_num(f.get("库存总价值", 0)))
    dept = safe_str(f.get("所属部门", ""))
    mgmt_type = safe_str(f.get("管理类型", ""))
    records.append({"name": name, "spec": spec, "stock": stock, "cost": cost, "dept": dept, "type": mgmt_type})

total = len(records)
in_stock = sum(1 for r in records if r["stock"] > 0)
out_stock = sum(1 for r in records if r["stock"] == 0)
total_val = round(sum(r["cost"] for r in records))

# 部门统计
dept_data = defaultdict(lambda: {"count": 0, "val": 0, "items": []})
for r in records:
    d = r["dept"] or "未知"
    dept_data[d]["count"] += 1
    dept_data[d]["val"] += r["cost"]
    dept_data[d]["items"].append(r)

# 出入库处理
in_rows = []
for r in inbound_recs:
    f = r.get("fields", {})
    name = safe_str(f.get("货品名称", ""))
    if not name: continue
    qty = safe_num(f.get("入库数量", 0))
    dept = safe_str(f.get("部门", ""))
    dt = f.get("入库日期")
    date_str = ""
    if dt and isinstance(dt, (int, float)):
        d = datetime.datetime.fromtimestamp(dt / 1000)
        date_str = f"{d.month:02d}-{d.day:02d}"
    in_rows.append({"name": name, "qty": qty, "dept": dept, "date": date_str})
in_rows.sort(key=lambda r: r["date"], reverse=True)

out_rows = []
for r in outbound_recs:
    f = r.get("fields", {})
    name = safe_str(f.get("货品名称", ""))
    if not name: continue
    qty = safe_num(f.get("出库数量", 0))
    dept = safe_str(f.get("部门", ""))
    dt = f.get("出库日期")
    date_str = ""
    if dt and isinstance(dt, (int, float)):
        d = datetime.datetime.fromtimestamp(dt / 1000)
        date_str = f"{d.month:02d}-{d.day:02d}"
    out_rows.append({"name": name, "qty": qty, "dept": dept, "date": date_str})
out_rows.sort(key=lambda r: r["date"], reverse=True)

# ── 过手件识别（入库≈出库模式检测）──
# 按名称汇总入库/出库总量，找出入库≈出库的物料
in_sum = defaultdict(int)
for r in inbound_recs:
    f = r.get("fields", {})
    name = safe_str(f.get("货品名称", ""))
    if not name: continue
    in_sum[name] += int(safe_num(f.get("入库数量", 0)))
out_sum = defaultdict(int)
for r in outbound_recs:
    f = r.get("fields", {})
    name = safe_str(f.get("货品名称", ""))
    if not name: continue
    out_sum[name] += int(safe_num(f.get("出库数量", 0)))

pass_through_candidates = []
for r in records:
    name = r["name"]
    t_in = in_sum.get(name, 0)
    t_out = out_sum.get(name, 0)
    # 已标过手件的
    if r["type"] == "过手件":
        pass_through_candidates.append({**r, "t_in": t_in, "t_out": t_out, "suggested": False})
    # 未标但入库≈出库（差值≤2）且都有活动的
    elif t_in > 0 and t_out > 0 and abs(t_in - t_out) <= 2:
        pass_through_candidates.append({**r, "t_in": t_in, "t_out": t_out, "suggested": True})
pass_through_candidates.sort(key=lambda x: (0 if x["type"]=="过手件" else 1, -x["t_in"]))

dept_sorted = sorted(dept_data.items(), key=lambda x: x[1]["val"], reverse=True)

# TOP20
top20 = sorted([r for r in records if r["cost"] > 0], key=lambda x: x["cost"], reverse=True)[:20]

# 缺货清单
reorder = [r for r in records if r["stock"] == 0 and len(r["name"]) > 1]

# ── 1.5 拉订单数据 ──
ORDER_TBL = "tblSakoiChynJrw5"
print("拉取订单数据...")
order_records = fetch_all(OPS_BASE, ORDER_TBL)
print(f"共 {len(order_records)} 条群聊记录")

import re as _re
order_re = _re.compile(r'[Hh][Xx]\d+')
g_re = _re.compile(r'(\d+)\s*[Gg]')
BUTTON_TYPES = ["磁钮","彩虹钮","仿贝壳钮","阴阳钮","树脂钮","金属钮","四合扣","工字钮","撞钉","鸡眼","五爪扣"]
PROCESS_STEPS = ["接单","调色","生产","筛胚","车钮","抛光","品检","出货"]
STEP_KW = {
    "接单":["查收","新单","下单"],"调色":["调色","对色","色板"],
    "生产":["生产","做货","做了","大货","直接做货"],"筛胚":["筛胚"],
    "车钮":["车钮","车床"],"抛光":["抛光","抛"],
    "品检":["品检","检验","全检"],"出货":["出货","寄出","交货","寄过来"],
}

all_orders = {}
today_str = datetime.date.today().isoformat()

for rec in order_records:
    f = rec.get("fields",{})
    content = f.get("消息内容","")
    ts_val = f.get("发送时间",0)
    try:
        msg_date = datetime.datetime.fromtimestamp(ts_val/1000)
        date_str = msg_date.strftime("%Y-%m-%d")
    except: date_str = "?"
    
    found = [o.upper() for o in order_re.findall(content)]
    found_g = g_re.findall(content)
    
    for o in found:
        o_up = o.upper()
        if o_up not in all_orders:
            all_orders[o_up] = {"order_no":o_up,"g_count":0,"product_type":"树脂钮","step":"接单","date":date_str,"latest_date":date_str,"client":"恒业","first_date":date_str}
        entry = all_orders[o_up]
        if date_str > entry["latest_date"]: entry["latest_date"] = date_str
        if date_str < entry["first_date"]: entry["first_date"] = date_str
        
        for g in found_g:
            gi = int(g)
            if 1 <= gi <= 50000: entry["g_count"] += gi
        
        for bt in BUTTON_TYPES:
            if bt in content: entry["product_type"] = bt; break
        
        for si,(step,kws) in enumerate(STEP_KW.items()):
            if any(kw in content for kw in kws):
                cs = PROCESS_STEPS.index(entry["step"])
                if si >= cs: entry["step"] = step

# ── 合约图片OCR确凿G数覆盖 ──
import os as _os
_vg_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "verified_g.json")
try:
    with open(_vg_path, 'r', encoding='utf-8') as _f:
        _vg = json.load(_f)
    _vg_orders = _vg.get("orders", {})
    for _oid, _vdata in _vg_orders.items():
        if _oid in all_orders:
            all_orders[_oid]["g_count"] = max(all_orders[_oid]["g_count"], _vdata.get("g_count", 0))
            if _vdata.get("verified_source", "") or _vdata.get("note", ""):
                all_orders[_oid]["verified_source"] = _vdata.get("source", "")
            all_orders[_oid]["verified"] = _vdata.get("verified", True)
        else:
            all_orders[_oid] = {
                "order_no": _oid,
                "g_count": _vdata.get("g_count", 0),
                "product_type": "",
                "step": "接单",
                "latest_date": _vdata.get("contract_date", ""),
                "first_date": _vdata.get("contract_date", ""),
                "verified_source": _vdata.get("source", ""),
                "verified": _vdata.get("verified", True),
                "history": [],
                "senders": set()
            }
except Exception as _e:
    pass

# 订单汇总
today_orders = [o for o in all_orders.values() if o["latest_date"]==today_str]
in_progress = [o for o in all_orders.values() if o["step"]!="出货"]
shipped = [o for o in all_orders.values() if o["step"]=="出货"]
total_g = sum(o["g_count"] for o in all_orders.values())
today_g = sum(o["g_count"] for o in today_orders)
no_g = [o for o in today_orders if o["g_count"]==0]
total_order_count = len(all_orders)

# 月度统计
import collections as _col
month_buckets = _col.defaultdict(lambda: {"count":0,"g":0})
this_month = datetime.date.today().strftime("%Y-%m")
this_year = datetime.date.today().strftime("%Y")
month_orders = 0; month_g = 0
year_orders = 0; year_g = 0
for o in all_orders.values():
    d = o["date"]
    if len(d) >= 7:
        m = d[:7]
        month_buckets[m]["count"] += 1
        month_buckets[m]["g"] += o["g_count"]
        if d.startswith(this_month):
            month_orders += 1; month_g += o["g_count"]
        if d.startswith(this_year):
            year_orders += 1; year_g += o["g_count"]

# 月度排行（最近12个月）
month_rank = sorted(month_buckets.items(), reverse=True)[:12]
month_chart_rows = ""
max_mg = max([m["g"] for _,m in month_rank]) if month_rank else 1
for m,(month_str,md) in enumerate(month_rank):
    mn = md["count"]; mg = md["g"]
    bar_w = mg/max_mg*60 if max_mg else 0
    lbl = month_str[-2:]+"月" if len(month_str)>=7 else month_str
    month_chart_rows += f'<tr><td>{lbl}</td><td class="tr">{mn}单</td><td class="tr">{mg}G</td><td><div style="background:#3D4F6F;height:6px;width:{bar_w}%;border-radius:3px;min-width:3px"></div></td></tr>\n'

# 客户排名
client_g = {}
for o in all_orders.values():
    c = o["client"]
    client_g[c] = client_g.get(c,0) + o["g_count"]
client_rank = sorted(client_g.items(), key=lambda x:-x[1])

# 工序分布（全部在途，非仅今日）
step_counts = {}
for o in in_progress:
    step_counts[o["step"]] = step_counts.get(o["step"],0) + 1

# 上月同比
last_month = (datetime.date.today().replace(day=1) - datetime.timedelta(days=1)).strftime("%Y-%m")
last_md = month_buckets.get(last_month, {"count":0,"g":0})
month_trend = ""
if last_md["g"] > 0 and month_g > 0:
    pct = (month_g - last_md["g"]) / last_md["g"] * 100
    arrow = "↑" if pct > 0 else ("↓" if pct < 0 else "→")
    month_trend = f'<span style="color:{"#27AE60" if pct>=0 else "#C0392B"};font-size:12px">{arrow}{abs(pct):.0f}%</span>'

# 钮扣类型
type_g = {}
for o in all_orders.values():
    t = o["product_type"]
    type_g[t] = type_g.get(t,0) + o["g_count"]
type_rank = sorted(type_g.items(), key=lambda x:-x[1])

# 在途订单行
active_orders = sorted([o for o in all_orders.values() if o["step"]!="出货"],
    key=lambda x: (x["latest_date"],x["order_no"]), reverse=True)[:12]
order_rows = ""
STEP_C = {"接单":"#2980B9","调色":"#8E44AD","生产":"#1ABC9C","筛胚":"#F39C12","车钮":"#B8860B","抛光":"#DAA520","品检":"#E74C3C","出货":"#27AE60"}
now_dt = datetime.date.today()
for o in active_orders:
    sc = STEP_C.get(o["step"],"#888")
    # 滞留天数
    try:
        fd = datetime.date.fromisoformat(o.get("first_date", o["date"]))
        age = (now_dt - fd).days
    except: age = 0
    age_style = "color:#C0392B;font-weight:700" if age > 7 else "color:#8A95A5"
    age_str = f'<span style="{age_style}">{age}天</span>' if age > 0 else "今天"
    # G数显示
    # G数显示
    verified = o.get("verified", True)
    if o["g_count"] > 0:
        vs = o.get("verified_source", "")
        if vs:
            g_str = f'{o["g_count"]}G <span style="color:#27AE60;font-size:9px" title="合约OCR确认">📋</span>'
        else:
            g_str = f'{o["g_count"]}G'
    elif not verified:
        g_str = '<span style="color:#E67E22" title="合约图加密未读">⚠️ 待确认</span>'
    else:
        g_str = '<span style="color:#AAA">未提</span>'
    order_rows += f'<tr><td style="color:{sc};font-weight:700">●</td><td class="td-name">{o["order_no"]}</td><td class="tr">{g_str}</td><td>{o["product_type"][:6]}</td><td><span style="background:{sc};color:#fff;padding:1px 8px;border-radius:10px;font-size:11px">{o["step"]}</span></td><td style="font-size:11px;color:#8A95A5">{o["latest_date"][5:]}</td><td>{age_str}</td></tr>\n'

# 工序管道
pipe_html = ""
for i,step in enumerate(PROCESS_STEPS):
    sc = STEP_C.get(step,"#888")
    cnt = step_counts.get(step,0)
    pipe_html += f'<div style="flex:1;text-align:center"><div style="background:{sc};color:#fff;padding:10px 4px;border-radius:8px;font-size:12px;font-weight:600">{step}</div><div style="font-size:20px;font-weight:700;color:{sc};margin-top:4px">{cnt}</div><div style="font-size:10px;color:#8A95A5">单</div></div>'

# 客户排名行
client_rows = ""
max_g = max([g for _,g in client_rank]) if client_rank else 1
for i,(cname,cg) in enumerate(client_rank[:6]):
    bar_w = cg/max_g*50 if max_g else 0
    client_rows += f'<tr><td>{cname}</td><td class="tr">{sum(1 for o in all_orders.values() if o["client"]==cname)}单</td><td class="tr">{cg}G</td><td><div style="background:{["#3D4F6F","#5B7FA6","#8BAA9E","#C4883A","#B85C5C","#9B7EB5"][i%6]};height:6px;width:{bar_w}%;border-radius:3px;min-width:4px"></div></td></tr>\n'

# 订单KPI — 大卡片（含月度维度）
order_kpi_cards = f"""<div class="okpi"><div class="okpi-icon" style="background:#EBF4FF;color:#2980B9">📋</div><div class="okpi-body"><div class="okpi-num">{total_order_count}</div><div class="okpi-label">全部订单</div></div><div class="okpi-sub">本月{month_orders}单</div></div>
<div class="okpi"><div class="okpi-icon" style="background:#E8F8F0;color:#27AE60">⚖</div><div class="okpi-body"><div class="okpi-num">{total_g}G</div><div class="okpi-label">订单总量 {month_trend}</div></div><div class="okpi-sub">本月{month_g}G</div></div>
<div class="okpi"><div class="okpi-icon" style="background:#FFF3E0;color:#E67E22">📅</div><div class="okpi-body"><div class="okpi-num">{year_orders}</div><div class="okpi-label">{this_year}年</div></div><div class="okpi-sub">{year_g}G</div></div>
<div class="okpi"><div class="okpi-icon" style="background:#FDECEC;color:#C0392B">⚙</div><div class="okpi-body"><div class="okpi-num">{len(in_progress)}</div><div class="okpi-label">进行中</div></div><div class="okpi-sub">{len(shipped)}已出货</div></div>
<div class="okpi"><div class="okpi-icon" style="background:#F3E5F5;color:#8E44AD">🔍</div><div class="okpi-body"><div class="okpi-num">{len(no_g)}</div><div class="okpi-label">待补G数</div></div><div class="okpi-sub">需跟进</div></div>"""

print(f"订单: {total_order_count}个, 今日{len(today_orders)}个, {total_g}G")

# ── 2. 生成HTML ──
now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

# TOP20行
top20_rows = ""
for i, r in enumerate(top20, 1):
    top20_rows += f"""        <tr><td class="td-num">{i}</td><td class="td-name">{short(r['name'], 16)}</td><td>{r['dept']}</td><td class="tr">{r['stock']}</td><td class="tr">¥{r['cost']:,}</td></tr>\n"""

# 缺货行
reorder_rows = ""
for r in reorder[:50]:
    reorder_rows += f"""        <tr><td class="td-name">{short(r['name'], 16)}</td><td>{r['dept']}</td><td><span class="st r">缺货</span></td></tr>\n"""

# 过手件行（移至 fmt_qty 定义后生成）
pass_through_rows = ""

# ── 单位推断：从规格型号提取包装单位和换算系数 ──
import re

def parse_spec(spec, name=""):
    """返回 (display_unit, kg_per_unit, spec_str) 或 None"""
    s = (spec or "").strip()
    if not s:
        return None
    
    su = s.upper()
    
    # 匹配模式：数字+单位/包装容器 (如 "25KG/桶", "25公斤/桶", "32KG/包", "1KG/罐")
    m = re.search(r'(\d+(?:\.\d+)?)\s*(KG|公斤|千克|KGS)\s*[/／](桶|罐|包|瓶|袋|箱|盒|条|卷)', su)
    if m:
        num = float(m.group(1))
        container = m.group(3)
        return (container, num, s)
    
    # 匹配模式：数字+包装容器 不含重量 (如 "500 毫升")
    m = re.search(r'(\d+(?:\.\d+)?)\s*(毫升|ML)\s*[/／]?(桶|罐|瓶)?', su)
    if m:
        num = float(m.group(1))
        container = m.group(3) or "瓶"
        return (container, num / 1000, s)  # ml→L，假设1L≈1kg
    
    # 匹配模式：数字+单位 后面没有明确容器，尝试找容器词
    m = re.search(r'(\d+(?:\.\d+)?)\s*(KG|公斤|千克|KGS|L)\s*(?:[/／])?\s*(桶|罐|包|瓶|袋|箱)?', su)
    if m:
        container = m.group(3) or "份"
        return (container, float(m.group(1)), s)
    
    return None  # 无法解析，用默认 "个"


# 构建名称→显示信息映射
name_to_display = {}  # name -> (container, kg_per_container)
name_to_spec = {}     # name -> spec
for r in records:
    name_to_spec[r["name"]] = r["spec"]
    parsed = parse_spec(r["spec"], r["name"])
    if parsed:
        container, per_unit, spec_str = parsed
        name_to_display[r["name"]] = (container, per_unit)
    else:
        name_to_display[r["name"]] = ("个", 1)  # 默认计数单位


def fmt_qty(qty, container, per_unit):
    """格式化数量显示：从kg换算到包装单位"""
    if container == "个":
        return f"{int(qty)}个"
    n = qty / per_unit
    if n == int(n):
        return f"{int(n)}{container}"
    else:
        return f"{n:.1f}{container}"

def clean_name(name, spec):
    """品名去重：如果规格型号出现在品名末尾，去掉它"""
    if not spec:
        return name
    s = spec.strip()
    n = name.strip()
    # 规格出现在品名末尾 → 去掉
    if n.endswith(s):
        return n[:-len(s)].rstrip()
    # 规格出现在品名中间某处 → 截到规格前
    idx = n.find(s)
    if idx > 0:
        return n[:idx].rstrip()
    return n

# 过手件行（实际生成，fmt_qty 已定义）
for r in pass_through_candidates[:30]:
    tag = '<span class="st g">✓ 已标记</span>' if r['type'] == "过手件" else '<span class="st o">? 建议标记</span>'
    spec = name_to_spec.get(r['name'], '')
    pass_through_rows += f"""        <tr><td class="td-name">{short(clean_name(r['name'], spec), 18)}</td><td class="tr">{fmt_qty(r['t_in'], *name_to_display.get(r['name'], ('个', 1)))}</td><td class="tr">{fmt_qty(r['t_out'], *name_to_display.get(r['name'], ('个', 1)))}</td><td class="tr">{fmt_qty(r['stock'], *name_to_display.get(r['name'], ('个', 1)))}</td><td>{tag}</td></tr>\n"""

# 入库行
inbound_body = ""
if in_rows:
    inbound_body = '<table style="table-layout:fixed;width:100%"><colgroup><col style="width:22%"><col style="width:18%"><col style="width:12%"><col style="width:16%"><col style="width:12%"><col style="width:20%"></colgroup><thead><tr><th>品名</th><th>规格/型号</th><th style="text-align:center">数量</th><th>部门</th><th style="text-align:center">库存</th><th style="text-align:center;white-space:nowrap">日期</th></tr></thead><tbody>\n'
    for r in in_rows:
        stock = 0
        for rec in records:
            if rec['name'] == r['name']:
                stock = rec['stock']
                break
        spec = name_to_spec.get(r['name'], '')
        inbound_body += f"""        <tr><td class="name">{short(clean_name(r['name'], spec), 16)}</td><td class="spec">{short(spec, 14)}</td><td style="text-align:center">{fmt_qty(r['qty'], *name_to_display.get(r['name'], ('个', 1)))}</td><td>{r['dept']}</td><td style="text-align:center">{fmt_qty(stock, *name_to_display.get(r['name'], ('个', 1)))}</td><td style="text-align:center;color:#8A95A5">{r['date']}</td></tr>\n"""
    inbound_body += '</tbody></table>'
else:
    inbound_body = '<div style="color:#8A95A5;text-align:center;padding:20px 0">暂无入库记录</div>'

# 出库行
outbound_body = ""
if out_rows:
    outbound_body = '<table style="table-layout:fixed;width:100%"><colgroup><col style="width:22%"><col style="width:18%"><col style="width:12%"><col style="width:16%"><col style="width:12%"><col style="width:20%"></colgroup><thead><tr><th>品名</th><th>规格/型号</th><th style="text-align:center">数量</th><th>部门</th><th style="text-align:center">库存</th><th style="text-align:center;white-space:nowrap">日期</th></tr></thead><tbody>\n'
    for r in out_rows:
        stock = 0
        for rec in records:
            if rec['name'] == r['name']:
                stock = rec['stock']
                break
        spec = name_to_spec.get(r['name'], '')
        outbound_body += f"""        <tr><td class="name">{short(clean_name(r['name'], spec), 16)}</td><td class="spec">{short(spec, 14)}</td><td style="text-align:center">{fmt_qty(r['qty'], *name_to_display.get(r['name'], ('个', 1)))}</td><td>{r['dept']}</td><td style="text-align:center">{fmt_qty(stock, *name_to_display.get(r['name'], ('个', 1)))}</td><td style="text-align:center;color:#8A95A5">{r['date']}</td></tr>\n"""
    outbound_body += '</tbody></table>'
else:
    outbound_body = '<div style="color:#8A95A5;text-align:center;padding:20px 0">暂无出库记录</div>'

# 饼图 - 部门金额占比（纯SVG donut）
pie_data = [(d, info) for d, info in dept_sorted[:8]]
pie_colors = ["#3D4F6F","#5B7FA6","#8BAA9E","#C4883A","#B85C5C","#9B7EB5","#5A9E8F","#C49A6C"]
pie_segments = ""
cx, cy, r_inner, r_outer = 16, 16, 10, 14.5
total_pie_val = sum(info["val"] for _, info in pie_data) or 1
angle = 0
for idx, (d, info) in enumerate(pie_data):
    pct = info["val"] / total_pie_val
    a2 = angle + pct * 360
    # SVG arc
    rad1 = angle * 3.14159 / 180
    rad2 = a2 * 3.14159 / 180
    x1o = cx + r_outer * (1 if idx == 0 else __import__('math').cos(rad1) if idx else 1)
    y1o = cy + r_outer * (0 if idx == 0 else __import__('math').sin(rad1) if idx else 0)
    x2o = cx + r_outer * __import__('math').cos(rad2)
    y2o = cy + r_outer * __import__('math').sin(rad2)
    x1i = cx + r_inner * __import__('math').cos(rad2)
    y1i = cy + r_inner * __import__('math').sin(rad2)
    x2i = cx + r_inner * __import__('math').cos(rad1)
    y2i = cy + r_inner * __import__('math').sin(rad1)
    large = 1 if pct > 0.5 else 0
    # 跳过过小片段
    if pct < 0.005:
        angle = a2
        continue
    pie_segments += f"""      <path d="M{x1o:.1f} {y1o:.1f} A{r_outer} {r_outer} 0 {large} 1 {x2o:.2f} {y2o:.2f} L{x1i:.2f} {y1i:.2f} A{r_inner} {r_inner} 0 {large} 0 {x2i:.2f} {y2i:.2f} Z" fill="{pie_colors[idx % len(pie_colors)]}"/>\n"""
    angle = a2

# 部门图例行
dept_chart_rows = ""
for idx, (d, info) in enumerate(pie_data):
    pct = info["val"] / total_pie_val * 100
    dept_chart_rows += f"""          <tr><td><span class="dot" style="background:{pie_colors[idx % len(pie_colors)]}"></span>{d}</td><td class="num">{pct:.1f}%</td><td class="num">¥{info['val']:,}</td></tr>\n"""

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>合盛辅料 HeSheng · 运营仪表盘</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{
  margin:0;padding:0;
  background:#F7F6F3;color:#1C2333;font-size:15px;
  font-family:-apple-system,'PingFang SC','Microsoft YaHei','Helvetica Neue',sans-serif;
  -webkit-font-smoothing:antialiased;
}}
.wrap{{max-width:1280px;margin:0 auto;padding:0 16px}}
.section-gap{{margin-bottom:14px}}
.hdr{{background:#fff;position:relative;box-shadow:0 1px 3px rgba(0,0,0,0.06);}}
.hdr::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,#3D4F6F 0%,#5B7FA6 100%);}}
.hdr-inner{{display:flex;align-items:center;justify-content:space-between;padding:18px 28px;}}
.brand{{display:flex;align-items:center;gap:16px}}
.brand-mark{{width:42px;height:42px;background:#3D4F6F;border-radius:10px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:22px;font-weight:800;flex-shrink:0;}}
.brand-name{{font-size:20px;font-weight:800;color:#1A1A2E;letter-spacing:1px}}
.brand-en{{font-size:11px;color:#8A94A2;letter-spacing:3px;text-transform:uppercase;margin-top:2px}}
.hdr-info{{display:flex;align-items:center;gap:28px}}
.hdr-info-item{{display:flex;flex-direction:column;align-items:flex-end;gap:1px}}
.hdr-info-label{{font-size:10px;color:#8A94A2;letter-spacing:2px;text-transform:uppercase}}
.hdr-info-value{{font-size:17px;font-weight:700;color:#1A1A2E}}
.hdr-divider{{width:1px;height:28px;background:#E8E7E3}}
.kpi-row{{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:16px 0}}
.kpi{{background:#fff;border-radius:14px;padding:18px 20px;border:1px solid #E8E6E2;min-width:0;box-shadow:0 2px 6px rgba(0,0,0,0.04);}}
.kn{{font-size:28px;font-weight:700;line-height:1;margin-bottom:3px}}
.kn.g{{color:#4A8C6F}}
.kn.r{{color:#B85C5C}}
.kn.o{{color:#C4883A}}
.kl{{font-size:13px;font-weight:500;color:#1C2333;margin-bottom:2px}}
.ks{{font-size:11px;color:#8A95A5}}
.card{{background:#fff;border-radius:14px;border:1px solid #E8E6E2;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.04);}}
.ctitle{{font-size:14px;font-weight:700;padding:14px 18px;border-bottom:2px solid #E8E7E3;display:flex;align-items:center;gap:6px;color:#2C3A4F;}}
.ctitle.navy{{border-bottom-color:#3D4F6F;color:#2C3A4F}}
.ctitle.danger{{border-bottom-color:#B85C5C;color:#B85C5C}}
.ctitle.orange{{border-bottom-color:#C4883A}}
.cnt{{font-size:11px;font-weight:600;padding:1px 8px;border-radius:10px}}
.cnt.o{{background:#FEF3E2;color:#C4883A}}
.dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle;}}
.mid-row{{display:grid;grid-template-columns:1fr;gap:14px;padding:0 0 14px;}}
.pie-section{{display:flex;gap:16px;align-items:center;padding:12px 16px;}}
.pie-svg{{flex-shrink:0;width:200px;height:200px;}}
.pie-legend{{flex:1;}}
.pie-legend table{{width:100%;border-collapse:collapse;font-size:13px;}}
.pie-legend td{{padding:3px 4px;vertical-align:middle;}}
.pie-legend td.num{{text-align:right;font-variant-numeric:tabular-nums;color:#555E6D;}}
.tab-bar{{display:flex;border-bottom:2px solid #E8E7E3;}}
.tab{{flex:1;padding:10px 0;text-align:center;font-size:14px;font-weight:600;cursor:pointer;color:#8A94A2;transition:all 0.15s;}}
.tab.active{{color:#3D4F6F;border-bottom:2px solid #3D4F6F;margin-bottom:-2px;}}
.tab-body{{padding:10px 14px;font-size:13px;max-height:170px;overflow-y:auto;}}
.tab-body table{{width:100%;border-collapse:collapse;font-size:13px;}}
.tab-body td{{padding:4px 6px;border-bottom:1px solid #F0EFEC;}}
.tab-body td.name{{white-space:nowrap;}}
.note{{font-size:11px;color:#8A95A5;padding:6px 16px 0;}}
.two-row{{display:grid;grid-template-columns:1fr 1fr;gap:14px;padding:0 0 24px;align-items:start;}}
.tbl-scroll{{overflow-x:auto;}}
.tbl-scroll table{{width:100%;border-collapse:collapse;font-size:13px;}}
.tbl-scroll th{{text-align:left;padding:8px 10px;font-size:11px;font-weight:700;color:#555E6D;text-transform:uppercase;letter-spacing:1px;border-bottom:2px solid #E8E7E3;position:sticky;top:0;background:#fff;}}
.tbl-scroll th.tr{{text-align:right;}}
.tbl-scroll td{{padding:6px 10px;border-bottom:1px solid #F0EFEC;vertical-align:middle;}}
.tbl-scroll td.tr{{text-align:right;font-variant-numeric:tabular-nums;}}
.td-num{{color:#8A95A5;font-size:11px;width:28px;text-align:center;}}
.td-name{{font-weight:500;max-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
.spec{{font-size:12px;color:#8A95A5;max-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
.st{{font-size:11px;padding:2px 8px;border-radius:4px;font-weight:600;}}
.st.r{{background:#FDECEC;color:#B85C5C;}}
.st.g{{background:#E8F5E9;color:#388E3C;}}
.st.o{{background:#FFF3E0;color:#E65100;}}
.u{{font-size:10px;color:#8A95A5;margin-left:2px;}}
.ftr{{text-align:center;padding:16px 0 24px;font-size:11px;color:#8A95A5;}}
/* ── 订单追踪专属样式 ── */
.o-section{{background:#fff;border-radius:14px;border:1px solid #E4E2DF;overflow:hidden;margin-bottom:14px;box-shadow:0 2px 8px rgba(0,0,0,0.04);}}
.o-header{{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid #F0EFEC;background:linear-gradient(135deg,#FAFBFC 0%,#F5F3F0 100%);}}
.o-title{{font-size:17px;font-weight:700;color:#1A1A2E;letter-spacing:0.5px;}}
.o-updated{{font-size:11px;color:#8A95A5;}}
.o-kpi-row{{display:flex;gap:12px;padding:16px 20px;}}
.okpi{{flex:1;display:flex;align-items:center;gap:12px;background:#FAFBFC;border-radius:10px;padding:14px 16px;border:1px solid #EEEBE6;min-width:0;}}
.okpi-icon{{width:42px;height:42px;border-radius:9px;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;}}
.okpi-body{{flex:1;min-width:0;}}
.okpi-num{{font-size:24px;font-weight:700;line-height:1.2;color:#1A1A2E;}}
.okpi-label{{font-size:12px;color:#555E6D;font-weight:500;margin-top:1px;}}
.okpi-sub{{font-size:10px;color:#8A95A5;white-space:nowrap;}}
.o-grid{{display:grid;grid-template-columns:1fr 320px;gap:0;border-top:1px solid #F0EFEC;}}
.o-pipeline{{padding:18px 20px;border-right:1px solid #F0EFEC;}}
.o-clients{{padding:18px 20px;}}
.o-subtitle{{font-size:13px;font-weight:700;color:#1A1A2E;margin-bottom:14px;padding-bottom:8px;border-bottom:2px solid #E8E7E3;}}
.o-pipe-row{{display:flex;gap:5px;margin-bottom:10px;}}
.o-pipe-legend{{font-size:10px;color:#8A95A5;text-align:center;letter-spacing:2px;}}
.o-client-table{{width:100%;border-collapse:collapse;font-size:13px;}}
.o-client-table th{{text-align:left;padding:5px 8px;border-bottom:2px solid #E8E7E3;font-size:11px;color:#555E6D;font-weight:600;}}
.o-client-table th.tr,.o-client-table th.bar-col{{text-align:right;}}
.o-client-table td{{padding:6px 8px;border-bottom:1px solid #F5F3F0;}}
.o-client-table td.tr{{text-align:right;font-variant-numeric:tabular-nums;}}
.o-active-orders{{padding:0 20px 18px;border-top:1px solid #F0EFEC;}}
.o-active-orders .o-subtitle{{margin-top:18px;}}
.o-order-scroll{{max-height:280px;overflow-y:auto;}}
.o-order-table{{width:100%;border-collapse:collapse;font-size:12px;}}
.o-order-table th{{text-align:left;padding:6px 8px;border-bottom:2px solid #E8E7E3;font-size:10px;font-weight:600;color:#8A95A5;text-transform:uppercase;letter-spacing:1px;position:sticky;top:0;background:#fff;}}
.o-order-table th.tr{{text-align:right;}}
.o-order-table td{{padding:5px 8px;border-bottom:1px solid #F5F3F0;vertical-align:middle;}}
.o-order-table td.tr{{text-align:right;font-variant-numeric:tabular-nums;}}
.o-monthly{{padding:0 20px 16px;border-bottom:1px solid #F0EFEC;}}
.o-month-table{{width:100%;border-collapse:collapse;font-size:12px;}}
.o-month-table th{{text-align:left;padding:4px 8px;border-bottom:2px solid #E8E7E3;font-size:10px;font-weight:600;color:#8A95A5;}}
.o-month-table th.tr,.o-month-table th.bar-col{{text-align:right;}}
.o-month-table td{{padding:3px 8px;border-bottom:1px solid #F5F3F0;}}
.o-month-table td.tr{{text-align:right;font-variant-numeric:tabular-nums;}}
/* ── 手机端适配 ── */
@media(max-width:768px){{
  body{{font-size:14px}}
  .wrap{{padding:0 10px}}
  .hdr-inner{{padding:12px 16px}}
  .hdr-info{{gap:14px}}
  .hdr-info-value{{font-size:14px}}
  .hdr-divider{{display:none}}
  .hdr-info-item:last-child{{display:none}}
  .brand-name{{font-size:17px}}
  .brand-mark{{width:34px;height:34px;font-size:18px}}
  .kpi-row{{gap:8px;padding:12px 0}}
  .kpi{{padding:12px 14px}}
  .kn{{font-size:22px}}
  .mid-row{{grid-template-columns:1fr;gap:10px;padding:0 0 10px}}
  .two-row{{grid-template-columns:1fr;gap:10px;padding:0 0 16px}}
  .pie-section{{flex-direction:column;align-items:center;padding:10px}}
  .pie-svg{{width:160px;height:160px}}
  .o-kpi-row{{flex-wrap:wrap;gap:6px;padding:12px 14px}}
  .okpi{{flex:1 1 calc(50% - 3px);min-width:0;padding:10px 12px;gap:8px}}
  .okpi-icon{{width:34px;height:34px;font-size:16px;border-radius:7px}}
  .okpi-num{{font-size:20px}}
  .okpi-sub{{display:none}}
  .okpi:nth-child(5){{flex:1 1 100%}}
  .o-grid{{grid-template-columns:1fr}}
  .o-pipeline{{border-right:none;border-bottom:1px solid #F0EFEC;padding:14px 14px}}
  .o-clients{{padding:14px 14px}}
  .o-active-orders{{padding:0 14px 14px}}
  .o-monthly{{padding:0 14px 14px}}
  .o-month-table{{font-size:11px}}
  .o-header{{padding:14px 14px}}
  .o-updated{{display:none}}
  .o-title{{font-size:15px}}
  .o-pipe-row{{flex-wrap:wrap;gap:4px}}
  .o-pipe-row > div{{flex:1 1 calc(25% - 3px)!important;min-width:60px}}
  .o-order-scroll{{max-height:240px}}
  .o-order-table{{font-size:11px}}
  .o-order-table th{{font-size:9px;padding:4px 5px}}
  .o-order-table td{{padding:3px 5px}}
  .tab{{font-size:13px}}
  .tab-body{{font-size:12px;max-height:200px}}
  .tbl-scroll table{{font-size:12px;min-width:480px}}
  .tbl-scroll th{{font-size:10px;padding:6px 8px}}
  .tbl-scroll{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
  .ctitle{{font-size:13px;padding:10px 14px}}
  .note{{font-size:10px;padding:4px 12px}}
  .ftr{{font-size:10px;padding:12px 0 20px}}
  .td-name{{max-width:120px!important}}
}}
@media(max-width:480px){{
  .wrap{{padding:0 6px}}
  .hdr-inner{{padding:8px 10px;gap:8px}}
  .brand{{gap:8px}}
  .brand-mark{{width:28px;height:28px;font-size:13px;border-radius:6px}}
  .brand-name{{font-size:14px;letter-spacing:0}}
  .brand-en{{display:none}}
  .hdr-info{{gap:8px}}
  .hdr-info-value{{font-size:11px}}
  .hdr-info-label{{font-size:8px}}
  .hdr-divider{{display:none}}
  .hdr-info-item:last-child{{display:none}}
  .kpi{{padding:8px 10px}}
  .kpi-row{{gap:6px}}
  .kn{{font-size:20px}}
  .kl{{font-size:12px}}
  .ks{{font-size:10px}}
  .okpi{{flex:1 1 calc(50% - 3px);padding:8px 10px;gap:6px}}
  .okpi-icon{{width:28px;height:28px;font-size:14px;border-radius:6px}}
  .okpi-num{{font-size:18px}}
  .okpi-label{{font-size:10px}}
  .o-pipe-row > div{{flex:1 1 calc(50% - 2px)!important;min-width:0}}
  .o-pipe-legend{{font-size:9px;letter-spacing:1px}}
  .pie-svg{{width:130px;height:130px}}
  .pie-legend table{{font-size:11px}}
  .o-section{{border-radius:10px}}
  .card{{border-radius:10px}}
  .kpi{{border-radius:10px}}
  .okpi{{border-radius:8px}}
  .tbl-scroll table{{font-size:11px}}
  .tbl-scroll th{{font-size:9px;padding:4px 6px}}
  .tbl-scroll td{{padding:4px 6px}}
  .tab{{font-size:12px;padding:8px 0}}
}}
</style>
</head>
<body>
<div class="hdr"><div class="hdr-inner">
  <div class="brand">
    <div class="brand-mark">HS</div>
    <div><div class="brand-name">合盛辅料</div><div class="brand-en">HeSheng Button</div></div>
  </div>
  <div class="hdr-info">
    <div class="hdr-info-item"><div class="hdr-info-label">Updated</div><div class="hdr-info-value">{now}</div></div>
    <div class="hdr-divider"></div>
    <div class="hdr-info-item"><div class="hdr-info-label">Source</div><div class="hdr-info-value">Feishu Bitable</div></div>
  </div>
</div></div>
<div class="wrap">

<div class="kpi-row section-gap">
  <div class="kpi"><div class="kn">{total}</div><div class="kl">总 SKU</div><div class="ks">全部物料品类</div></div>
  <div class="kpi"><div class="kn g">{in_stock}</div><div class="kl">有库存</div><div class="ks">可正常领用</div></div>
  <div class="kpi"><div class="kn r">{out_stock}</div><div class="kl">无库存</div><div class="ks">当前缺货待补</div></div>
  <div class="kpi"><div class="kn o">¥{total_val:,}</div><div class="kl">库存总值</div><div class="ks">已占用资金</div></div>
</div>

<div class="section-gap two-row">
  <div class="card">
    <div class="ctitle danger">⚠️ 缺货清单 <span class="cnt">{len(reorder)} 品</span></div>
    <div class="tbl-scroll" style="max-height:400px;overflow-y:auto;">
      <table>
        <thead><tr><th style="width:38%">品名</th><th style="width:28%">部门</th><th style="width:34%">状态</th></tr></thead>
        <tbody>
{reorder_rows}        </tbody>
      </table>
    </div>
  </div>
  <div class="card">
    <div class="ctitle navy">库存金额 TOP 20</div>
    <div class="tbl-scroll" style="max-height:400px;overflow-y:auto;">
      <table>
        <thead><tr><th style="width:8%">#</th><th style="width:35%">品名</th><th style="width:20%">部门</th><th class="tr" style="width:17%">库存</th><th class="tr" style="width:20%">金额</th></tr></thead>
        <tbody>
{top20_rows}        </tbody>
      </table>
    </div>
  </div>
</div>

<div class="mid-row section-gap">
  <div class="card">
    <div class="ctitle navy">📥 入库记录 <span class="cnt">{len(in_rows)} 条</span></div>
    <div class="tbl-scroll" style="max-height:300px;overflow-y:auto">
{inbound_body}
    </div>
  </div>
  <div class="card">
    <div class="ctitle navy">📤 出库记录 <span class="cnt">{len(out_rows)} 条</span></div>
    <div class="tbl-scroll" style="max-height:300px;overflow-y:auto">
{outbound_body}
    </div>
  </div>
</div>

<div class="card section-gap">
  <div class="ctitle navy" style="padding:10px 14px;font-size:13px;font-weight:600">
    🔄 过手件识别 <span class="cnt">{len(pass_through_candidates)} 项</span>
  </div>
  <div class="tbl-scroll" style="max-height:300px;overflow-y:auto;padding:0 14px 10px">
      <table>
        <thead><tr><th style="width:30%">品名</th><th class="tr" style="width:12%">入库</th><th class="tr" style="width:12%">出库</th><th class="tr" style="width:12%">库存</th><th style="width:24%">标签</th></tr></thead>
        <tbody>
{pass_through_rows}        </tbody>
      </table>
    </div>
</div>

<!-- ═══ 订单追踪 ═══ -->
<div class="o-section">
  <div class="o-header">
    <div class="o-title">📋 订单追踪</div>
    <div class="o-updated">更新于 {now}</div>
  </div>
  <div class="o-kpi-row">{order_kpi_cards}</div>
  
  <!-- 月度概览 -->
  <div class="o-monthly">
    <div class="o-subtitle" style="padding:0 4px 8px;margin-bottom:0">📅 月度订单概览</div>
    <table class="o-month-table">
      <thead><tr><th>月份</th><th class="tr">单数</th><th class="tr">G数</th><th class="bar-col">趋势</th></tr></thead>
      <tbody>{month_chart_rows}</tbody>
    </table>
  </div>

  <div class="o-grid">
    <!-- 工序管道 -->
    <div class="o-pipeline">
      <div class="o-subtitle">工序管道 · {len(in_progress)}单在途</div>
      <div class="o-pipe-row">{pipe_html}</div>
      <div class="o-pipe-legend">接单→调色→生产→筛胚→车钮→抛光→品检→出货</div>
    </div>
    <!-- 客户排名 -->
    <div class="o-clients">
      <div class="o-subtitle">客户排名（按G数）</div>
      <table class="o-client-table">
        <thead><tr><th>客户</th><th class="tr">单数</th><th class="tr">G数</th><th class="bar-col">占比</th></tr></thead>
        <tbody>{client_rows}</tbody>
      </table>
    </div>
  </div>

  <!-- 在途订单 -->
  <div class="o-active-orders">
    <div class="o-subtitle">在途订单 · {len(active_orders)} 单</div>
    <div class="o-order-scroll">
      <table class="o-order-table">
        <thead><tr><th></th><th>订单号</th><th class="tr">G数</th><th>类型</th><th>工序</th><th class="tr">日期</th><th>滞留</th></tr></thead>
        <tbody>{order_rows}</tbody>
      </table>
    </div>
  </div>
</div>

<div class="ftr">合盛钮扣厂 · 生产运营司 · 数据来源 飞书多维表格</div>
</div><!-- end wrap -->

<script>
function swTab(el,tab){{
  document.querySelectorAll('.tab').forEach(function(e){{e.classList.remove('active')}});
  el.classList.add('active');
  document.getElementById('t-in').style.display=tab==='in'?'block':'none';
  document.getElementById('t-out').style.display=tab==='out'?'block':'none';
}}
</script>
</body>
</html>"""

# ── 3. 写入文件 ──
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\n✅ index.html 已生成")
print(f"总SKU:{total} 有库存:{in_stock} 无库存:{out_stock} 总值:¥{total_val:,}")
print(f"TOP1: {top20[0]['name']} ¥{top20[0]['cost']:,}" if top20 else "")
print(f"缺货: {len(reorder)}品")
