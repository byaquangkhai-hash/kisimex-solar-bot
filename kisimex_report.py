"""
iSolarCloud KISIMEX Daily Report Bot
- Tự động login web3.isolarcloud.com.hk bằng Playwright
- Lấy dữ liệu 3 nhà máy KISIMEX (scrape DOM)
- Gửi báo cáo Telegram lúc 17:00 hàng ngày (UTC+7 = 10:00 UTC)

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

# ─── CONFIG ──────────────────────────────────────────────────────────────────────────────
ISOLAR_USER      = os.environ["ISOLAR_USER"]
ISOLAR_PASS      = os.environ["ISOLAR_PASS"]
TELEGRAM_TOKEN   = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

REPORT_TIME = "10:00"   # 17:00 UTC+7 = 10:00 UTC

PLANTS = [
    {
        "name": "KHO BAO BÌ",
        "capacity": 442.00,
        "url": (
            "https://web3.isolarcloud.com.hk/#/plantDetail/overView?"
            "iZqCKXx5Va4g8FQ7ra3x4Hf6DQbrtgRigehoXLxU0zL/8B89lX288F1dHBsyrQRG"
            "drXVifwghOIMZqwzIXUQnWHbeB9Yc65bh88oSSzDpcExy91tArNP+iaaavfs1dsBV"
            "pjLmuYvQbcAiw54aRHjgA=="
        ),
    },
    {
        "name": "KHU VĂN PHÒNG",
        "capacity": 298.40,
        "url": (
            "https://web3.isolarcloud.com.hk/#/plantDetail/overView?"
            "Ve03VaBd6nEPkgncgMLeinf6DQbrtgRigehoXLxU0zIO1j2w47+2f8ypm9x4mMNb7"
            "D5FyoWUsV4EydcaOPkDISwI37vleOhOPTN1IHkvpnM7l/tbyxLmEw/fHYElach1MA"
            "DkNUl7Qx7Dgv/SZSjhmg=="
        ),
    },
    {
        "name": "TẮC C᪪u",
        "capacity": 360.00,
        "url": (
            "https://web3.isolarcloud.com.hk/#/plantDetail/overView?"
            "HxZvdIgPhCiqjtXZzyU573f6DQbrtgRigehoXLxU0zKh+mSEyO5CySQHVD43qrzX"
            "lTLy2TwT9gc0cqiS0t+cWjTUg2xDN/M2QgG+3avo07w/Ln8410NRBk8unPVHSimD"
            "FT0KkDI5/lboqQT6LvpAkw=="
        ),
    },
]

WEEKDAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


# ─── LOGIN ────────────────────────────────────────────────────────────────────────────────
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
        viewport={"width": 1280, "height": 800},
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


# ─── SCRAPE DOM ─────────────────────────────────────────────────────────────────────────
def get_plant_data(page, plant: dict) -> dict:
    """Điều hướng đến trang nhà máy và lấy dữ liệu từ DOM."""
    print(f"📡 Đang lấy dữ liệu {plant['name']}...")
    page.goto(plant["url"], timeout=60000)
    page.wait_for_load_state("networkidle", timeout=30000)
    time.sleep(4)

    data = page.evaluate("""() => {
        const pts = Array.from(document.querySelectorAll('span.overview-point-value'))
                        .map(el => el.textContent.trim());
        const itemVals = Array.from(document.querySelectorAll('span.item-value'))
                        .map(el => el.textContent.trim());
        return { pts: pts, itemVals: itemVals };
    }""")

    pts = data.get("pts", [])
    item_vals = data.get("itemVals", [])
    print(f"   → pts={pts}")
    print(f"   → itemVals={item_vals}")

    # pts[0] thường là sản lượng hôm nay (kWh)
    production = pts[0] if pts else (item_vals[0] if item_vals else None)
    return {"production": production}


# ─── HELPERS ─────────────────────────────────────────────────────────────────────────────
def parse_vn_number(s: str):
    """Đổi số định dạng VN ('1.234,56') sang float."""
    if not s or s.strip() in ("--", "N/A", ""):
        return None
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


# ─── FORMAT ──────────────────────────────────────────────────────────────────────────────
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
        kwh = parse_vn_number(data.get("production"))
        cap = plant["capacity"]

        if kwh is not None:
            gio_nang = round(kwh / cap, 2)
            total_kwh += kwh
            if gio_nang >= 3.68:
                nhan_xet = "Bức xạ tốt, sản lượng đạt kỳ vọng."
            else:
                nhan_xet = "Bức xạ kém, sản lượng không đạt kỳ vọng."
            prod_str = f"{kwh:,.0f} kWh"
            gio_str  = f"{gio_nang:.2f} h"
        else:
            prod_str = "N/A"
            gio_str  = "N/A"
            nhan_xet = "Không có dữ liệu."

        lines += [
            f"{emojis[i]} {plant['name']} ({cap:,.2f} kWp)",
            f"  ⚡ Sản lượng : {prod_str}",
            f"  ☀️ Giờ nắng  : {gio_str}",
            f"  📋 Nhận xét  : {nhan_xet}",
            "",
        ]

    lines += [
        "━" * 23,
        f"📊 Tổng sản lượng    : {total_kwh:,.0f} kWh",
        f"   Công suất lắp đặt : 1,100.40 kWp",
        "",
        "Trân trọng.",
    ]

    return "\n".join(lines)


# ─── TELEGRAM ─────────────────────────────────────────────────────────────────────────────────
def send_telegram(message: str) -> bool:
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
    ok   = resp.status_code == 200 and resp.json().get("ok")
    print("📤 Đã gửi Telegram!" if ok else f"❌ Lỗi Telegram: {resp.text}")
    return ok


# ─── TELEGRAM COMMAND LISTENER ─────────────────────────────────────────────────────────────────────────────
def telegram_poll():
    """Đang poll Telegram API, xử lý lệnh /baocao."""
    offset = 0
    print("📩 Telegram command listener khởi động (/baocao)")
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            resp = requests.get(url, params={"offset": offset, "timeout": 30}, timeout=35)
            if resp.status_code != 200:
                time.sleep(5)
                continue
            updates = resp.json().get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = (msg.get("text") or "").strip().lower()
                if text.startswith("/baocao"):
                    chat_id = msg.get("chat", {}).get("id")
                    print(f"📩 Lệnh /baocao từ chat_id={chat_id}")
                    requests.post(
                        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                        json={"chat_id": TELEGRAM_CHAT_ID, "text": "⏳ Đang lấy dữ liệu, vui lòng chờ..."},
                        timeout=10,
                    )
                    threading.Thread(target=run_report, daemon=True).start()
        except Exception as e:
            print(f"⚠️ Telegram poll lỗi: {e}")
            time.sleep(5)


# ─── JOB ──────────────────────────────────────────────────────────────────────────────────────
def run_report():
    tz_vn = timezone(timedelta(hours=7))
    print(f"\n{'='*50}")
    print(f"🌞 Chạy báo cáo lúc {datetime.now(tz_vn).strftime('%H:%M %d/%m/%Y')} (VN)")

    p = browser = None
    try:
        p, browser, page = login_isolar()

        results = []
        for plant in PLANTS:
            data = get_plant_data(page, plant)
            results.append((plant, data))
            time.sleep(2)

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


# ─── MAIN ───────────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🤖 KISIMEX Report Bot khởi động")
    print(f"⏰ Lịch gửi: {REPORT_TIME} UTC (= 17:00 VN) mỗi ngày")
    print("📩 Lệnh Telegram: /baocao")

    # Khởi động Telegram command listener trong background thread
    threading.Thread(target=telegram_poll, daemon=True).start()

    # Test ngay — bỏ comment dòng dưới:
    # run_report()

    schedule.every().day.at(REPORT_TIME).do(run_report)

    while True:
        schedule.run_pending()
        time.sleep(30)
