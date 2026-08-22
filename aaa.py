# =====================================================================
# BUXGALTERIYA HISOB-KITOB TELEGRAM BOTI
# =====================================================================
# ISHGA TUSHIRISH:
#   1) python3 -m venv venv
#      source venv/bin/activate        (Windows: venv\Scripts\activate)
#   2) pip install python-telegram-bot pillow
#   3) Pastdagi BOT_TOKEN qatoriga @BotFather bergan tokeningizni yozing
#   4) python3 bot.py
#   5) Telegram'da botga /start yuboring.
# =====================================================================

# 👇 BOT TOKENNI SHU YERGA YOZING (tirnoqlar ichida)
BOT_TOKEN = "8612213994:AAFqPR7TxDFdqMTZTWNXv0vcAg6bbRzWvOM"

import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)


# =====================================================================
# Render.com'ning bepul "Web Service" tarifi ishlashi uchun portni
# tinglab turadigan soxta HTTP server. Bot o'zi Telegram bilan
# "polling" orqali ishlaydi, lekin Render web-service HTTP porti ochiq
# turishini talab qiladi — shuning uchun fonda shu kichik serverni
# ham ishga tushiramiz.
# =====================================================================
class _PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot ishlayapti")

    def log_message(self, format, *args):
        pass  # konsolni keraksiz log bilan to'ldirmaslik uchun


def start_ping_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), _PingHandler)
    server.serve_forever()

# =====================================================================
# 2) Excel jadvalidan olingan mahsulotlar (Goods / composition / Expiry /
#    packs / Price / 12% QQS / VAT bilan narx). Faqat "Soni" (miqdor)
#    ustunini bot orqali kiritamiz — xuddi Excel'dagi aa/bb/cc/gg
#    kataklariga son yozgandek.
# =====================================================================
PRODUCTS = [
    {
        "code": "aa",
        "name": "Cardoz 25 mg Tab",
        "composition": "Carvedilol",
        "expiry": "Nov.26",
        "packs": "2x14 Tab",
        "price": 84235.05,
    },
    {
        "code": "bb",
        "name": "Cartiflex  №10 Sachet",
        "composition": "collagen peptide",
        "expiry": "Nov.26",
        "packs": "10 Sachet",
        "price": 133928.57,
    },
    {
        "code": "cc",
        "name": "Nutrifiber 200 mg tab",
        "composition": "Inulin, Maltodextrin, PHGG",
        "expiry": "Nov.27",
        "packs": "200 Gm",
        "price": 111607.14,
    },
    {
        "code": "gg",
        "name": "Immard 200 mg №30 Tab",
        "composition": "Hydroxychloroquine sulfate",
        "expiry": "Sep.29",
        "packs": "3x10 Tab",
        "price": 29569.87,
    },
]

VAT_RATE = 0.12  # 12% QQS, Excel'dagi kabi

# Excel shablonidagi kabi doim bir xil turadigan pastki matn (kontakt)
FOOTER_TEXT = "carewell   телефон: + 998 90 316 92 22"

# Suhbat bosqichlari: 0 = firma nomi, keyingilari — har bir mahsulot uchun son
NAME_STATE = 0
QTY_STATES = [i + 1 for i in range(len(PRODUCTS))]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


def fmt(n: float) -> str:
    """Sonlarni 1 234 567.89 ko'rinishida chiroyli formatlaydi."""
    return f"{n:,.2f}".replace(",", " ")


# ---------------------------------------------------------------------
# /start — suhbatni boshlaydi, avval firma nomini so'raydi
# ---------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["qty"] = {}
    await update.message.reply_text(
        "Salom! Buxgalteriya hisob-kitob boti.\n\n"
        "Avval firma (mijoz) nomini kiriting:"
    )
    return NAME_STATE


async def name_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["company_name"] = update.message.text.strip()
    p = PRODUCTS[0]
    await update.message.reply_text(
        "Endi har bir mahsulot uchun sonini (miqdorini) kiriting.\n"
        "Kerak bo'lmasa 0 deb yozing.\n\n"
        f"1) {p['name']} — soni nechta?"
    )
    return QTY_STATES[0]


def make_qty_handler(index: int):
    """Har bir mahsulot uchun son so'rovchi handler yasab beradi."""

    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip().replace(",", ".")
        try:
            qty = float(text)
        except ValueError:
            await update.message.reply_text(
                "Iltimos, faqat son kiriting (masalan: 5 yoki 0)."
            )
            return QTY_STATES[index]

        code = PRODUCTS[index]["code"]
        context.user_data["qty"][code] = qty

        next_index = index + 1
        if next_index < len(PRODUCTS):
            p = PRODUCTS[next_index]
            await update.message.reply_text(
                f"{next_index + 1}) {p['name']} — soni nechta?"
            )
            return QTY_STATES[next_index]
        else:
            await finish(update, context)
            return ConversationHandler.END

    return handler


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bekor qilindi. Qaytadan boshlash uchun /start yozing.")
    return ConversationHandler.END


# ---------------------------------------------------------------------
# Hisob-kitob va rasm (screenshot) yasash
# ---------------------------------------------------------------------
def calculate(qty: dict):
    rows = []
    total = 0.0
    for p in PRODUCTS:
        q = qty.get(p["code"], 0)
        vat = round(p["price"] * VAT_RATE, 2)
        price_with_vat = round(p["price"] + vat, 2)
        amount = round(q * price_with_vat, 2)
        total += amount
        rows.append(
            {**p, "vat": vat, "price_with_vat": price_with_vat, "qty": q, "amount": amount}
        )
    return rows, total


# Turli operatsion tizimlarda (Windows / Linux / Mac) mavjud bo'lgan,
# krillcha (rus/o'zbek) belgilarni qo'llab-quvvatlaydigan shriftlarni
# birma-bir qidiradi va topilganini ishlatadi.
REGULAR_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\tahoma.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]
BOLD_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\tahomabd.ttf",
    r"C:\Windows\Fonts\calibrib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]

_font_cache = {}


def load_font(bold: bool, size: int):
    key = (bold, size)
    if key in _font_cache:
        return _font_cache[key]
    candidates = BOLD_FONT_CANDIDATES if bold else REGULAR_FONT_CANDIDATES
    for path in candidates:
        if os.path.exists(path):
            font = ImageFont.truetype(path, size)
            _font_cache[key] = font
            return font
    # Hech qanday shrift topilmasa, PIL standart shriftidan foydalanamiz
    font = ImageFont.load_default()
    _font_cache[key] = font
    return font


def build_table_image(rows, total, company_name: str = "") -> BytesIO:
    # Ustunlar Excel shablonidagi tartibda: №, Goods, composition, Expiry,
    # packs, Price, 12% QQS, ^VAT, (soni — sarlavhasiz ustun), Amount
    headers = [
        "№", "Goods", "composition", "Expiry", "packs",
        "Price", "12% QQS", "^VAT", "", "Amount",
    ]
    col_w = [40, 200, 200, 90, 90, 100, 90, 100, 60, 120]
    row_h = 40
    header_h = 46
    title_h = 46
    margin = 20
    table_w = sum(col_w)

    n_rows = len(rows)
    height = title_h + header_h + row_h * (n_rows + 1 + 2) + margin * 2 + 20

    img = Image.new("RGB", (table_w + margin * 2, height), "white")
    draw = ImageDraw.Draw(img)

    f_header = load_font(bold=True, size=14)
    f_cell = load_font(bold=False, size=13)
    f_total = load_font(bold=True, size=15)
    f_title = load_font(bold=True, size=26)

    x0, y0 = margin, margin

    def col_x(i):
        return x0 + sum(col_w[:i])

    def box(x, y, w, h, fill="white"):
        draw.rectangle([x, y, x + w, y + h], outline="black", width=1, fill=fill)

    def center_text(x, y, w, h, text, font, bold_color="black"):
        tw = draw.textlength(str(text), font=font)
        th = font.size
        draw.text((x + (w - tw) / 2, y + (h - th) / 2), str(text), fill=bold_color, font=font)

    def _draw_wrapped(x, y, w, h, text, font):
        text = str(text)
        words = text.split(" ")
        lines, cur = [], ""
        for word in words:
            test = (cur + " " + word).strip()
            if draw.textlength(test, font=font) <= w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        lines = lines[:3] if lines else [""]
        total_text_h = len(lines) * (font.size + 4)
        ty = y + (h - total_text_h) / 2
        for line in lines:
            draw.text((x + 4, ty), line, fill="black", font=font)
            ty += font.size + 4

    # ---- 1) Sarlavha qatori: firma nomi (katta), Excel'dagidek faqat
    #        № + Goods + composition + Expiry + packs ustunlarini egallaydi
    title_w = sum(col_w[:5])
    box(x0, y0, title_w, title_h, fill="white")
    if company_name:
        center_text(x0, y0, title_w, title_h, company_name.upper(), f_title)
    for i in range(5, 10):
        box(col_x(i), y0, col_w[i], title_h)
    y = y0 + title_h

    # ---- 2) Ustun sarlavhalari
    for i, h_text in enumerate(headers):
        box(col_x(i), y, col_w[i], header_h, fill=(255, 255, 255))
        center_text(col_x(i), y, col_w[i], header_h, h_text, f_header)
    y += header_h

    # ---- 3) Mahsulot qatorlari
    for idx, r in enumerate(rows, start=1):
        qty_str = fmt(r["qty"]).rstrip("0").rstrip(".") if "." in fmt(r["qty"]) else fmt(r["qty"])
        cells = [
            str(idx), r["name"], r["composition"], r["expiry"], r["packs"],
            fmt(r["price"]), fmt(r["vat"]), fmt(r["price_with_vat"]), qty_str, fmt(r["amount"]),
        ]
        for i, text in enumerate(cells):
            box(col_x(i), y, col_w[i], row_h)
            if i in (1, 2):  # Goods, composition — chapga tekislab, uzun matnni bo'lib yozamiz
                _draw_wrapped(col_x(i), y, col_w[i] - 8, row_h, text, f_cell)
            else:
                center_text(col_x(i), y, col_w[i], row_h, text, f_cell)
        y += row_h

    # ---- 4) Jami qatori (Excel'dagi O8 kabi — faqat Amount ustunida raqam)
    box(x0, y, table_w, row_h)
    center_text(col_x(9), y, col_w[9], row_h, fmt(total), f_total)
    y += row_h

    # ---- 5) Pastki qism: chap tomonda doimiy kontakt matni (2 qator balandlikda),
    #        o'ng tomonda 50% / 100% qatorlari
    footer_h = row_h * 2
    footer_w = sum(col_w[:6])  # №..Price ustunlarini egallaydi
    box(x0, y, footer_w, footer_h)
    center_text(x0, y, footer_w, footer_h, FOOTER_TEXT, f_total)

    # 12% QQS va ^VAT ustunlari bo'sh (blank) qoladi, 2 qator balandlikda
    blank_w = col_w[6] + col_w[7]
    box(col_x(6), y, blank_w, footer_h)

    half = round(total * 0.5, 2)
    for offset, (label, value) in enumerate([("50%", half), ("100%", total)]):
        ry = y + offset * row_h
        box(col_x(8), ry, col_w[8], row_h)
        center_text(col_x(8), ry, col_w[8], row_h, label, f_total)
        box(col_x(9), ry, col_w[9], row_h)
        center_text(col_x(9), ry, col_w[9], row_h, fmt(value), f_total)

    buf = BytesIO()
    buf.name = "hisobot.png"
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


async def finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    qty = context.user_data.get("qty", {})
    company_name = context.user_data.get("company_name", "")
    rows, total = calculate(qty)
    half = round(total * 0.5, 2)
    photo = build_table_image(rows, total, company_name)

    lines = []
    if company_name:
        lines.append(f"Firma: {company_name}\n")
    lines.append("Hisob-kitob tayyor:\n")
    for r in rows:
        if r["qty"] > 0:
            lines.append(f"• {r['name']}: {r['qty']} x {fmt(r['price_with_vat'])} = {fmt(r['amount'])} so'm")
    lines.append(f"\nJami: {fmt(total)} so'm")
    lines.append(f"50%: {fmt(half)} so'm")
    lines.append(f"100%: {fmt(total)} so'm")

    await update.message.reply_text("\n".join(lines))
    await update.message.reply_photo(photo=photo)


def get_token() -> str:
    # 1) Avval faylning yuqorisidagi BOT_TOKEN qatoriga qaraydi
    if BOT_TOKEN and BOT_TOKEN != "SIZNING_TOKEN_BU_YERGA":
        return BOT_TOKEN.strip()
    # 2) Bo'lmasa, muhit o'zgaruvchisidan qidiradi (masalan Render'da)
    token = os.environ.get("BOT_TOKEN")
    if token:
        return token.strip()
    # 3) Terminal mavjud bo'lsa (kompyuterda qo'lda ishga tushirilsa) so'raydi.
    #    Serverda (terminal yo'q joyda) input() abadiy osilib qolib,
    #    dasturni qayta-qayta qulatib yuborishi mumkin — shuning uchun
    #    bunday holatda darhol tushunarli xato bilan to'xtaymiz.
    if sys.stdin is not None and sys.stdin.isatty():
        token = input("Telegram bot TOKEN'ni kiriting (@BotFather'dan olingan): ").strip()
        while not token:
            token = input("Token bo'sh bo'lmasligi kerak. Qayta kiriting: ").strip()
        return token
    log.error(
        "BOT_TOKEN topilmadi! Faylning yuqorisidagi BOT_TOKEN qatoriga tokenni yozing "
        "yoki server sozlamalarida BOT_TOKEN muhit o'zgaruvchisini qo'shing."
    )
    sys.exit(1)


def main():
    bot_token = get_token()

    # Render'ning bepul tarifi uchun port tinglovchi serverni fonda ishga tushiramiz
    threading.Thread(target=start_ping_server, daemon=True).start()

    app = ApplicationBuilder().token(bot_token).build()

    states = {NAME_STATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, name_handler)]}
    for i in range(len(PRODUCTS)):
        states[QTY_STATES[i]] = [MessageHandler(filters.TEXT & ~filters.COMMAND, make_qty_handler(i))]

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states=states,
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv)
    log.info("Bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
