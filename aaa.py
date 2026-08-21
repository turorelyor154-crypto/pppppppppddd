# =====================================================================
# BUXGALTERIYA HISOB-KITOB TELEGRAM BOTI
# =====================================================================
# ISHGA TUSHIRISH (terminalda):
#   1) python3 -m venv venv
#      source venv/bin/activate        (Windows: venv\Scripts\activate)
#   2) pip install python-telegram-bot pillow
#   3) python3 bot.py
#   4) Terminal token so'raydi — @BotFather bergan tokenni shu yerga
#      yozib, Enter bosing (fayl ichiga token yozilmaydi).
#   5) Telegram'da botga /start yuboring.
# =====================================================================

import logging
import os
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
        "expiry": "01.11.2026",
        "packs": "2x14 Tab",
        "price": 84235.05,
    },
    {
        "code": "bb",
        "name": "Cartiflex №10 Sachet",
        "composition": "collagen peptide",
        "expiry": "01.11.2026",
        "packs": "10 Sachet",
        "price": 133928.57,
    },
    {
        "code": "cc",
        "name": "Nutrifiber 200 mg tab",
        "composition": "Inulin, Maltodextrin, PHGG",
        "expiry": "01.11.2027",
        "packs": "200 Gm",
        "price": 111607.14,
    },
    {
        "code": "gg",
        "name": "Immard 200 mg №30 Tab",
        "composition": "Hydroxychloroquine sulfate",
        "expiry": "01.09.2029",
        "packs": "3x10 Tab",
        "price": 29569.87,
    },
]

VAT_RATE = 0.12  # 12% QQS, Excel'dagi kabi

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
    # Ustunlar: №, Mahsulot, Tarkibi, Yaroqlilik, Qadoq, Narxi, 12% QQS, QQS bilan, Soni, Summa
    headers = [
        "№", "Mahsulot", "Tarkibi", "Yaroqlilik", "Qadoq",
        "Narxi", "12% QQS", "QQS bilan", "Soni", "Summa",
    ]
    col_w = [40, 220, 220, 100, 90, 110, 90, 110, 70, 130]
    row_h = 44
    header_h = 50
    title_h = 40 if company_name else 0
    margin = 20

    width = sum(col_w) + margin * 2
    # +2 qo'shimcha qator: 50% va 100%
    height = title_h + header_h + row_h * (len(rows) + 1 + 2) + margin * 2 + 20

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    f_header = load_font(bold=True, size=15)
    f_cell = load_font(bold=False, size=14)
    f_total = load_font(bold=True, size=16)
    f_title = load_font(bold=True, size=20)

    x0, y0 = margin, margin

    if company_name:
        draw.text((x0, y0), company_name, fill="black", font=f_title)
        y0 += title_h

    def draw_row(y, cells, font, header=False, bold_last=False):
        x = x0
        fill = (221, 235, 247) if header else "white"
        for i, text in enumerate(cells):
            w = col_w[i]
            draw.rectangle([x, y, x + w, y + row_h if not header else y + header_h],
                           outline="black", width=1, fill=fill)
            h = header_h if header else row_h
            use_font = f_total if (bold_last and i == len(cells) - 1) else font
            # matnni katakka joylashtirish, agar uzun bo'lsa qatorga bo'lib yozamiz
            _draw_wrapped(draw, text, x + 4, y, w - 8, h, use_font)
            x += w

    def _draw_wrapped(draw, text, x, y, w, h, font):
        text = str(text)
        words = text.split(" ")
        lines = []
        cur = ""
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
        if not lines:
            lines = [""]
        lines = lines[:3]
        total_text_h = len(lines) * (font.size + 4)
        ty = y + (h - total_text_h) / 2
        for line in lines:
            draw.text((x, ty), line, fill="black", font=font)
            ty += font.size + 4

    # sarlavha
    draw_row(y0, headers, f_header, header=True)
    y = y0 + header_h

    for idx, r in enumerate(rows, start=1):
        cells = [
            str(idx),
            r["name"],
            r["composition"],
            r["expiry"],
            r["packs"],
            fmt(r["price"]),
            fmt(r["vat"]),
            fmt(r["price_with_vat"]),
            fmt(r["qty"]).rstrip("0").rstrip(".") if "." in fmt(r["qty"]) else fmt(r["qty"]),
            fmt(r["amount"]),
        ]
        draw_row(y, cells, f_cell)
        y += row_h

    # Jami, 50% va 100% qatorlari
    half = round(total * 0.5, 2)
    summary_rows = [
        (f"Jami: {fmt(total)} so'm", (255, 242, 204)),
        (f"50%: {fmt(half)} so'm", (226, 239, 218)),
        (f"100%: {fmt(total)} so'm", (226, 239, 218)),
    ]
    for label, color in summary_rows:
        draw.rectangle([x0, y, x0 + sum(col_w), y + row_h], outline="black", width=1, fill=color)
        draw.text(
            (x0 + sum(col_w) - 4 - draw.textlength(label, font=f_total), y + (row_h - f_total.size) / 2),
            label, fill="black", font=f_total,
        )
        y += row_h

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
    # Avval muhit o'zgaruvchisidan qidiradi (ixtiyoriy), bo'lmasa terminalda so'raydi
    token = os.environ.get("BOT_TOKEN")
    if token:
        return token.strip()
    token = input("Telegram bot TOKEN'ni kiriting (@BotFather'dan olingan): ").strip()
    while not token:
        token = input("Token bo'sh bo'lmasligi kerak. Qayta kiriting: ").strip()
    return token


def main():
    bot_token = get_token()
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
