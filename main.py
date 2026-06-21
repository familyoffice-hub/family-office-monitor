# -*- coding: utf-8 -*-
"""
FAMILY OFFICE INTELLIGENCE MONITORING SYSTEM
============================================
Sistem ini memantau:
  1. Berita keuangan (RSS) + Google News
  2. Update regulator (The Fed, SEC, OJK, BI, DJP via Google News)
  3. Market data (indeks saham, USD/IDR, emas, minyak) via Stooq
  4. Crypto (BTC, ETH, dll) via CoinGecko
Lalu memberi skor prioritas, mencegah duplikat, dan mengirim ALERT ke Telegram.

Tidak butuh API key apa pun untuk versi MVP (Telegram token saja).

Cara jalan:
  - RUN_MODE=once  -> jalan 1 kali lalu berhenti (dipakai GitHub Actions / cron)
  - RUN_MODE=loop  -> jalan terus, ulang tiap CHECK_INTERVAL_MINUTES (Railway / laptop)
"""

import os
import json
import time
import html
import re
import csv
import io
import traceback
from datetime import datetime, timezone, timedelta

import requests
import feedparser

# Memuat file .env saat di laptop (di server, variabel diisi lewat dashboard)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ============================================================================
# BAGIAN 1 - PENGATURAN UTAMA (boleh Anda ubah-ubah)
# ============================================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
# Bisa lebih dari satu tujuan, pisahkan dengan koma. Contoh: "12345,-1009876"
TELEGRAM_CHAT_IDS = [c.strip() for c in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()]

RUN_MODE = os.getenv("RUN_MODE", "once").lower()            # "once" atau "loop"
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "60"))

# Hanya kirim alert jika skor >= angka ini (semakin tinggi = semakin sedikit & makin penting)
MIN_SCORE_TO_ALERT = int(os.getenv("MIN_SCORE_TO_ALERT", "4"))
# Jam (waktu Jakarta, 0-23) untuk mengirim ringkasan harian. -1 = matikan ringkasan.
DAILY_SUMMARY_HOUR = int(os.getenv("DAILY_SUMMARY_HOUR", "7"))

# Jeda antar pesan Telegram (detik). Grup butuh jeda lebih panjang agar tidak kena limit.
SEND_DELAY_SECONDS = int(os.getenv("SEND_DELAY_SECONDS", "4"))
# Maksimum alert berita per putaran. Sisanya ditandai "sudah dilihat" tanpa dikirim,
# supaya run pertama tidak membanjiri Telegram (anti-flood).
MAX_ALERTS_PER_CYCLE = int(os.getenv("MAX_ALERTS_PER_CYCLE", "12"))

# --- AI (opsional). Pilih penyedia: "gemini" (gratis) atau "claude". ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()

# Tentukan penyedia: pakai AI_PROVIDER jika diisi, kalau tidak deteksi dari kunci yang ada.
AI_PROVIDER = os.getenv("AI_PROVIDER", "").strip().lower()
if not AI_PROVIDER:
    if GEMINI_API_KEY:
        AI_PROVIDER = "gemini"
    elif ANTHROPIC_API_KEY:
        AI_PROVIDER = "claude"

# Model default per penyedia (boleh ditimpa lewat AI_MODEL).
_DEFAULT_MODEL = {"gemini": "gemini-2.5-flash-lite", "claude": "claude-haiku-4-5"}
AI_MODEL = os.getenv("AI_MODEL", "").strip() or _DEFAULT_MODEL.get(AI_PROVIDER, "")

AI_ENABLED = (AI_PROVIDER == "gemini" and bool(GEMINI_API_KEY)) or \
             (AI_PROVIDER == "claude" and bool(ANTHROPIC_API_KEY))

# Buat draft LinkedIn + catatan IC hanya untuk alert prioritas tinggi (hemat kuota/biaya).
AI_DRAFTS_FOR_HIGH_ONLY = os.getenv("AI_DRAFTS_FOR_HIGH_ONLY", "true").lower() == "true"
# Hemat kuota: panggil AI (ringkasan) HANYA untuk alert High. Medium/Low tetap terkirim
# tanpa memanggil AI (pakai cuplikan asli). Set "false" untuk memanggil AI di semua alert.
AI_SUMMARY_FOR_HIGH_ONLY = os.getenv("AI_SUMMARY_FOR_HIGH_ONLY", "true").lower() == "true"

# File penyimpanan riwayat (agar tidak kirim berita yang sama dua kali)
SEEN_FILE = os.getenv("SEEN_FILE", "seen.json")
STATE_FILE = os.getenv("STATE_FILE", "state.json")
SEEN_RETENTION_DAYS = 7

JAKARTA = timezone(timedelta(hours=7))   # WIB

# ============================================================================
# BAGIAN 2 - SUMBER BERITA (RSS). Tambah / kurangi sesuka Anda.
# weight = bobot kepercayaan sumber (regulator & bank sentral lebih tinggi)
# ============================================================================

def gnews(query, lang="en-US", country="US", ceid="US:en"):
    """Bikin URL Google News RSS untuk sebuah kata kunci pencarian."""
    from urllib.parse import quote
    return ("https://news.google.com/rss/search?q=" + quote(query) +
            f"&hl={lang}&gl={country}&ceid={ceid}")

RSS_FEEDS = [
    # name, url, source_weight
    ("The Fed (press)",   "https://www.federalreserve.gov/feeds/press_all.xml", 4),
    ("SEC (press)",       "https://www.sec.gov/news/pressreleases.rss",         4),
    ("CNBC Markets",      "https://www.cnbc.com/id/100003114/device/rss/rss.html", 2),
    ("CNBC Finance",      "https://www.cnbc.com/id/10000664/device/rss/rss.html",  2),

    # --- Google News: topik global ---
    ("GN Family Office",  gnews('"family office" OR "multi-family office"'), 2),
    ("GN Wealth Mgmt",    gnews('"wealth management" OR "private banking"'), 2),
    ("GN Estate/Trust",   gnews('"estate planning" OR "trust fund" OR "succession planning"'), 2),
    ("GN Fed/Rates",      gnews('Federal Reserve interest rate OR ECB rate decision'), 2),
    ("GN Crypto Reg",     gnews('crypto regulation OR stablecoin OR RWA tokenized'), 2),
    ("GN Big Managers",   gnews('BlackRock OR Vanguard OR "JP Morgan" OR Goldman Sachs outlook'), 2),
    ("GN Security",       gnews('bank failure OR crypto hack OR stablecoin depeg OR investment fraud'), 3),

    # --- Google News: Indonesia (bahasa Indonesia) ---
    ("GN OJK",            gnews('OJK peraturan investasi OR pasar modal', "id", "ID", "ID:id"), 3),
    ("GN Bank Indonesia", gnews('"Bank Indonesia" suku bunga OR kebijakan', "id", "ID", "ID:id"), 3),
    ("GN DJP/Pajak",      gnews('DJP pajak OR Kemenkeu pajak OR PPATK', "id", "ID", "ID:id"), 3),
    ("GN Family Office ID", gnews('family office Indonesia OR wealth management Indonesia', "id", "ID", "ID:id"), 2),
]

# ============================================================================
# BAGIAN 3 - KATA KUNCI MONITORING (dengan bobot skor per kategori)
# ============================================================================

KEYWORDS = {
    "Family Office":        (["family office", "multi-family office", "single family office", "private wealth", "ultra high net worth", "uhnwi", "hnwi"], 3),
    "Wealth Management":    (["wealth management", "asset allocation", "portfolio", "rebalancing", "wealth preservation"], 2),
    "Private Banking":      (["private banking", "private bank"], 2),
    "Tax Planning":         (["tax planning", "tax", "pajak", "dividen", "pph", "ppn", "beneficial ownership", "transfer pricing", "tax treaty"], 2),
    "Estate & Trust":       (["estate planning", "trust", "inheritance", "warisan", "estate"], 3),
    "Succession":           (["succession planning", "succession", "wealth transfer", "generational wealth", "next generation"], 3),
    "Family Governance":    (["family governance", "family constitution", "family business"], 2),
    "Alternative Invest":   (["private equity", "venture capital", "private credit", "hedge fund", "infrastructure fund", "alternative investment"], 2),
    "Real Estate":          (["real estate", "property", "reit"], 1),
    "Gold & Commodities":   (["gold", "emas", "commodities", "oil", "minyak", "treasury"], 1),
    "Bond & Yield":         (["bond", "yield", "sbn", "obligasi", "us treasury"], 1),
    "Crypto & Digital":     (["crypto", "bitcoin", "ethereum", "stablecoin", "digital asset", "tokenized", "rwa", "defi"], 2),
    "Indonesia Regulator":  (["ojk", "bank indonesia", "djp", "kemenkeu", "kementerian keuangan", "ppatk", "ihsg", "idx", "bei"], 4),
    "Global Regulator":     (["sec", "mas", "sfc", "fca", "finma", "oecd", "fatca", "crs", "irs", "central bank"], 3),
    "Macro":                (["federal reserve", "the fed", "interest rate", "suku bunga", "inflation", "inflasi", "recession", "rate cut", "rate hike"], 2),
    "Big Institution":      (["blackrock", "vanguard", "jp morgan", "jpmorgan", "goldman sachs", "morgan stanley", "ubs", "julius baer", "fidelity", "franklin templeton", "citi private bank"], 3),
    "Security Risk":        (["fraud", "scam", "ponzi", "hack", "bank failure", "custodian", "depeg", "sanction", "aml", "money laundering", "cyberattack", "phishing", "deepfake", "tax investigation"], 5),
}

# Kata-kata "high priority" -> langsung prioritas tinggi
HIGH_PRIORITY_WORDS = ["fraud", "hack", "bank failure", "depeg", "sanction", "ponzi",
                       "tax investigation", "money laundering", "cyberattack", "deepfake",
                       "market crash", "collapse"]

# ============================================================================
# BAGIAN 4 - MARKET DATA (Stooq, tanpa API key)
#   Kita hitung pergerakan hari ini = (close - open) / open  (perkiraan sederhana)
#   symbol Stooq: ^spx S&P500, ^ndq Nasdaq, ^dji Dow, ^nkx Nikkei, ^hsi HangSeng
#   usdidr USD/IDR, xauusd Emas, cl.f Minyak WTI
# ============================================================================

MARKET_TICKERS = [
    # label, stooq_symbol, threshold_persen (alert jika |gerakan| >= ini)
    ("S&P 500",   "^spx",   2.0),
    ("Nasdaq",    "^ndq",   2.5),
    ("Dow Jones", "^dji",   2.0),
    ("Nikkei",    "^nkx",   2.5),
    ("Hang Seng", "^hsi",   2.5),
    ("USD/IDR",   "usdidr", 1.0),
    ("Emas (Gold)", "xauusd", 2.0),
    ("Minyak WTI",  "cl.f",   3.0),
]

# Crypto via CoinGecko (tanpa key). id CoinGecko: bitcoin, ethereum, tether, dll.
CRYPTO_COINS = [
    # label, coingecko_id, threshold_persen_24jam
    ("Bitcoin",  "bitcoin",  5.0),
    ("Ethereum", "ethereum", 6.0),
    ("Tether (depeg watch)", "tether", 1.0),
]

# ============================================================================
# BAGIAN 5 - FUNGSI BANTU: simpan / muat file
# ============================================================================

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Gagal menyimpan", path, e)

# ============================================================================
# BAGIAN 6 - SKORING
# ============================================================================

def make_pattern(word):
    """Regex agar 'fed' tidak cocok dengan 'feed'. Cocokkan sebagai kata utuh."""
    return r"(?<![a-z])" + re.escape(word.lower()) + r"(?![a-z])"

def score_text(text):
    """Hitung skor + daftar kategori yang cocok dari sebuah teks berita."""
    text_l = " " + text.lower() + " "
    score = 0
    matched = []
    for category, (words, weight) in KEYWORDS.items():
        for w in words:
            if re.search(make_pattern(w), text_l):
                score += weight
                matched.append(category)
                break  # cukup 1 kata per kategori
    is_high = any(re.search(make_pattern(w), text_l) for w in HIGH_PRIORITY_WORDS)
    if is_high:
        score += 4
    return score, list(dict.fromkeys(matched)), is_high

def recency_bonus(published_dt):
    """Tambah skor jika berita < 6 jam."""
    if not published_dt:
        return 0
    age_hours = (datetime.now(timezone.utc) - published_dt).total_seconds() / 3600
    if age_hours <= 6:
        return 2
    if age_hours <= 24:
        return 1
    return 0

def decide_alert_type(matched, is_high):
    if is_high:
        return "SECURITY WARNING"
    order = [
        ("Indonesia Regulator", "REGULATORY UPDATE"),
        ("Global Regulator",    "REGULATORY UPDATE"),
        ("Tax Planning",        "TAX UPDATE"),
        ("Family Office",       "FAMILY OFFICE INSIGHT"),
        ("Succession",          "SUCCESSION PLANNING"),
        ("Estate & Trust",      "TRUST & ESTATE"),
        ("Private Banking",     "PRIVATE BANKING"),
        ("Crypto & Digital",    "CRYPTO / RWA"),
        ("Macro",               "MACRO ALERT"),
        ("Big Institution",     "PORTFOLIO INSIGHT"),
        ("Alternative Invest",  "INVESTMENT OPPORTUNITY"),
    ]
    for cat, label in order:
        if cat in matched:
            return label
    return "MARKET INTELLIGENCE"

def priority_from_score(score, is_high):
    if is_high or score >= 9:
        return "High"
    if score >= 6:
        return "Medium"
    return "Low"

# ============================================================================
# BAGIAN 7 - FORMAT & KIRIM TELEGRAM
# ============================================================================

def tg_escape(s):
    """Telegram HTML mode: escape karakter < > &."""
    return html.escape(s or "")

# Tombol untuk menghubungkan ke Connector Bot (Tools B).
# callback_data HARUS sama dengan yang dikenali Connector Bot.
ADVISORY_BUTTONS = [
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

def _build_keyboard():
    rows, row = [], []
    for label, data in ADVISORY_BUTTONS:
        row.append({"text": label, "callback_data": data})
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    return {"inline_keyboard": rows}

def _split_message(text, limit=3800):
    """Pecah pesan panjang menjadi beberapa bagian agar tidak melebihi batas Telegram."""
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            if current:
                chunks.append(current)
            current = line
        else:
            current = (current + "\n" + line) if current else line
    if current:
        chunks.append(current)
    return chunks

def send_telegram(message, buttons=False):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_IDS:
        print("[!] TELEGRAM_TOKEN / TELEGRAM_CHAT_IDS belum diisi. Pesan tidak terkirim.")
        print(message)
        return False
    ok_all = True
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        parts = _split_message(message)
        for idx, part in enumerate(parts):
            sent = False
            # Coba sampai 4 kali. Jika kena 429, tunggu sesuai 'retry_after' lalu ulang.
            for attempt in range(4):
                try:
                    data = {
                        "chat_id": chat_id,
                        "text": part,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": "true",
                    }
                    # Tombol hanya pada bagian terakhir pesan.
                    if buttons and idx == len(parts) - 1:
                        data["reply_markup"] = json.dumps(_build_keyboard())
                    r = requests.post(url, data=data, timeout=20)
                    if r.status_code == 200:
                        sent = True
                        break
                    if r.status_code == 429:
                        try:
                            wait = r.json().get("parameters", {}).get("retry_after", 5)
                        except Exception:
                            wait = 5
                        print(f"[i] Kena limit (429) untuk {chat_id}, tunggu {wait}s lalu coba lagi...")
                        time.sleep(int(wait) + 1)
                        continue
                    # error lain (mis. 400/403): jangan diulang, catat saja
                    print("[!] Telegram error", chat_id, r.status_code, r.text[:200])
                    break
                except Exception as e:
                    print("[!] Telegram exception", e)
                    time.sleep(3)
            if not sent:
                ok_all = False
    return ok_all

# ----------------------------------------------------------------------------
# FUNGSI AI (opsional) - ringkasan & draft konten memakai Claude API
# ----------------------------------------------------------------------------

def call_claude(system, user, max_tokens=700):
    """Panggil Claude API. Return teks balasan, atau None jika gagal."""
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": AI_MODEL,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
            timeout=40,
        )
        if r.status_code != 200:
            print("[!] Claude API error", r.status_code, r.text[:200])
            return None
        data = r.json()
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        return "\n".join(parts).strip()
    except Exception as e:
        print("[!] Claude API exception", e)
        return None

def call_gemini(system, user, max_tokens=700):
    """Panggil Gemini API (gratis). Return teks balasan, atau None jika gagal."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{AI_MODEL}:generateContent"
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.4,
            # Matikan "thinking" pada Gemini 2.5 agar token tidak habis & balasan tidak kosong.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    for attempt in range(4):
        try:
            r = requests.post(
                url,
                headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
                json=body, timeout=40,
            )
            if r.status_code == 200:
                data = r.json()
                cands = data.get("candidates", [])
                if not cands:
                    print("[!] Gemini: tidak ada candidates (mungkin diblok filter).")
                    return None
                parts = cands[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts).strip()
                if not text:
                    fr = cands[0].get("finishReason", "?")
                    print(f"[!] Gemini: balasan kosong (finishReason={fr}).")
                    return None
                return text
            if r.status_code == 429:
                print("[i] Gemini limit (429), tunggu 25s lalu coba lagi...")
                time.sleep(25)
                continue
            if r.status_code in (500, 502, 503, 504):
                # Server Gemini sedang penuh/sibuk: coba lagi dengan jeda bertambah.
                wait = 8 * (attempt + 1)
                print(f"[i] Gemini sibuk ({r.status_code}), tunggu {wait}s lalu coba lagi...")
                time.sleep(wait)
                continue
            print("[!] Gemini API error", r.status_code, r.text[:300])
            return None
        except Exception as e:
            print("[!] Gemini API exception", e)
            time.sleep(5)
    print("[i] Gemini tetap gagal setelah beberapa percobaan; alert dikirim tanpa ringkasan AI.")
    return None

def call_ai(system, user, max_tokens=700):
    """Arahkan ke penyedia AI yang aktif."""
    if not AI_ENABLED:
        return None
    if AI_PROVIDER == "gemini":
        return call_gemini(system, user, max_tokens)
    return call_claude(system, user, max_tokens)

def ai_enrich(item):
    """Minta AI: ringkasan 2 kalimat + why + (opsional) draft LinkedIn & memo IC.
    Mengembalikan dict, atau None jika AI mati/gagal (program tetap jalan tanpa AI)."""
    if not AI_ENABLED:
        return None

    # HEMAT KUOTA: untuk alert non-High, jangan panggil AI sama sekali.
    if AI_SUMMARY_FOR_HIGH_ONLY and item.get("priority") != "High":
        return None

    want_drafts = (not AI_DRAFTS_FOR_HIGH_ONLY) or (item["priority"] == "High")
    area = ", ".join(item["matched"][:4]) if item["matched"] else "wealth management"

    system = (
        "Anda analis senior di sebuah Family Office di Indonesia. "
        "Anda menulis ringkas, tajam, dan praktis dalam Bahasa Indonesia. "
        "Anda hanya punya JUDUL + cuplikan singkat berita, bukan artikel penuh, "
        "jadi JANGAN mengarang angka, kutipan, atau detail spesifik yang tidak ada. "
        "Jika detail tidak pasti, tetap umum namun berguna."
    )

    draft_instr = ""
    if want_drafts:
        draft_instr = (
            ', "linkedin": "<draft LinkedIn post 4-6 kalimat, profesional, '
            'sudut pandang wealth/family office, tanpa tagar berlebihan>", '
            '"ic_memo": "<3-4 poin singkat untuk catatan investment committee: '
            'observasi, dampak, usulan tindakan>"'
        )
    else:
        draft_instr = ', "linkedin": "", "ic_memo": ""'

    user = (
        f"JUDUL: {item['title']}\n"
        f"SUMBER: {item['source']}\n"
        f"AREA TERKAIT: {area}\n"
        f"PRIORITAS: {item['priority']}\n\n"
        "Balas HANYA dalam format JSON valid (tanpa teks lain, tanpa ```), persis:\n"
        '{"ringkasan": "<2 kalimat ringkas apa isi berita ini>", '
        '"why": "<1 kalimat: kenapa ini penting bagi family office/investor/keluarga bisnis>"'
        + draft_instr + "}"
    )

    raw = call_ai(system, user, max_tokens=900 if want_drafts else 350)
    if not raw:
        return None
    # Bersihkan jika model membungkus dengan ```
    raw = re.sub(r"^```(json)?", "", raw.strip())
    raw = re.sub(r"```$", "", raw.strip()).strip()
    try:
        return json.loads(raw)
    except Exception as e:
        print("[!] Gagal baca JSON AI:", e)
        return None

def format_news_alert(item, enrich=None):
    matched = item["matched"]
    area = " / ".join(matched[:4]) if matched else "General"
    content_idea = "LinkedIn post / Newsletter" 
    if "Indonesia Regulator" in matched or "Global Regulator" in matched:
        content_idea = "Client advisory memo / Executive briefing"
    elif "Security Risk" in matched or item["is_high"]:
        content_idea = "Internal risk note / Family briefing"
    elif "Family Office" in matched:
        content_idea = "LinkedIn post / Instagram carousel"

    action = "Monitor only"
    if item["is_high"]:
        action = "Escalate to principal / Discuss in investment committee"
    elif item["priority"] == "High":
        action = "Discuss in investment committee / Review portfolio exposure"
    elif item["priority"] == "Medium":
        action = "Review exposure / Prepare client memo"

    # Jika AI aktif, pakai ringkasan & alasan dari AI. Jika tidak, pakai teks default.
    ai_ringkasan = _as_text(enrich.get("ringkasan")) if enrich else ""
    if ai_ringkasan:
        why = _as_text(enrich.get("why")) or f"Menyentuh area {area}."
        summary_block = [
            f"📄 <b>RINGKASAN AI:</b> {tg_escape(ai_ringkasan)}",
            f"<b>WHY IT MATTERS:</b> {tg_escape(why)}",
        ]
    else:
        summary_block = [
            f"<b>WHY IT MATTERS:</b> Relevan untuk Family Office / investor: menyentuh area {tg_escape(area)}.",
            f"<b>IMPACT:</b> Berpotensi memengaruhi {tg_escape(area)} dalam portfolio / struktur keluarga.",
        ]

    lines = [
        f"<b>[{item['alert_type']}]</b>",
        f"<b>{tg_escape(item['title'])}</b>",
        "",
    ] + summary_block + [
        f"<b>RECOMMENDED ACTION:</b> {tg_escape(action)}",
        f"<b>ASSET CLASS / AREA:</b> {tg_escape(area)}",
        f"<b>SOURCE:</b> {tg_escape(item['source'])} — {tg_escape(item['link'])}",
        f"<b>CONTENT IDEA:</b> {tg_escape(content_idea)}",
        f"<b>PRIORITY:</b> {item['priority']}  |  Score: {item['score']}",
    ]
    return "\n".join(lines)

def _as_text(value):
    """Ubah nilai dari AI menjadi teks, apa pun bentuknya (str, list, dict, None)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for v in value:
            if isinstance(v, str):
                parts.append(v)
            elif isinstance(v, dict):
                parts.append(" ".join(str(x) for x in v.values()))
            else:
                parts.append(str(v))
        return "\n".join(p.strip() for p in parts if p).strip()
    if isinstance(value, dict):
        return "\n".join(f"{k}: {v}" for k, v in value.items()).strip()
    return str(value).strip()

def format_drafts_message(item, enrich):
    """Pesan kedua khusus berisi draft konten (LinkedIn + catatan IC) dari AI."""
    if not enrich:
        return None
    linkedin = _as_text(enrich.get("linkedin"))
    ic_memo = _as_text(enrich.get("ic_memo"))
    if not linkedin and not ic_memo:
        return None
    lines = [f"✍️ <b>DRAFT KONTEN</b> — {tg_escape(item['title'][:80])}"]
    if linkedin:
        lines += ["", "<b>LinkedIn post:</b>", tg_escape(linkedin)]
    if ic_memo:
        lines += ["", "<b>Catatan Investment Committee:</b>", tg_escape(ic_memo)]
    return "\n".join(lines)

def format_market_alert(label, pct, kind="MARKET"):
    arrow = "🔻" if pct < 0 else "🔺"
    atype = "PORTFOLIO RISK" if kind == "MARKET" else "CRYPTO RISK"
    prio = "High" if abs(pct) >= 4 else "Medium"
    lines = [
        f"<b>[{atype}]</b>",
        f"<b>{arrow} {tg_escape(label)} bergerak {pct:+.2f}% hari ini</b>",
        "",
        "<b>WHY IT MATTERS:</b> Pergerakan signifikan dapat memengaruhi nilai portfolio keluarga.",
        "<b>IMPACT:</b> Pertimbangkan dampak ke asset allocation & cash management.",
        "<b>RECOMMENDED ACTION:</b> Review portfolio exposure / Discuss in investment committee",
        f"<b>ASSET CLASS / AREA:</b> {tg_escape(label)}",
        "<b>SOURCE:</b> Stooq / CoinGecko (market data)",
        "<b>CONTENT IDEA:</b> Internal market intelligence note",
        f"<b>PRIORITY:</b> {prio}",
    ]
    return "\n".join(lines)

# ============================================================================
# BAGIAN 8 - AMBIL BERITA RSS
# ============================================================================

def parse_published(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    return None

def collect_news():
    results = []
    for name, url, weight in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:25]:
                title = entry.get("title", "").strip()
                summary = re.sub("<[^>]+>", " ", entry.get("summary", ""))[:400]
                link = entry.get("link", "")
                if not title or not link:
                    continue
                pub = parse_published(entry)
                base_score, matched, is_high = score_text(title + " " + summary)
                if base_score == 0:
                    continue
                total = base_score + weight + recency_bonus(pub)
                results.append({
                    "title": title,
                    "link": link,
                    "source": name,
                    "matched": matched,
                    "is_high": is_high,
                    "score": total,
                    "published": pub,
                    "alert_type": decide_alert_type(matched, is_high),
                    "priority": priority_from_score(total, is_high),
                })
        except Exception as e:
            print(f"[!] Gagal baca feed {name}: {e}")
    return results

# ============================================================================
# BAGIAN 9 - AMBIL MARKET DATA
# ============================================================================

def fetch_stooq(symbol):
    """Ambil quote dari Stooq. Return (open, close) atau None."""
    url = f"https://stooq.com/q/l/?s={symbol}&f=sd2t2ohlc&e=csv"
    try:
        r = requests.get(url, timeout=20)
        if r.status_code != 200:
            return None
        reader = csv.reader(io.StringIO(r.text.strip()))
        rows = list(reader)
        if len(rows) < 2:
            return None
        header, data = rows[0], rows[1]
        d = dict(zip([h.lower() for h in header], data))
        o = float(d.get("open"))
        c = float(d.get("close"))
        if o <= 0:
            return None
        return o, c
    except Exception as e:
        print("[!] Stooq error", symbol, e)
        return None

def check_market(seen):
    alerts = []
    today = datetime.now(JAKARTA).strftime("%Y-%m-%d")
    for label, symbol, threshold in MARKET_TICKERS:
        data = fetch_stooq(symbol)
        if not data:
            continue
        o, c = data
        pct = (c - o) / o * 100
        if abs(pct) >= threshold:
            key = f"market::{symbol}::{today}"
            if key not in seen:
                alerts.append(format_market_alert(label, pct, "MARKET"))
                seen[key] = datetime.now(timezone.utc).isoformat()
    return alerts

def check_crypto(seen):
    alerts = []
    today = datetime.now(JAKARTA).strftime("%Y-%m-%d")
    ids = ",".join(c[1] for c in CRYPTO_COINS)
    url = ("https://api.coingecko.com/api/v3/simple/price?ids=" + ids +
           "&vs_currencies=usd&include_24hr_change=true")
    try:
        r = requests.get(url, timeout=20)
        if r.status_code != 200:
            print("[!] CoinGecko error", r.status_code)
            return alerts
        data = r.json()
    except Exception as e:
        print("[!] CoinGecko exception", e)
        return alerts
    for label, cid, threshold in CRYPTO_COINS:
        info = data.get(cid)
        if not info:
            continue
        pct = info.get("usd_24h_change", 0) or 0
        # khusus stablecoin: alert jika menjauh dari 0 (depeg) walau threshold kecil
        if abs(pct) >= threshold:
            key = f"crypto::{cid}::{today}"
            if key not in seen:
                alerts.append(format_market_alert(label + " (24h)", pct, "CRYPTO"))
                seen[key] = datetime.now(timezone.utc).isoformat()
    return alerts

# ============================================================================
# BAGIAN 10 - RINGKASAN HARIAN
# ============================================================================

def _safe_dt(s):
    """Parse waktu ISO dengan aman; jika gagal, kembalikan waktu sangat lampau."""
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)

def record_daily(seen, item):
    """Catat ringkas setiap alert yang terkirim, untuk bahan Daily Digest."""
    log = seen.get("__daily_log__")
    if not isinstance(log, list):
        log = []
        seen["__daily_log__"] = log
    log.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "title": item.get("title", ""),
        "source": item.get("source", ""),
        "area": " / ".join(item.get("matched", [])[:3]) if item.get("matched") else "General",
        "priority": item.get("priority", "Low"),
        "alert_type": item.get("alert_type", ""),
    })

def build_digest_message(now, items):
    """Bangun pesan Daily Digest. Pakai AI bila aktif; jika tidak, daftar ringkas."""
    tanggal = now.strftime("%d %b %Y")
    if not items:
        return (f"<b>📋 DAILY DIGEST</b> — {tanggal}\n\n"
                "Tidak ada alert signifikan dalam 24 jam terakhir.")

    # Urutkan: High dulu
    pr = {"High": 0, "Medium": 1, "Low": 2}
    items = sorted(items, key=lambda r: pr.get(r.get("priority"), 3))[:40]

    # --- Versi AI ---
    if AI_ENABLED:
        daftar = "\n".join(
            f"- [{r.get('priority')}] {r.get('title')} (area: {r.get('area')}, sumber: {r.get('source')})"
            for r in items
        )
        system = (
            "Anda Chief Investment Officer sebuah Family Office di Indonesia. "
            "Tulis executive briefing harian dalam Bahasa Indonesia yang ringkas, tajam, dan rapi. "
            "Anda hanya punya daftar judul alert, bukan artikel penuh — jangan mengarang angka/detail. "
            "Gunakan HTML sederhana Telegram: <b>...</b> untuk judul bagian (JANGAN pakai #, *, atau tabel)."
        )
        user = (
            f"Tanggal: {tanggal}. Berikut {len(items)} alert penting 24 jam terakhir:\n\n"
            f"{daftar}\n\n"
            "Buat executive briefing dengan struktur:\n"
            "1. Kalimat pembuka (1-2 kalimat: gambaran besar hari ini).\n"
            "2. Kelompokkan temuan ke bagian relevan saja (pilih dari): "
            "<b>Makro & Pasar</b>, <b>Regulasi & Pajak</b>, <b>Family Office & Wealth</b>, "
            "<b>Risiko & Keamanan</b>, <b>Peluang Investasi</b>. "
            "Tiap bagian 1-3 poin singkat (pakai tanda '•').\n"
            "3. <b>Fokus / Rekomendasi</b>: 2-3 tindakan prioritas untuk minggu ini.\n"
            "Total maksimal sekitar 350 kata. Jangan mengulang judul mentah; sarikan."
        )
        ai = call_ai(system, user, max_tokens=1400)
        if ai:
            return (f"<b>📋 DAILY DIGEST</b> — {tanggal}\n"
                    f"<i>{len(items)} alert penting · 24 jam terakhir</i>\n\n{ai}")

    # --- Versi tanpa AI (daftar ringkas) ---
    by_pr = {"High": [], "Medium": [], "Low": []}
    for r in items:
        by_pr.get(r.get("priority"), by_pr["Low"]).append(r)
    lines = [f"<b>📋 DAILY DIGEST</b> — {tanggal}",
             f"<i>{len(items)} alert penting · 24 jam terakhir</i>"]
    for label in ("High", "Medium", "Low"):
        rows = by_pr[label]
        if not rows:
            continue
        lines.append(f"\n<b>{label} priority ({len(rows)})</b>")
        for r in rows[:15]:
            lines.append(f"• {tg_escape(r.get('title',''))} — <i>{tg_escape(r.get('area',''))}</i>")
    lines.append("\nGunakan untuk bahan investment committee / family briefing.")
    return "\n".join(lines)

def maybe_daily_digest(seen):
    """Kirim Daily Digest sekali sehari pada jam DAILY_SUMMARY_HOUR (WIB)."""
    if DAILY_SUMMARY_HOUR < 0:
        return
    now = datetime.now(JAKARTA)
    if now.hour != DAILY_SUMMARY_HOUR:
        return
    key = "digest::" + now.strftime("%Y-%m-%d")
    if key in seen:
        return  # sudah dikirim hari ini
    log = seen.get("__daily_log__", [])
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    items, titles = [], set()
    for r in log:
        if not isinstance(r, dict) or _safe_dt(r.get("ts")) < cutoff:
            continue
        t = r.get("title", "")
        if t and t not in titles:
            titles.add(t)
            items.append(r)
    msg = build_digest_message(now, items)
    if msg and send_telegram(msg):
        seen[key] = datetime.now(timezone.utc).isoformat()
        print(f"[i] Daily digest terkirim ({len(items)} item).")

# ============================================================================
# BAGIAN 11 - SATU SIKLUS PEMERIKSAAN
# ============================================================================

def prune_seen(seen):
    cutoff = datetime.now(timezone.utc) - timedelta(days=SEEN_RETENTION_DAYS)
    for k in list(seen.keys()):
        if k == "__daily_log__":
            continue  # ini daftar untuk digest, ditangani terpisah
        try:
            if datetime.fromisoformat(seen[k]) < cutoff:
                del seen[k]
        except Exception:
            pass
    # Pangkas catatan harian agar tidak menumpuk (simpan 3 hari terakhir).
    log = seen.get("__daily_log__")
    if isinstance(log, list):
        dcut = datetime.now(timezone.utc) - timedelta(days=3)
        seen["__daily_log__"] = [r for r in log
                                 if isinstance(r, dict) and _safe_dt(r.get("ts")) >= dcut]

# ============================================================================
# FASE 2 — kirim alert High ke inbox.json Orchestrator (papan tulis bersama)
# ============================================================================
ORCH_REPO = os.getenv("ORCH_REPO", "").strip()            # "user/family-office-orchestrator"
GH_PUSH_TOKEN = os.getenv("GH_PUSH_TOKEN", "").strip()    # PAT fine-grained, Contents: RW
ORCH_INBOX_PATH = os.getenv("ORCH_INBOX_PATH", "inbox.json")

def push_to_orchestrator(rows):
    """Tambahkan beberapa baris ke inbox.json repo orchestrator via GitHub API (1 commit)."""
    if not ORCH_REPO or not GH_PUSH_TOKEN or not rows:
        if rows and not (ORCH_REPO and GH_PUSH_TOKEN):
            print("[i] ORCH_REPO/GH_PUSH_TOKEN belum diset -> lewati push ke orchestrator.")
        return
    import base64
    url = f"https://api.github.com/repos/{ORCH_REPO}/contents/{ORCH_INBOX_PATH}"
    headers = {"Authorization": f"Bearer {GH_PUSH_TOKEN}", "Accept": "application/vnd.github+json"}
    try:
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 200:
            data = r.json(); sha = data["sha"]
            content = json.loads(base64.b64decode(data["content"]).decode("utf-8"))
            if not isinstance(content, list):
                content = []
        else:
            sha = None; content = []
        content.extend(rows)
        content = content[-1000:]
        new_b64 = base64.b64encode(json.dumps(content, ensure_ascii=False, indent=2).encode()).decode()
        payload = {"message": f"Tools A: +{len(rows)} alert High ke inbox", "content": new_b64}
        if sha:
            payload["sha"] = sha
        pr = requests.put(url, headers=headers, json=payload, timeout=20)
        if pr.status_code in (200, 201):
            print(f"[i] {len(rows)} alert High dikirim ke Orchestrator inbox.")
        else:
            print("[!] Gagal push ke orchestrator:", pr.status_code, pr.text[:150])
    except Exception as e:
        print("[!] Exception push ke orchestrator:", e)

def _orch_row(item, enrich):
    summary = ""
    if isinstance(enrich, dict):
        summary = _as_text(enrich.get("summary") or enrich.get("why") or "")
    if not summary:
        summary = _as_text(item.get("summary") or item.get("title") or "")
    return {
        "output_id": "o" + format(int(time.time() * 1000) % 10_000_000, "x"),
        "agent_id": "Tools A Monitor",
        "title": _as_text(item.get("title", "")),
        "summary": summary[:600],
        "raw_output": "",
        "source_url": item.get("link", ""),
        "category": item.get("area", ""),
        "confidentiality_level": "internal",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_processed": False,
    }

def run_cycle():
    print("=" * 60)
    print("Mulai siklus:", datetime.now(JAKARTA).strftime("%Y-%m-%d %H:%M:%S WIB"))
    # --- Diagnostik AI: tampil jelas di log ---
    if AI_ENABLED:
        klen = len(GEMINI_API_KEY) if AI_PROVIDER == "gemini" else len(ANTHROPIC_API_KEY)
        print(f"AI: AKTIF | provider={AI_PROVIDER} | model={AI_MODEL} | panjang_kunci={klen}")
        test = call_ai("Jawab singkat.", "Balas satu kata: OK", max_tokens=50)
        print("AI TEST:", ("BERHASIL -> " + test[:40]) if test else "GAGAL (lihat baris [!] di atas/bawah)")
    else:
        print(f"AI: NONAKTIF | provider={AI_PROVIDER or 'kosong'} | "
              f"gemini_key={'ada' if GEMINI_API_KEY else 'kosong'} | "
              f"anthropic_key={'ada' if ANTHROPIC_API_KEY else 'kosong'}")
    seen = load_json(SEEN_FILE, {})
    sent_today = []

    # 1) Berita
    news = collect_news()
    news = [n for n in news if n["score"] >= MIN_SCORE_TO_ALERT]
    news.sort(key=lambda x: x["score"], reverse=True)

    # Ambil hanya yang BELUM pernah dikirim
    fresh = [n for n in news if ("news::" + (n["link"] or n["title"])) not in seen]

    # ANTI-FLOOD: kirim maksimal MAX_ALERTS_PER_CYCLE (yang skornya tertinggi).
    # Sisanya ditandai "sudah dilihat" TANPA dikirim, agar tidak membanjiri & tidak diulang.
    to_send = fresh[:MAX_ALERTS_PER_CYCLE]
    to_skip = fresh[MAX_ALERTS_PER_CYCLE:]
    for item in to_skip:
        uid = "news::" + (item["link"] or item["title"])
        seen[uid] = datetime.now(timezone.utc).isoformat()
    if to_skip:
        print(f"[i] {len(to_skip)} berita lama dilewati (anti-flood), ditandai sudah dilihat.")

    orch_rows = []  # Fase 2: kumpulkan alert High untuk dikirim ke Orchestrator
    for item in to_send:
        uid = "news::" + (item["link"] or item["title"])
        enrich = ai_enrich(item)   # None jika AI mati / gagal -> alert tetap terkirim
        ok = send_telegram(format_news_alert(item, enrich), buttons=True)
        # Tandai sudah-dilihat apa pun hasilnya, supaya tidak dikirim berulang tiap jam.
        seen[uid] = datetime.now(timezone.utc).isoformat()
        if ok:
            sent_today.append(item)
            record_daily(seen, item)   # catat untuk Daily Digest
            if item.get("priority") == "High":
                orch_rows.append(_orch_row(item, enrich))
            # Kirim draft konten (LinkedIn + memo IC) sebagai pesan terpisah, jika ada.
            drafts = format_drafts_message(item, enrich)
            if drafts:
                time.sleep(SEND_DELAY_SECONDS)
                send_telegram(drafts)
        save_json(SEEN_FILE, seen)   # simpan bertahap agar aman bila run terhenti
        time.sleep(SEND_DELAY_SECONDS)

    # Fase 2: kirim semua alert High ke inbox Orchestrator dalam 1 commit.
    push_to_orchestrator(orch_rows)

    # 2) Market data
    for msg in check_market(seen):
        send_telegram(msg)
        time.sleep(SEND_DELAY_SECONDS)

    # 3) Crypto
    for msg in check_crypto(seen):
        send_telegram(msg)
        time.sleep(SEND_DELAY_SECONDS)

    # 4) Daily Digest (executive briefing, sekali sehari)
    maybe_daily_digest(seen)

    prune_seen(seen)
    save_json(SEEN_FILE, seen)
    print(f"Selesai. Alert berita terkirim: {len(sent_today)}")

# ============================================================================
# BAGIAN 12 - TITIK MASUK PROGRAM
# ============================================================================

def main():
    print("Family Office Monitor — mode:", RUN_MODE)
    if RUN_MODE == "loop":
        while True:
            try:
                run_cycle()
            except Exception:
                print("[!] Error pada siklus:")
                traceback.print_exc()
            print(f"Tidur {CHECK_INTERVAL_MINUTES} menit...\n")
            time.sleep(CHECK_INTERVAL_MINUTES * 60)
    else:  # once
        try:
            run_cycle()
        except Exception:
            print("[!] Error:")
            traceback.print_exc()

if __name__ == "__main__":
    main()
