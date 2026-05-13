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
        records.extend(data["data"]["items"])
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
print(f"共 {len(items)} 条")

records = []
for r in items:
    f = r.get("fields", {})
    name = safe_str(f.get("货品名称", ""))
    if not name: continue
    spec = safe_str(f.get("规格型号", ""))
    stock = int(safe_num(f.get("当前库存", 0)))
    cost = round(safe_num(f.get("库存总价值", 0)))
    dept = safe_str(f.get("所属部门", ""))
    records.append({"name": name, "spec": spec, "stock": stock, "cost": cost, "dept": dept})

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
order_re = _re.compile(r'HX\d+')
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
    
    found = order_re.findall(content)
    found_g = g_re.findall(content)
    
    for o in found:
        if o not in all_orders:
            all_orders[o] = {"order_no":o,"g_count":0,"product_type":"树脂钮","step":"接单","date":date_str,"latest_date":date_str,"client":"恒业"}
        if date_str > all_orders[o]["latest_date"]: all_orders[o]["latest_date"] = date_str
        
        for g in found_g:
            gi = int(g)
            if 1 <= gi <= 500: all_orders[o]["g_count"] = max(all_orders[o]["g_count"],gi)
        
        for bt in BUTTON_TYPES:
            if bt in content: all_orders[o]["product_type"] = bt; break
        
        for si,(step,kws) in enumerate(STEP_KW.items()):
            if any(kw in content for kw in kws):
                cs = PROCESS_STEPS.index(all_orders[o]["step"])
                if si >= cs: all_orders[o]["step"] = step

# 订单汇总
today_orders = [o for o in all_orders.values() if o["latest_date"]==today_str]
in_progress = [o for o in all_orders.values() if o["step"]!="出货"]
shipped = [o for o in all_orders.values() if o["step"]=="出货"]
total_g = sum(o["g_count"] for o in all_orders.values())
today_g = sum(o["g_count"] for o in today_orders)
no_g = [o for o in today_orders if o["g_count"]==0]
total_order_count = len(all_orders)

# 客户排名
client_g = {}
for o in all_orders.values():
    c = o["client"]
    client_g[c] = client_g.get(c,0) + o["g_count"]
client_rank = sorted(client_g.items(), key=lambda x:-x[1])

# 工序分布
step_counts = {}
for o in today_orders:
    step_counts[o["step"]] = step_counts.get(o["step"],0) + 1

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
for o in active_orders:
    sc = STEP_C.get(o["step"],"#888")
    order_rows += f'<tr><td style="color:{sc};font-weight:700">●</td><td class="td-name">{o["order_no"]}</td><td class="tr">{o["g_count"]}G</td><td>{o["product_type"][:6]}</td><td><span style="background:{sc};color:#fff;padding:1px 8px;border-radius:10px;font-size:11px">{o["step"]}</span></td><td style="font-size:11px;color:#8A95A5">{o["latest_date"][5:]}</td></tr>\n'

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

# 订单KPI
order_kpi_cards = f"""<div class="kpi"><div class="kn">{len(today_orders)}</div><div class="kl">今日订单</div><div class="ks">实时追踪</div></div>
<div class="kpi"><div class="kn g">{today_g}G</div><div class="kl">今日G数</div><div class="ks">{today_g*144:,}颗</div></div>
<div class="kpi"><div class="kn o">{len(in_progress)}/{len(shipped)}</div><div class="kl">进行中/已出货</div><div class="ks">{total_order_count}单在途</div></div>
<div class="kpi"><div class="kn r">{len(no_g)}单</div><div class="kl">待补G数</div><div class="ks">今天</div></div>"""

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
  font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;
  background:#F2F1EE;color:#1C2333;font-size:15px;
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
.kpi-row{{display:flex;gap:14px;padding:16px 0}}
.kpi{{flex:1;background:#fff;border-radius:12px;padding:16px 18px;border:1px solid #E4E2DF;min-width:0;}}
.kn{{font-size:28px;font-weight:700;line-height:1;margin-bottom:3px}}
.kn.g{{color:#4A8C6F}}
.kn.r{{color:#B85C5C}}
.kn.o{{color:#C4883A}}
.kl{{font-size:13px;font-weight:500;color:#1C2333;margin-bottom:2px}}
.ks{{font-size:11px;color:#8A95A5}}
.card{{background:#fff;border-radius:12px;border:1px solid #E4E2DF;overflow:hidden;}}
.ctitle{{font-size:14px;font-weight:700;padding:12px 16px;border-bottom:2px solid #E8E7E3;display:flex;align-items:center;gap:6px;}}
.ctitle.navy{{border-bottom-color:#3D4F6F}}
.ctitle.orange{{border-bottom-color:#C4883A}}
.cnt{{font-size:11px;font-weight:600;padding:1px 8px;border-radius:10px}}
.cnt.o{{background:#FEF3E2;color:#C4883A}}
.dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle;}}
.mid-row{{display:grid;grid-template-columns:1fr 340px;gap:14px;padding:0 0 14px;align-items:start;}}
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
.st{{font-size:11px;padding:2px 8px;border-radius:4px;font-weight:600;}}
.st.r{{background:#FDECEC;color:#B85C5C;}}
.ftr{{text-align:center;padding:16px 0 24px;font-size:11px;color:#8A95A5;}}
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

<!-- ═══ 订单追踪 ═══ -->
<div class="section-gap" style="background:#fff;border-radius:12px;border:1px solid #E4E2DF;padding:0 0 16px">
  <div class="ctitle navy" style="border-bottom:2px solid #C4883A">订单追踪</div>
  <div class="kpi-row" style="padding:14px 16px">
{order_kpi_cards}
  </div>
  <div style="display:grid;grid-template-columns:1fr 380px 320px;gap:14px;padding:0 16px">
    <div>
      <div style="font-size:13px;font-weight:700;margin:0 0 8px;color:#1C2333">客户订单排名（按G数）</div>
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr><th style="text-align:left;padding:4px 6px;border-bottom:2px solid #E8E7E3;font-size:11px;color:#555E6D">客户</th><th class="tr" style="border-bottom:2px solid #E8E7E3;font-size:11px;color:#555E6D">单数</th><th class="tr" style="border-bottom:2px solid #E8E7E3;font-size:11px;color:#555E6D">G数</th><th style="width:60px;border-bottom:2px solid #E8E7E3"></th></tr></thead>
        <tbody>{client_rows}</tbody>
      </table>
    </div>
    <div>
      <div style="font-size:13px;font-weight:700;margin:0 0 8px;color:#1C2333">今日工序进度</div>
      <div style="display:flex;gap:4px;margin-bottom:10px">{pipe_html}</div>
      <div style="font-size:11px;color:#8A95A5;text-align:center;margin-top:6px">接单→调色→生产→筛胚→车钮→抛光→品检→出货</div>
    </div>
    <div>
      <div style="font-size:13px;font-weight:700;margin:0 0 8px;color:#1C2333">在途订单（{len(active_orders)}单）</div>
      <div style="max-height:220px;overflow-y:auto">
        <table style="width:100%;border-collapse:collapse;font-size:12px">
          <tbody>{order_rows}</tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<div class="kpi-row section-gap">
  <div class="kpi"><div class="kn">{total}</div><div class="kl">总 SKU</div><div class="ks">全部物料品类</div></div>
  <div class="kpi"><div class="kn g">{in_stock}</div><div class="kl">有库存</div><div class="ks">可正常领用</div></div>
  <div class="kpi"><div class="kn r">{out_stock}</div><div class="kl">无库存</div><div class="ks">当前缺货待补</div></div>
  <div class="kpi"><div class="kn o">¥{total_val:,}</div><div class="kl">库存总值</div><div class="ks">已占用资金</div></div>
</div>

<div class="mid-row section-gap">
  <div class="card">
    <div class="ctitle navy">各部门库存金额占比</div>
    <div class="pie-section">
      <svg class="pie-svg" viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">
{pie_segments}      </svg>
      <div class="pie-legend">
        <table>
{dept_chart_rows}        </table>
      </div>
    </div>
  </div>
  <div class="card">
    <div class="tab-bar">
      <div class="tab active" onclick="swTab(this,'in')">入库</div>
      <div class="tab" onclick="swTab(this,'out')">出库</div>
    </div>
    <div id="t-in" class="tab-body">
      <div style="color:#4A8C6F;font-weight:600;margin-bottom:6px">今日入库 {in_stock} 品</div>
      <table><tbody>
        <tr><td class="name">沽水（促进剂）</td><td style="text-align:right">100 kg</td><td style="color:#8A95A5">05-11</td></tr>
      </tbody></table>
    </div>
    <div id="t-out" class="tab-body" style="display:none">
      <div style="color:#8A95A5;text-align:center;padding:20px 0">暂无出库记录</div>
    </div>
  </div>
</div>

<div class="section-gap two-row">
  <div class="card">
    <div class="ctitle navy">库存金额 TOP 20</div>
    <div class="tbl-scroll">
      <table>
        <thead><tr><th style="width:8%">#</th><th style="width:35%">品名</th><th style="width:20%">部门</th><th class="tr" style="width:17%">库存</th><th class="tr" style="width:20%">金额</th></tr></thead>
        <tbody>
{top20_rows}        </tbody>
      </table>
    </div>
  </div>
  <div class="card">
    <div class="ctitle orange">缺货清单 <span class="cnt o">{len(reorder)} 品</span></div>
    <div class="note">缺货 ≠ 补货 · 高频消耗+缺货 → 立即采购</div>
    <div class="tbl-scroll" style="max-height:400px;overflow-y:auto;">
      <table>
        <thead><tr><th style="width:38%">品名</th><th style="width:28%">部门</th><th style="width:34%">状态</th></tr></thead>
        <tbody>
{reorder_rows}        </tbody>
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
