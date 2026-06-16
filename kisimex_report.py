"""
iSolarCloud KISIMEX Daily Report Bot
- Tự động login web3.isolarcloud.com.hk bằng Playwright
- Lấy dữ liệu từ BẢNG DANH SÁCH nhà máy (1 trang duy nhất)
- Cột: "Yield today" (MWh → đổi ra kWh) + "Equivalent hours"
- Gửi Telegram lúc 17:00 VN hàng ngày; hỗ trợ lệnh /baocao

Biến môi trường (Railway):
    ISOLAR_USER        - email đăng nhập iSolarCloud
    ISOLAR_PASS        - password iSolarCloud
    TELEGRAM_BOT_TOKEN - token bot Telegram
    TELEGRAM_CHAT_ID   - chat ID Telegram
"""

import os
import time
import threading
import schedule
import requests
from datetime import datetime, timezone, timedelta

# ─── CONFIG ──────────────────────────────────────────────────────────────────
ISOLAR_USER      = os.environ["ISOLAR_USER"]
ISOLAR_PASS      = os.environ["ISOLAR_PASS"]
TELEGRAM_TOKEN   = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

REPORT_TIME = "10:00"   # 17:00 UTC+7 = 10:00 UTC

PLANTS = [
    {"name": "KHO BAO BÌ",    "capacity": 442.00},
    {"name": "KHU VĂN PHÒNG", "capacity": 298.40},
    {"name": "TẮC CẬU",       "capacity": 360.00},
]

WEEKDAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]

PLANT_LIST_URL = "https://web3.isolarcloud.com.hk/#/plantList"


# ─── LOGIN ────────────────────────────────────────────────────────────────────
def login_isolar():
    from playwright.sync_api import sync_playwright

    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 900},
    )
    page = context.new_page()

    print("🔐 Đang mở iSolarCloud...")
    page.goto("https://web3.isolarcloud.com.hk/", timeout=60000)
    page.wait_for_load_state("networkidle", timeout=30000)
    time.sleep(3)

    user_selectors = [
        'input[name="account"]',
        'input[placeholder*="account" i]',
        'input[placeholder*="email" i]',
        'input[placeholder*="username" i]',
        'input[type="text"]:visible',
    ]
    for sel in user_selectors:
        try:
            page.fill(sel, ISOLAR_USER, timeout=3000)
            print(f"✏️  Username → {sel}")
            break
        except Exception:
            continue

    time.sleep(0.5)
    page.fill('input[type="password"]:visible', ISOLAR_PASS)
    time.sleep(0.5)

    login_selectors = [
        'button[type="submit"]',
        '.login-btn',
        'button:has-text("Log In")',
        'button:has-text("Login")',
        'button:has-text("登录")',
        'button:has-text("Sign In")',
    ]
    for sel in login_selectors:
        try:
            page.click(sel, timeout=3000)
            print(f"🖱️  Click login → {sel}")
            break
        except Exception:
            continue

    page.wait_for_url("**/#/**", timeout=30000)
    time.sleep(4)
    print("✅ Đăng nhập thành công!")
    return p, browser, page


# ─── SCRAPE BẢNG DANH SÁCH ───────────────────────────────────────────────────
def get_all_plant_data(page) -> list:
    """
    Scrape bảng danh sách nhà máy — lấy cột:
      - 'Yield today' (MWh, sẽ đổi sang kWh)
      - 'Equivalent hours'
    """
    print("📡 Đang mở trang danh sách nhà máy...")
    page.goto(PLANT_LIST_URL, timeout=60000)
    page.wait_for_load_state("networkidle", timeout=30000)
    time.sleep(5)

    result = page.evaluate("""() => {
        const ths = Array.from(document.querySelectorAll('th'));
        const headerTexts = ths.map(th => th.innerText.trim());

        let prodIdx = -1, hourIdx = -1, nameIdx = 0;
        headerTexts.forEach((txt, i) => {
            const t = txt.toLowerCase();
            if (t.includes('yield today') || t.includes('daily yield') || t.includes('today')
                || t.includes('sản lượng') || t.includes('trong ngày'))
                prodIdx = i;
            if (t.includes('equivalent') || t.includes('peak hour')
                || t.includes('giờ') || t.includes('tương đương'))
                hourIdx = i;
        });

        const rows = Array.from(document.querySelectorAll('tbody tr')).map(tr => {
            const cells = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
            return {
                name:       cells[nameIdx] || '',
                production: prodIdx >= 0 ? cells[prodIdx] : null,
                hours:      hourIdx >= 0 ? cells[hourIdx] : null,
            };
        });

        return { headers: headerTexts, prodIdx, hourIdx, rows };
    }""")

    headers  = result.get("headers", [])
    prod_idx = result.get("prodIdx", -1)
    hour_idx = result.get("hourIdx", -1)
    rows     = result.get("rows", [])

    print(f"   → headers={headers}")
    print(f"   → prodIdx={prod_idx} ('{headers[prod_idx] if prod_idx >= 0 else 'N/F'}'), hourIdx={hour_idx} ('{headers[hour_idx] if hour_idx >= 0 else 'N/F'}')")
    for r in rows:
        print(f"   → '{r.get('name','')[:40]}' | prod='{r.get('production')}' | hours='{r.get('hours')}'")

    return rows


# ─── HELPERS ─────────────────────────────────────────────────────────────────
def parse_number(s: str):
    """Parse số từ chuỗi, bỏ dấu phân cách, trả về float."""
    if not s or s.strip() in ("--", "N/A", ""):
        return None
    # Lấy phần số đầu tiên (bỏ đơn vị phía sau)
    token = s.strip().split()[0]
    # Thử format quốc tế (1,234.56 hoặc 1234.56)
    try:
        return float(token.replace(",", ""))
    except ValueError:
        pass
    # Thử format VN (1.234,56)
    try:
        return float(token.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def parse_production_kwh(s: str):
    """
    Parse sản lượng, tự động đổi MWh → kWh nếu cần.
    iSolarCloud plant list hiển thị 'Yield today' theo đơn vị MWh.
    """
    if not s or s.strip() in ("--", "N/A", ""):
        return None
    parts = s.strip().split()
    val = parse_number(parts[0])
    if val is None:
        return None
    unit = parts[1].lower() if len(parts) > 1 else ""
    if "mwh" in unit:
        val = val * 1000   # MWh → kWh
    # Nếu không có đơn vị hoặc đã là kWh, giữ nguyên
    return val


def parse_hours(s: str):
    """Parse giờ tương đương."""
    return parse_number(s)


def find_row_for_plant(rows: list, plant_name: str):
    name_upper = plant_name.upper()
    for row in rows:
        row_name = (row.get("name") or "").upper()
        keywords = [w for w in name_upper.split() if len(w) > 2]
        if any(kw in row_name for kw in keywords):
            return row
    return None


# ─── FORMAT ──────────────────────────────────────────────────────────────────
def format_report(results: list) -> str:
    tz_vn = timezone(timedelta(hours=7))
    now = datetime.now(tz_vn)
    thu = WEEKDAYS[now.weekday()]
    date_str = now.strftime("%d/%m/%Y")

    emojis = ["1️⃣", "2️⃣", "3️⃣"]
    total_kwh = 0.0

    lines = [
        "🌟 BÁO CÁO VẬN HÀNH SOLAR - KISIMEX",
        "━" * 23,
        f"Hệ thống  : KISIMEX - Kiên Giang",
        f"Ngày      : {thu}, {date_str}",
        f"Cập nhật  : 17:00",
        "━" * 23,
    ]

    for i, (plant, data) in enumerate(results):
        kwh = parse_production_kwh(data.get("production"))
        gio = parse_hours(data.get("hours"))
        cap = plant["capacity"]

        prod_str = f"{kwh:,.2f} kWh" if kwh is not None else "N/A"
        gio_str  = f"{gio:.2f} h"    if gio is not None else "N/A"

        if kwh is not None:
            total_kwh += kwh

        lines += [
            f"{emojis[i]} {plant['name']} ({cap:,.2f} kWp)",
            f"  ⚡ Sản lượng         : {prod_str}",
            f"  ☀️ Giờ tương đương  : {gio_str}",
            "",
        ]

    lines += [
        "━" * 23,
        f"📊 Tổng sản lượng    : {total_kwh:,.2f} kWh",
        f"   Công suất lắp đặt : 1,100.40 kWp",
        "",
        "Trân trọng.",
    ]

    return "\n".join(lines)


# ─── TELEGRAM ─────────────────────────────────────────────────────────────────
def send_telegram(message: str) -> bool:
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
    ok   = resp.status_code == 200 and resp.json().get("ok")
    print("📤 Đã gửi Telegram!" if ok else f"❌ Lỗi Telegram: {resp.text}")
    return ok


# ─── TELEGRAM COMMAND LISTENER ────────────────────────────────────────────────
def telegram_poll():
    offset = 0
    print("📩 Telegram command listener khởi động (/baocao)")
    while True:
        try:
            url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            resp = requests.get(url, params={"offset": offset, "timeout": 30}, timeout=35)
            if resp.status_code != 200:
                time.sleep(5)
                continue
            for update in resp.json().get("result", []):
                offset = update["update_id"] + 1
                msg  = update.get("message", {})
                text = (msg.get("text") or "").strip().lower()
                if text.startswith("/baocao"):
                    print(f"📩 Lệnh /baocao từ chat_id={msg.get('chat', {}).get('id')}")
                    requests.post(
                        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                        json={"chat_id": TELEGRAM_CHAT_ID, "text": "⏳ Đang lấy dữ liệu, vui lòng chờ..."},
                        timeout=10,
                    )
                    threading.Thread(target=run_report, daemon=True).start()
        except Exception as e:
            print(f"⚠️ Telegram poll lỗi: {e}")
            time.sleep(5)


# ─── JOB ─────────────────────────────────────────────────────────────────────
def run_report():
    tz_vn = timezone(timedelta(hours=7))
    print(f"\n{'='*50}")
    print(f"🌞 Chạy báo cáo lúc {datetime.now(tz_vn).strftime('%H:%M %d/%m/%Y')} (VN)")

    p = browser = None
    try:
        p, browser, page = login_isolar()
        rows = get_all_plant_data(page)

        results = []
        for plant in PLANTS:
            row  = find_row_for_plant(rows, plant["name"])
            data = {"production": row["production"], "hours": row["hours"]} if row else {}
            results.append((plant, data))
            if not row:
                print(f"⚠️  Không tìm thấy hàng cho {plant['name']}")

        message = format_report(results)
        print(f"\n📋 Báo cáo:\n{message}\n")
        send_telegram(message)

    except Exception as e:
        err = f"⚠️ Lỗi báo cáo KISIMEX: {e}"
        print(err)
        try:
            send_telegram(err)
        except Exception:
            pass
    finally:
        if browser:
            browser.close()
        if p:
            p.stop()


# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🤖 KISIMEX Report Bot khởi động")
    print(f"⏰ Lịch gửi: {REPORT_TIME} UTC (= 17:00 VN) mỗi ngày")
    print("📩 Lệnh Telegram: /baocao")

    threading.Thread(target=telegram_poll, daemon=True).start()

    schedule.every().day.at(REPORT_TIME).do(run_report)

    while True:
        schedule.run_pending()
        time.sleep(30)
