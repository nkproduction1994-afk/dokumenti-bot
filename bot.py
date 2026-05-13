import os
import json
import asyncio
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

TOKEN = os.environ.get("BOT_TOKEN")
DATA_FILE = "dokumenti.json"

# Conversation states
NAZIV, DATUM = range(2)

def load_docs():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_docs(docs):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=2)

def status(date_str):
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    d = datetime.strptime(date_str, "%d.%m.%Y")
    diff = (d - today).days
    if diff < 0:
        return f"🔴 Isteklo {abs(diff)}d"
    elif diff <= 30:
        return f"🟡 Za {diff}d"
    else:
        return f"🟢 Za {diff}d"

def parse_date(text):
    """Pokušaj parsirati datum u različitim formatima"""
    formats = ["%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y"]
    for fmt in formats:
        try:
            return datetime.strptime(text.strip(), fmt).strftime("%d.%m.%Y")
        except:
            continue
    return None

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Zdravo! Evidencija dokumenata.*\n\n"
        "📌 *Komande:*\n"
        "/dodaj — dodaj novi dokument\n"
        "/lista — svi dokumenti\n"
        "/uskoro — ističe u 30 dana\n"
        "/isteklo — istekli dokumenti\n"
        "/brisanje — obriši dokument\n\n"
        "💡 Ili samo piši u formatu:\n"
        "`Naziv dokumenta 31.12.2025`",
        parse_mode="Markdown"
    )

async def dodaj_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📄 *Naziv dokumenta?*\n\n"
        "npr. _Registracija VW Golf_",
        parse_mode="Markdown"
    )
    return NAZIV

async def dodaj_naziv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["naziv"] = update.message.text.strip()
    await update.message.reply_text(
        f"📅 *Datum isteka za:* _{ctx.user_data['naziv']}_\n\n"
        "Unesi u formatu: `31.12.2025`",
        parse_mode="Markdown"
    )
    return DATUM

async def dodaj_datum(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    date_str = parse_date(update.message.text)
    if not date_str:
        await update.message.reply_text(
            "❌ Neispravan format datuma.\n"
            "Unesi ovako: `31.12.2025`",
            parse_mode="Markdown"
        )
        return DATUM

    docs = load_docs()
    doc = {
        "id": int(datetime.now().timestamp()),
        "naziv": ctx.user_data["naziv"],
        "datum": date_str
    }
    docs.append(doc)
    save_docs(docs)

    s = status(date_str)
    await update.message.reply_text(
        f"✅ *Sačuvano!*\n\n"
        f"📄 {doc['naziv']}\n"
        f"📅 {date_str}\n"
        f"Status: {s}",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def dodaj_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Otkazano.")
    return ConversationHandler.END

async def lista(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    docs = load_docs()
    if not docs:
        await update.message.reply_text("📭 Nema dokumenata. Dodaj prvi sa /dodaj")
        return

    docs_sorted = sorted(docs, key=lambda d: datetime.strptime(d["datum"], "%d.%m.%Y"))
    msg = "📋 *Svi dokumenti:*\n\n"
    for d in docs_sorted:
        s = status(d["datum"])
        msg += f"{s} *{d['naziv']}*\n📅 {d['datum']}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def uskoro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    docs = load_docs()
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    filtered = [d for d in docs if 0 <= (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days <= 30]
    filtered.sort(key=lambda d: datetime.strptime(d["datum"], "%d.%m.%Y"))

    if not filtered:
        await update.message.reply_text("✅ Nema dokumenata koji ističu u narednih 30 dana.")
        return

    msg = f"🟡 *Uskoro ističe ({len(filtered)}):*\n\n"
    for d in filtered:
        diff = (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days
        msg += f"⚠️ *{d['naziv']}*\n📅 {d['datum']} — za {diff} dana\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def isteklo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    docs = load_docs()
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    filtered = [d for d in docs if (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days < 0]
    filtered.sort(key=lambda d: datetime.strptime(d["datum"], "%d.%m.%Y"))

    if not filtered:
        await update.message.reply_text("✅ Nema isteklih dokumenata.")
        return

    msg = f"🔴 *Isteklo ({len(filtered)}):*\n\n"
    for d in filtered:
        diff = abs((datetime.strptime(d["datum"], "%d.%m.%Y") - today).days)
        msg += f"❌ *{d['naziv']}*\n📅 {d['datum']} — {diff} dana isteklo\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def brisanje(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    docs = load_docs()
    if not docs:
        await update.message.reply_text("📭 Nema dokumenata za brisanje.")
        return

    docs_sorted = sorted(docs, key=lambda d: datetime.strptime(d["datum"], "%d.%m.%Y"))
    msg = "🗑 *Koji dokument obrisati?*\n\nPošalji broj:\n\n"
    for i, d in enumerate(docs_sorted, 1):
        s = status(d["datum"])
        msg += f"{i}. {d['naziv']} — {d['datum']}\n"

    ctx.user_data["docs_za_brisanje"] = docs_sorted
    await update.message.reply_text(msg, parse_mode="Markdown")

async def brisi_broj(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if "docs_za_brisanje" not in ctx.user_data:
        return
    try:
        br = int(update.message.text.strip())
        lista_za_brisanje = ctx.user_data["docs_za_brisanje"]
        if br < 1 or br > len(lista_za_brisanje):
            await update.message.reply_text("❌ Neispravan broj.")
            return
        doc = lista_za_brisanje[br - 1]
        docs = load_docs()
        docs = [d for d in docs if d["id"] != doc["id"]]
        save_docs(docs)
        del ctx.user_data["docs_za_brisanje"]
        await update.message.reply_text(f"✅ Obrisan: *{doc['naziv']}*", parse_mode="Markdown")
    except:
        pass

async def brzi_unos(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Parsira poruku oblika: Naziv dokumenta 31.12.2025"""
    text = update.message.text.strip()
    parts = text.rsplit(" ", 1)
    if len(parts) != 2:
        await update.message.reply_text(
            "❓ Ne razumijem.\n\n"
            "Koristi /dodaj ili piši:\n"
            "`Naziv dokumenta 31.12.2025`",
            parse_mode="Markdown"
        )
        return

    naziv, datum_raw = parts
    date_str = parse_date(datum_raw)
    if not date_str:
        await update.message.reply_text(
            "❓ Ne razumijem datum.\n\n"
            "Koristi format: `31.12.2025`",
            parse_mode="Markdown"
        )
        return

    docs = load_docs()
    doc = {"id": int(datetime.now().timestamp()), "naziv": naziv.strip(), "datum": date_str}
    docs.append(doc)
    save_docs(docs)

    s = status(date_str)
    await update.message.reply_text(
        f"✅ *Sačuvano!*\n\n📄 {doc['naziv']}\n📅 {date_str}\nStatus: {s}",
        parse_mode="Markdown"
    )

async def dnevni_podsjetnik(ctx: ContextTypes.DEFAULT_TYPE):
    """Šalje jutarnji podsjetnik u 8:00"""
    chat_id = ctx.job.data
    docs = load_docs()
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)

    expired = [d for d in docs if (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days < 0]
    soon = [d for d in docs if 0 <= (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days <= 30]

    if not expired and not soon:
        return  # Ne šalji ako je sve uredeno

    msg = f"🌅 *Jutarnji izvještaj* — {today.strftime('%d.%m.%Y')}\n\n"

    if expired:
        msg += f"🔴 *Isteklo ({len(expired)}):*\n"
        for d in expired:
            diff = abs((datetime.strptime(d["datum"], "%d.%m.%Y") - today).days)
            msg += f"• {d['naziv']} — {diff}d\n"
        msg += "\n"

    if soon:
        msg += f"🟡 *Uskoro ističe ({len(soon)}):*\n"
        for d in soon:
            diff = (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days
            msg += f"• {d['naziv']} — za {diff}d\n"

    await ctx.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")

def main():
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("dodaj", dodaj_start)],
        states={
            NAZIV: [MessageHandler(filters.TEXT & ~filters.COMMAND, dodaj_naziv)],
            DATUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, dodaj_datum)],
        },
        fallbacks=[CommandHandler("cancel", dodaj_cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("uskoro", uskoro))
    app.add_handler(CommandHandler("isteklo", isteklo))
    app.add_handler(CommandHandler("brisanje", brisanje))
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, brzi_unos))

    print("Bot pokrenut!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
