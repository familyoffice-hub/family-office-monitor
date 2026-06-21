# -*- coding: utf-8 -*-
"""
FAMILY OFFICE CONNECTOR BOT (penyambung Tools A -> Tools B)
==========================================================
Bot ini HIDUP TERUS (long polling). Tugasnya:
  1. /demo  -> kirim contoh alert Family Office LENGKAP DENGAN TOMBOL (simulasi Tools A).
  2. Saat tombol di sebuah alert diklik -> baca data alert dari TEKS pesan itu,
     panggil Tools B (advisory_generator), lalu kirim DRAFT balik ke Telegram.
  3. Cegah draft ganda jika tombol diklik berkali-kali.

Karena bot membaca data dari teks pesan yang diklik, ia bekerja untuk:
  - alert /demo dari bot ini, DAN
  - alert asli dari Tools A (asalkan alert Tools A diberi tombol - lihat README Fase 2).
"""

import os
import json
import time
import traceback
from datetime import datetime, timezone, timedelta

import requests
import advisory_generator as toolsB

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
STORE_FILE = os.getenv("STORE_FILE", "alert_store.json")
DEDUP_WINDOW_MIN = 10   # menit; cegah draft sama dibuat ulang dalam jendela ini

# Tombol: (teks tampil, kode callback)
BUTTONS = [
    ("📝 IC Memo", "gen:ic"),
    ("📨 Client Advisory", "gen:advisory"),
    ("👪 Family Briefing", "gen:family"),
    ("⚠️ Portfolio Risk", "gen:risk"),
    ("🧾 Tax/Legal Update", "gen:tax"),
    ("💼 LinkedIn Post", "gen:linkedin"),
    ("📰 Newsletter", "gen:newsletter"),
    ("📣 Telegram Post", "gen:telegram"),
    ("🎬 Video Script", "gen:video"),
    ("📸 IG Carousel", "gen:instagram"),
    ("🪜 Succession Note", "gen:succession"),
    ("🚫 Ignore", "ignore"),
]

# ============================================================================
# Penyimpanan sederhana (untuk cegah duplikat)
# ============================================================================

def load_store():
    try:
        with open(STORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_store(d):
    try:
        with open(STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[!] Gagal simpan store:", e)

def prune_store(store):
    cut = datetime.now(timezone.utc) - timedelta(days=2)
    for k in list(store.keys()):
        try:
            if datetime.fromisoformat(store[k]) < cut:
                del store[k]
        except Exception:
            pass

# ============================================================================
# Fungsi Telegram (pakai requests langsung)
# ============================================================================

def _split(text, limit=3800):
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            if cur:
                chunks.append(cur)
            cur = line
        else:
            cur = (cur + "\n" + line) if cur else line
    if cur:
        chunks.append(cur)
    return chunks

def tg(method, payload):
    try:
        r = requests.post(f"{API}/{method}", json=payload, timeout=60)
        return r.json()
    except Exception as e:
        print(f"[!] Telegram {method} error:", e)
        return {}

def send_message(chat_id, text, buttons=False, reply_to=None, parse_html=False):
    """Kirim pesan. buttons=True menambahkan tombol alert. Pesan panjang dipecah."""
    parts = _split(text)
    last = None
    for i, part in enumerate(parts):
        payload = {"chat_id": chat_id, "text": part, "disable_web_page_preview": True}
        if parse_html:
            payload["parse_mode"] = "HTML"
        if reply_to:
            payload["reply_to_message_id"] = reply_to
        # tombol hanya di bagian terakhir
        if buttons and i == len(parts) - 1:
            rows, row = [], []
            for label, data in BUTTONS:
                row.append({"text": label, "callback_data": data})
                if len(row) == 2:
                    rows.append(row); row = []
            if row:
                rows.append(row)
            payload["reply_markup"] = {"inline_keyboard": rows}
        last = tg("sendMessage", payload)
        time.sleep(0.4)
    return last

def answer_callback(cb_id, text=""):
    tg("answerCallbackQuery", {"callback_query_id": cb_id, "text": text[:180]})

# ============================================================================
# Membaca data alert dari TEKS pesan (kunci agar tanpa database)
# ============================================================================

def parse_alert(text):
    """Ambil field alert dari teks pesan Tools A / /demo.
    Mencari baris berlabel; toleran terhadap variasi kecil."""
    data = {"headline": "", "summary": "", "why_it_matters": "", "impact": "",
            "recommended_action": "", "area": "", "source_url": "", "priority": "Medium"}
    if not text:
        return data
    lines = [l.rstrip() for l in text.split("\n")]

    def after(label, line):
        return line.split(label, 1)[1].strip(" :*-")

    for i, line in enumerate(lines):
        up = line.upper()
        if not data["headline"] and line.strip() and not up.startswith("[") and "RINGKASAN AI" not in up:
            # judul = baris non-kosong pertama yang bukan tag [TYPE]
            data["headline"] = line.strip()
        if "RINGKASAN AI" in up:
            data["summary"] = after("RINGKASAN AI", line).lstrip(":")
        elif "WHY IT MATTERS" in up:
            data["why_it_matters"] = after("WHY IT MATTERS", line)
        elif up.startswith("IMPACT") or "IMPACT:" in up:
            data["impact"] = after("IMPACT", line)
        elif "RECOMMENDED ACTION" in up:
            data["recommended_action"] = after("RECOMMENDED ACTION", line)
        elif "ASSET CLASS" in up or "AREA:" in up:
            data["area"] = after(":", line) if ":" in line else line
        elif up.startswith("SOURCE"):
            # ambil URL pertama jika ada
            for tok in line.split():
                if tok.startswith("http"):
                    data["source_url"] = tok
                    break
        elif up.startswith("PRIORITY"):
            val = after("PRIORITY", line).split("|")[0].strip()
            if val:
                data["priority"] = val
    if not data["summary"]:
        data["summary"] = data["why_it_matters"] or data["headline"]
    return data

# ============================================================================
# Contoh alert (simulasi Tools A) untuk /demo
# ============================================================================

DEMO_ALERTS = [
    ("[REGULATORY UPDATE]\n"
     "Kemenkeu Umumkan Aturan Pelaporan Pajak Baru untuk HNWI\n\n"
     "📄 RINGKASAN AI: Kementerian Keuangan menambah kewajiban pelaporan aset bagi wajib pajak kaya. "
     "Aturan ini dapat memengaruhi pengungkapan aset dan perencanaan pajak keluarga.\n"
     "WHY IT MATTERS: Berdampak pada tax planning, pelaporan aset offshore, dan struktur estate.\n"
     "IMPACT: Family office perlu meninjau kepatuhan pajak, struktur holding, dan trust.\n"
     "RECOMMENDED ACTION: Diskusi dengan tax advisor & siapkan client advisory memo.\n"
     "ASSET CLASS / AREA: Tax Planning / Wealth Structuring\n"
     "SOURCE: Kemenkeu — https://example.com/regulasi-pajak\n"
     "PRIORITY: High | Score: 11"),
    ("[MACRO ALERT]\n"
     "The Fed Isyaratkan Penundaan Pemangkasan Suku Bunga\n\n"
     "📄 RINGKASAN AI: Bank sentral AS memberi sinyal suku bunga tetap tinggi lebih lama. "
     "Pasar merespons dengan kenaikan yield obligasi.\n"
     "WHY IT MATTERS: Memengaruhi yield, USD/IDR, dan strategi cash keluarga.\n"
     "IMPACT: Pertimbangkan dampak ke alokasi obligasi, kas, dan aset berbasis USD.\n"
     "RECOMMENDED ACTION: Review portfolio exposure & bahas di investment committee.\n"
     "ASSET CLASS / AREA: Macro / Bond / FX\n"
     "SOURCE: Federal Reserve — https://example.com/fed\n"
     "PRIORITY: Medium | Score: 7"),
]

def send_demo(chat_id, idx=0):
    alert = DEMO_ALERTS[idx % len(DEMO_ALERTS)]
    send_message(chat_id, alert, buttons=True)

# ============================================================================
# Penanganan klik tombol
# ============================================================================

def handle_callback(cb):
    cb_id = cb.get("id")
    data = cb.get("data", "")
    msg = cb.get("message", {}) or {}
    chat_id = msg.get("chat", {}).get("id")
    message_id = msg.get("message_id")
    text = msg.get("text", "")

    if data == "ignore":
        answer_callback(cb_id, "Diabaikan.")
        return

    if not data.startswith("gen:"):
        answer_callback(cb_id, "Tombol tidak dikenal.")
        return

    code = data.split(":", 1)[1]

    # Cegah duplikat: kunci = chat:message:kode
    store = load_store()
    key = f"{chat_id}:{message_id}:{code}"
    if key in store:
        answer_callback(cb_id, "Draft ini sudah dibuat barusan.")
        return

    answer_callback(cb_id, "Membuat draft, mohon tunggu...")

    try:
        alert = parse_alert(text)
        nama, draft = toolsB.generate_draft(code, alert)
        send_message(chat_id, draft, reply_to=message_id)
        store[key] = datetime.now(timezone.utc).isoformat()
        prune_store(store)
        save_store(store)
        print(f"[i] Draft '{nama}' dikirim ke chat {chat_id}.")
    except Exception:
        print("[!] Gagal membuat draft:")
        traceback.print_exc()
        send_message(chat_id, "Maaf, terjadi kesalahan saat membuat draft. Coba lagi.",
                     reply_to=message_id)

# ============================================================================
# Penanganan pesan biasa (perintah)
# ============================================================================

def handle_message(m):
    chat_id = m.get("chat", {}).get("id")
    text = (m.get("text") or "").strip()
    if text.startswith("/start"):
        send_message(chat_id,
            "Halo! Saya Connector Bot Family Office.\n\n"
            "Ketik /demo untuk melihat contoh alert berisi tombol.\n"
            "Klik salah satu tombol untuk membuat draft memo/advisory/konten.\n"
            "Chat ID Anda: " + str(chat_id))
    elif text.startswith("/demo"):
        send_demo(chat_id)
    elif text.startswith("/id"):
        send_message(chat_id, "Chat ID Anda: " + str(chat_id))

# ============================================================================
# Loop utama (long polling)
# ============================================================================

def main():
    if not TELEGRAM_TOKEN:
        print("[!] TELEGRAM_TOKEN belum diisi. Berhenti.")
        return
    me = tg("getMe", {})
    print("Connector Bot aktif sebagai:", me.get("result", {}).get("username", "?"))
    print("AI:", "AKTIF (" + toolsB.AI_PROVIDER + "/" + toolsB.AI_MODEL + ")" if toolsB.AI_ENABLED
          else "NONAKTIF (pakai template)")

    offset = None
    while True:
        try:
            params = {"timeout": 50}
            if offset is not None:
                params["offset"] = offset
            resp = requests.get(f"{API}/getUpdates", params=params, timeout=60).json()
            for upd in resp.get("result", []):
                offset = upd["update_id"] + 1
                if "callback_query" in upd:
                    handle_callback(upd["callback_query"])
                elif "message" in upd:
                    handle_message(upd["message"])
        except Exception:
            print("[!] Error di loop, lanjut...")
            traceback.print_exc()
            time.sleep(5)

if __name__ == "__main__":
    main()
