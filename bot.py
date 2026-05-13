import os
import json
import asyncio
import httpx
from datetime import datetime, time
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, JobQueue

TOKEN = os.environ.get("BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DATA_FILE = "dokumenti.json"
SETTINGS_FILE = "settings.json"

NAZIV, DATUM = range(2)

def load_docs():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_docs(docs):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=2)

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_settings(s):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)

def status(date_str):
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    d = datetime.strptime(date_str, "%d.%m.%Y")
    diff = (d - today).days
    if diff < 0:
        return f"🔴 Isteklo {abs(diff)}d", "expired", diff
    elif diff <= 30:
        return f"🟡 Za {diff}d", "soon", diff
    else:
        return f"🟢 Za {diff}d", "ok", diff

def parse_date(text):
    formats = ["%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y"]
    for fmt in formats:
        try:
            return datetime.strptime(text.strip(), fmt).strftime("%d.%m.%Y")
        except:
            continue
    return None

def build_report():
    docs = load_docs()
    if not docs:
        return None
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    expired = []
    soon = []
    for d in docs:
        label, stype, diff = status(d["datum"])
        if stype == "expired":
            expired.append((d, abs(diff)))
        elif stype == "soon":
            soon.append((d, diff))

    if not expired and not soon:
        return None

    msg = f"🌅 *Jutarnji izvještaj* — {today.strftime('%d.%m.%Y')}\n\n"
    if expired:
        msg += f"🔴 *ISTEKLO ({len(expired)}):*\n"
        for d, diff in sorted(expired, key=lambda x: x[1]):
            msg += f"• {d['naziv']} — {diff} dana isteklo\n"
        msg += "\n"
    if soon:
        msg += f"🟡 *USKORO ISTIČE ({len(soon)}):*\n"
        for d, diff in sorted(soon, key=lambda x: x[1]):
            msg += f"• {d['naziv']} — za {diff} dana\n"
    return msg

def build_docs_context():
    """Gradi kontekst o dokumentima za AI."""
    docs = load_docs()
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    if not docs:
        return "Trenutno nema unesenih dokumenata."

    lines = [f"Danas je {today.strftime('%d.%m.%Y')}. Popis dokumenata:"]
    for d in sorted(docs, key=lambda x: datetime.strptime(x["datum"], "%d.%m.%Y")):
        label, stype, diff = status(d["datum"])
        if stype == "expired":
            lines.append(f"- {d['naziv']}: datum isteka {d['datum']} (ISTEKLO prije {abs(diff)} dana)")
        elif stype == "soon":
            lines.append(f"- {d['naziv']}: datum isteka {d['datum']} (ističe za {diff} dana)")
        else:
            lines.append(f"- {d['naziv']}: datum isteka {d['datum']} (vrijedi još {diff} dana)")
    return "\n".join(lines)

AI_SYSTEM_PROMPT = """Ti si asistent za upravljanje dokumentima integriran u Telegram bota.
Pomažeš korisniku da prati rokove važnosti dokumenata (registracije, vozačke dozvole, pasoši, police osiguranja itd.).

Tvoje mogućnosti:
1. Odgovaraš na pitanja o dokumentima (koji ističu, koji su istekli, koliko dana ostalo)
2. Daješ savjete šta uraditi sa isteklim ili dokumentima koji uskoro ističu
3. Prepoznaješ kada korisnik želi dodati novi dokument i vraćaš strukturirani JSON
4. Opći razgovor i pomoć

Kada korisnik želi dodati dokument (npr. "dodaj registraciju auta do 15.3.2026" ili "vozačka ističe 01.06.2026"):
Vrati SAMO JSON u ovom formatu, bez ikakvog drugog teksta:
{"action": "dodaj_dokument", "naziv": "Naziv dokumenta", "datum": "DD.MM.YYYY"}

U svim ostalim slučajevima odgovaraj normalno na bosanskom/srpskom jeziku.
Budi koncizan, prijateljski i praktičan. Koristit emotikone umjereno."""

async def ai_chat(user_message: str, docs_context: str, history: list) -> str:
    """Poziva Gemini Flash API."""
    if not GEMINI_API_KEY:
        return "❌ AI nije konfigurisan. Postavi GEMINI_API_KEY environment varijablu."

    system_with_context = f"{AI_SYSTEM_PROMPT}\n\nTrenutno stanje dokumenata:\n{docs_context}"

    # System prompt kao prvi user/model par
    contents = [
        {"role": "user", "parts": [{"text": system_with_context}]},
        {"role": "model", "parts": [{"text": "Razumijem, spreman sam pomoci."}]},
    ]
    for msg in history:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    contents.append({"role": "user", "parts": [{"text": user_message}]})

    payload = {
        "contents": contents,
        "generationConfig": {
            "maxOutputTokens": 1000,
            "temperature": 0.7,
        }
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

async def podsjetnik_job(ctx: ContextTypes.DEFAULT_TYPE):
    settings = load_settings()
    chat_id = settings.get("chat_id")
    if not chat_id:
        return
    msg = build_report()
    if msg:
        await ctx.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    settings = load_settings()
    settings["chat_id"] = update.effective_chat.id
    save_settings(settings)
    podsjetnici = "✅ Uključeni" if settings.get("podsjetnici", False) else "❌ Isključeni"
    await update.message.reply_text(
        "👋 *Zdravo! Evidencija dokumenata.*\n\n"
        "📌 *Komande:*\n"
        "/dodaj — dodaj novi dokument\n"
        "/lista — svi dokumenti\n"
        "/uskoro — ističe u 30 dana\n"
        "/isteklo — istekli dokumenti\n"
        "/brisanje — obriši dokument\n"
        "/izvjestaj — pošalji izvještaj odmah\n\n"
        "🤖 *AI Asistent:*\n"
        "/ai ili /pitaj — razgovaraj sa AI asistentom\n"
        "_(pita za dokumente, daje savjete, dodaje dokumente)_\n\n"
        "🔔 *Podsjetnici:*\n"
        "/podsjetnik\\_on — uključi jutarnji podsjetnik\n"
        "/podsjetnik\\_off — isključi podsjetnik\n"
        f"Status: {podsjetnici}\n\n"
        "💡 Brzi unos:\n"
        "`Naziv dokumenta 31.12.2025`",
        parse_mode="Markdown"
    )

async def podsjetnik_on(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    settings = load_settings()
    settings["chat_id"] = update.effective_chat.id
    settings["podsjetnici"] = True
    save_settings(settings)
    current_jobs = ctx.job_queue.get_jobs_by_name("jutarnji")
    for job in current_jobs:
        job.schedule_removal()
    ctx.job_queue.run_daily(
        podsjetnik_job,
        time=time(hour=8, minute=0, second=0),
        name="jutarnji"
    )
    await update.message.reply_text(
        "🔔 *Jutarnji podsjetnici uključeni!*\n\n"
        "Svaki dan u *08:00* dobijaš poruku ako ima isteklih ili dokumenata koji uskoro ističu.",
        parse_mode="Markdown"
    )

async def podsjetnik_off(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    settings = load_settings()
    settings["podsjetnici"] = False
    save_settings(settings)
    current_jobs = ctx.job_queue.get_jobs_by_name("jutarnji")
    for job in current_jobs:
        job.schedule_removal()
    await update.message.reply_text(
        "🔕 *Jutarnji podsjetnici isključeni.*\n\nMožeš ih ponovo uključiti sa /podsjetnik\\_on",
        parse_mode="Markdown"
    )

async def izvjestaj(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = build_report()
    if msg:
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("✅ *Sve je uređeno!* Nema isteklih ni dokumenata koji uskoro ističu.", parse_mode="Markdown")

async def dodaj_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📄 *Naziv dokumenta?*\n\nnpr. _Registracija VW Golf_", parse_mode="Markdown")
    return NAZIV

async def dodaj_naziv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["naziv"] = update.message.text.strip()
    await update.message.reply_text(
        f"📅 *Datum isteka za:* _{ctx.user_data['naziv']}_\n\nUnesi: `31.12.2025`",
        parse_mode="Markdown"
    )
    return DATUM

async def dodaj_datum(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    date_str = parse_date(update.message.text)
    if not date_str:
        await update.message.reply_text("❌ Neispravan format. Unesi: `31.12.2025`", parse_mode="Markdown")
        return DATUM
    docs = load_docs()
    doc = {"id": int(datetime.now().timestamp()), "naziv": ctx.user_data["naziv"], "datum": date_str}
    docs.append(doc)
    save_docs(docs)
    label, _, _ = status(date_str)
    await update.message.reply_text(
        f"✅ *Sačuvano!*\n\n📄 {doc['naziv']}\n📅 {date_str}\nStatus: {label}",
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
        label, _, _ = status(d["datum"])
        msg += f"{label} *{d['naziv']}*\n📅 {d['datum']}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def uskoro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    docs = load_docs()
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    filtered = [(d, (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days)
                for d in docs if 0 <= (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days <= 30]
    filtered.sort(key=lambda x: x[1])
    if not filtered:
        await update.message.reply_text("✅ Nema dokumenata koji ističu u narednih 30 dana.")
        return
    msg = f"🟡 *Uskoro ističe ({len(filtered)}):*\n\n"
    for d, diff in filtered:
        msg += f"⚠️ *{d['naziv']}*\n📅 {d['datum']} — za {diff} dana\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def isteklo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    docs = load_docs()
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    filtered = [(d, abs((datetime.strptime(d["datum"], "%d.%m.%Y") - today).days))
                for d in docs if (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days < 0]
    filtered.sort(key=lambda x: x[1])
    if not filtered:
        await update.message.reply_text("✅ Nema isteklih dokumenata.")
        return
    msg = f"🔴 *Isteklo ({len(filtered)}):*\n\n"
    for d, diff in filtered:
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
        msg += f"{i}. {d['naziv']} — {d['datum']}\n"
    ctx.user_data["docs_za_brisanje"] = docs_sorted
    await update.message.reply_text(msg, parse_mode="Markdown")

async def ai_komanda(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Pokreće AI asistenta — /ai ili /pitaj, opcionalno s porukom."""
    # Inicijalizuj historiju ako ne postoji
    if "ai_history" not in ctx.user_data:
        ctx.user_data["ai_history"] = []

    # Provjeri da li je poruka proslijeđena uz komandu (npr. /ai koji dokumenti ističu?)
    args = ctx.args
    if args:
        user_text = " ".join(args)
        await _process_ai_message(update, ctx, user_text)
    else:
        ctx.user_data["ai_mode"] = True
        await update.message.reply_text(
            "🤖 *AI Asistent aktivan!*\n\n"
            "Pitaj me bilo šta o tvojim dokumentima ili piši slobodno.\n\n"
            "Primjeri:\n"
            "• _Koji dokumenti ističu uskoro?_\n"
            "• _Šta trebam uraditi za isteklu registraciju?_\n"
            "• _Dodaj vozačku dozvolu do 15.3.2027_\n\n"
            "Za izlaz iz AI moda piši /kraj ili /stop",
            parse_mode="Markdown"
        )

async def ai_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Izlaz iz AI moda."""
    ctx.user_data["ai_mode"] = False
    ctx.user_data["ai_history"] = []
    await update.message.reply_text(
        "👋 AI mod zatvoren. Historija razgovora obrisana.\n\nKoristi /ai za novi razgovor.",
        parse_mode="Markdown"
    )

async def _process_ai_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user_text: str):
    """Obrađuje poruku kroz AI i eventualno dodaje dokument."""
    docs_context = build_docs_context()
    history = ctx.user_data.get("ai_history", [])

    # Pošalji "kuca..." indikator
    thinking_msg = await update.message.reply_text("🤖 _Razmišljam..._", parse_mode="Markdown")

    try:
        response_text = await ai_chat(user_text, docs_context, history)

        # Provjeri da li AI želi dodati dokument (JSON akcija)
        stripped = response_text.strip()
        if stripped.startswith("{") and '"action": "dodaj_dokument"' in stripped:
            try:
                action = json.loads(stripped)
                naziv = action.get("naziv", "")
                datum_raw = action.get("datum", "")
                date_str = parse_date(datum_raw)
                if naziv and date_str:
                    docs = load_docs()
                    doc = {"id": int(datetime.now().timestamp()), "naziv": naziv, "datum": date_str}
                    docs.append(doc)
                    save_docs(docs)
                    label, _, _ = status(date_str)
                    await thinking_msg.edit_text(
                        f"✅ *Dokument dodan putem AI!*\n\n📄 {naziv}\n📅 {date_str}\nStatus: {label}",
                        parse_mode="Markdown"
                    )
                    # Dodaj u historiju
                    ctx.user_data["ai_history"] = history + [
                        {"role": "user", "content": user_text},
                        {"role": "assistant", "content": f"Dodao sam dokument: {naziv}, datum: {date_str}"}
                    ]
                    return
            except json.JSONDecodeError:
                pass  # Nije JSON, nastavi normalno

        # Normalan AI odgovor — ažuriraj poruku
        await thinking_msg.edit_text(response_text, parse_mode="Markdown")

        # Čuvaj historiju (max 10 poruka da ne bude prevelika)
        new_history = history + [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": response_text}
        ]
        ctx.user_data["ai_history"] = new_history[-10:]

    except httpx.HTTPStatusError as e:
        await thinking_msg.edit_text(f"❌ API greška: {e.response.status_code}. Provjeri API ključ.")
    except Exception as e:
        await thinking_msg.edit_text(f"❌ Greška: {str(e)}")

async def brzi_unos(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Ako je AI mod aktivan, preusmjeri na AI
    if ctx.user_data.get("ai_mode", False):
        if text.lower() in ["/kraj", "/stop", "kraj", "stop", "izlaz"]:
            ctx.user_data["ai_mode"] = False
            ctx.user_data["ai_history"] = []
            await update.message.reply_text("👋 AI mod zatvoren.")
            return
        await _process_ai_message(update, ctx, text)
        return

    # Brisanje po broju
    if "docs_za_brisanje" in ctx.user_data:
        try:
            br = int(text)
            lista_za_brisanje = ctx.user_data["docs_za_brisanje"]
            if 1 <= br <= len(lista_za_brisanje):
                doc = lista_za_brisanje[br - 1]
                docs = load_docs()
                docs = [d for d in docs if d["id"] != doc["id"]]
                save_docs(docs)
                del ctx.user_data["docs_za_brisanje"]
                await update.message.reply_text(f"✅ Obrisan: *{doc['naziv']}*", parse_mode="Markdown")
                return
        except:
            del ctx.user_data["docs_za_brisanje"]

    # Brzi unos: "Naziv DD.MM.YYYY"
    parts = text.rsplit(" ", 1)
    if len(parts) == 2:
        naziv, datum_raw = parts
        date_str = parse_date(datum_raw)
        if date_str:
            docs = load_docs()
            doc = {"id": int(datetime.now().timestamp()), "naziv": naziv.strip(), "datum": date_str}
            docs.append(doc)
            save_docs(docs)
            label, _, _ = status(date_str)
            await update.message.reply_text(
                f"✅ *Sačuvano!*\n\n📄 {doc['naziv']}\n📅 {date_str}\nStatus: {label}",
                parse_mode="Markdown"
            )
            return

    await update.message.reply_text(
        "❓ Ne razumijem.\n\nKoristi /dodaj, /ai za AI asistenta, ili piši:\n`Naziv dokumenta 31.12.2025`",
        parse_mode="Markdown"
    )

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
    app.add_handler(CommandHandler("izvjestaj", izvjestaj))
    app.add_handler(CommandHandler("podsjetnik_on", podsjetnik_on))
    app.add_handler(CommandHandler("podsjetnik_off", podsjetnik_off))
    app.add_handler(CommandHandler(["ai", "pitaj"], ai_komanda))
    app.add_handler(CommandHandler(["kraj", "stop"], ai_stop))
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, brzi_unos))

    settings = load_settings()
    if settings.get("podsjetnici", False) and settings.get("chat_id"):
        app.job_queue.run_daily(
            podsjetnik_job,
            time=time(hour=8, minute=0, second=0),
            name="jutarnji"
        )
        print("Jutarnji podsjetnik aktivan — 08:00")

    print("Bot pokrenut!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
