import os
import json
import logging
import asyncio
from datetime import datetime, time
from typing import Dict, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    filters, ContextTypes, ConversationHandler, 
    CallbackQueryHandler
)

# ==================== LOGGING ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== KONFIGURACIJA ====================
TOKEN = os.environ.get("BOT_TOKEN")

# Opciono: DeepSeek AI (ako nema ključa, AI neće raditi - nije greška)
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")

# Inicijalizacija DeepSeek (samo ako ima ključa)
deepseek_client = None
if DEEPSEEK_API_KEY:
    try:
        from openai import AsyncOpenAI
        deepseek_client = AsyncOpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com/v1"
        )
        logger.info("✅ DeepSeek AI klijent inicijaliziran")
    except ImportError:
        logger.warning("⚠️ openai biblioteka nije instalirana. Instaliraj sa: pip install openai")
    except Exception as e:
        logger.error(f"❌ Greška pri inicijalizaciji DeepSeek: {e}")

# Fajlovi za podatke
DATA_FILE = "dokumenti.json"
SETTINGS_FILE = "settings.json"
USERS_FILE = "users.json"

# Konstantne za ConversationHandler
NAZIV, DATUM, KATEGORIJA, PRIORITET = range(4)
KATEGORIJE = ["📄 Lična", "💼 Poslovna", "🏥 Zdravstvo", "🚗 Auto", "🏠 Stambena", "🔒 Osiguranje", "🎓 Obrazovna", "💳 Finansijska"]
PRIORITETI = [("🔴 Visok", "high"), ("🟠 Srednji", "medium"), ("🟢 Nizak", "low")]

# ==================== POMOĆNE FUNKCIJE ====================
def load_docs() -> List[Dict]:
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Greška pri učitavanju: {e}")
    return []

def save_docs(docs: List[Dict]) -> bool:
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(docs, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Greška pri čuvanju: {e}")
        return False

def load_settings() -> Dict:
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Greška pri učitavanju podešavanja: {e}")
    return {"users": {}}

def save_settings(s: Dict) -> bool:
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Greška pri čuvanju podešavanja: {e}")
        return False

def load_users() -> Dict:
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Greška pri učitavanju korisnika: {e}")
    return {}

def save_users(users: Dict) -> bool:
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Greška pri čuvanju korisnika: {e}")
        return False

def get_user_docs(user_id: int) -> List[Dict]:
    docs = load_docs()
    return [d for d in docs if d.get("user_id") == user_id]

def status_info(date_str: str, priority: str = "medium") -> tuple:
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    d = datetime.strptime(date_str, "%d.%m.%Y")
    diff = (d - today).days
    
    priority_emoji = {"high": "🔴", "medium": "🟠", "low": "🟢"}.get(priority, "🟠")
    
    if diff < 0:
        return f"{priority_emoji} Isteklo {abs(diff)}d", "expired", diff
    elif diff <= 7:
        return f"{priority_emoji}🔥 Uskoro! ({diff}d)", "critical", diff
    elif diff <= 30:
        return f"{priority_emoji} Za {diff}d", "soon", diff
    else:
        return f"{priority_emoji} Za {diff}d", "ok", diff

def parse_date(text: str) -> Optional[str]:
    formats = ["%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y"]
    for fmt in formats:
        try:
            return datetime.strptime(text.strip(), fmt).strftime("%d.%m.%Y")
        except:
            continue
    return None

def build_report(user_id: int) -> Optional[str]:
    docs = get_user_docs(user_id)
    if not docs:
        return None
    
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    expired = []
    critical = []
    soon = []
    
    for d in docs:
        _, stype, diff = status_info(d["datum"], d.get("priority", "medium"))
        if stype == "expired":
            expired.append((d, abs(diff)))
        elif stype == "critical":
            critical.append((d, diff))
        elif stype == "soon":
            soon.append((d, diff))

    if not expired and not critical and not soon:
        return None

    msg = f"🌅 *Izvještaj* — {today.strftime('%d.%m.%Y')}\n\n"
    
    if expired:
        msg += f"🔴 *ISTEKLO ({len(expired)}):*\n"
        for d, diff in sorted(expired, key=lambda x: x[1]):
            msg += f"• {d['naziv']} — {diff} dana isteklo\n"
        msg += "\n"
    
    if critical:
        msg += f"🔥 *KRITIČNO! ({len(critical)}):*\n"
        for d, diff in sorted(critical, key=lambda x: x[1]):
            msg += f"• {d['naziv']} — za {diff} dana ⚠️\n"
        msg += "\n"
    
    if soon:
        msg += f"🟡 *USKORO ISTIČE ({len(soon)}):*\n"
        for d, diff in sorted(soon, key=lambda x: x[1]):
            msg += f"• {d['naziv']} — za {diff} dana\n"
    
    return msg

# ==================== AI CHAT (opciono) ====================
async def ai_chat(user_id: int, message: str) -> Optional[str]:
    """Komuniciraj sa DeepSeek AI (samo ako je podešen)"""
    if not deepseek_client:
        return None  # Vrati None ako AI nije dostupan
    
    try:
        response = await deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "Ti si koristan asistent na srpskom jeziku. Odgovaraj kratko."},
                {"role": "user", "content": message}
            ],
            max_tokens=300,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"AI greška: {e}")
        return None

# ==================== TELEGRAM HANDLERI ====================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    
    # Registruj korisnika
    users = load_users()
    if str(user_id) not in users:
        users[str(user_id)] = {
            "username": update.effective_user.username or "Nema",
            "first_name": update.effective_user.first_name,
            "registered_at": datetime.now().strftime("%d.%m.%Y %H:%M")
        }
        save_users(users)
        logger.info(f"Novi korisnik: {user_id}")
    
    keyboard = [
        [InlineKeyboardButton("📄 Dodaj dokument", callback_data="dodaj")],
        [InlineKeyboardButton("📋 Moji dokumenti", callback_data="lista")],
        [InlineKeyboardButton("🔥 Hitni dokumenti", callback_data="hitno")],
        [InlineKeyboardButton("📊 Statistika", callback_data="statistika")],
        [InlineKeyboardButton("⚙️ Podešavanja", callback_data="settings")]
    ]
    
    ai_status = "✅ Dostupan" if deepseek_client else "❌ Nije podešen"
    
    await update.message.reply_text(
        f"👋 *Zdravo {update.effective_user.first_name}!*\n\n"
        f"Dobrodošao u *Evidenciju dokumenata* 📋\n\n"
        f"🤖 *AI Chat:* {ai_status}\n\n"
        f"📌 *Komande:*\n"
        f"/dodaj — dodaj dokument\n"
        f"/lista — svi dokumenti\n"
        f"/hitno — ističe u 7 dana\n"
        f"/uskoro — ističe u 30 dana\n"
        f"/isteklo — istekli dokumenti\n"
        f"/statistika — pregled\n"
        f"/izvjestaj — ručni izvještaj\n"
        f"/pomoc — sve komande\n\n"
        f"💬 *AI Chat:*\n"
        f"Napiši bilo šta i AI će odgovoriti!",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def pomoc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *Sve komande:*\n\n"
        "📄 *Dokumenti:*\n"
        "/dodaj — dodaj dokument\n"
        "/lista — svi dokumenti\n"
        "/hitno — ističe za 7 dana\n"
        "/uskoro — ističe za 30 dana\n"
        "/isteklo — istekli dokumenti\n"
        "/brisanje — obriši dokument\n\n"
        "📊 *Statistika:*\n"
        "/statistika — pregled\n"
        "/izvjestaj — izvještaj\n\n"
        "🔔 *Podsjetnici:*\n"
        "/podsjetnik_on — uključi\n"
        "/podsjetnik_off — isključi\n\n"
        "❓ *Pomoć:*\n"
        "/pomoc — ovo\n"
        "/start — glavni meni",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Obradi poruku - ako AI radi, odgovori, inače samo običan odgovor"""
    user_id = update.effective_chat.id
    message_text = update.message.text.strip()
    
    # Preskoči ako je broj (za brisanje)
    if message_text.isdigit() and ctx.user_data.get("docs_za_brisanje"):
        return
    
    # Ako AI nije dostupan
    if not deepseek_client:
        await update.message.reply_text(
            "🤖 *AI chat trenutno nije dostupan.*\n\n"
            "Možeš koristiti komande za dokumente:\n"
            "/dodaj, /lista, /hitno, /pomoc",
            parse_mode="Markdown"
        )
        return
    
    # Pokaži da bot razmišlja
    await ctx.bot.send_chat_action(chat_id=user_id, action="typing")
    
    # Pokušaj dobiti AI odgovor
    response = await ai_chat(user_id, message_text)
    
    if response:
        await update.message.reply_text(response, parse_mode="Markdown")
    else:
        await update.message.reply_text(
            "❌ *AI chat nije uspio odgovoriti.*\n\n"
            "Provjeri da li je API ključ ispravan. Za sada možeš koristiti komande.",
            parse_mode="Markdown"
        )

# ==================== DODAVANJE DOKUMENATA ====================
async def dodaj_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📄 *Naziv dokumenta?*\n\nPrimjer: _Registracija vozila_",
        parse_mode="Markdown"
    )
    return NAZIV

async def dodaj_naziv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["naziv"] = update.message.text.strip()
    
    keyboard = [[InlineKeyboardButton(kat, callback_data=f"kat_{kat}")] for kat in KATEGORIJE]
    keyboard.append([InlineKeyboardButton("⏭️ Preskoči", callback_data="kat_skip")])
    
    await update.message.reply_text(
        f"📂 *Kategorija za:* _{ctx.user_data['naziv']}_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return KATEGORIJA

async def dodaj_kategorija(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "kat_skip":
        ctx.user_data["kategorija"] = None
    else:
        ctx.user_data["kategorija"] = query.data.replace("kat_", "")
    
    keyboard = [[InlineKeyboardButton(naziv, callback_data=f"prio_{vrijednost}")] for naziv, vrijednost in PRIORITETI]
    
    await query.edit_message_text(
        f"⚠️ *Prioritet za:* _{ctx.user_data['naziv']}_\n\n"
        f"🔴 Visok — alarm za 7 dana\n"
        f"🟠 Srednji — alarm za 30 dana\n"
        f"🟢 Nizak — običan",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return PRIORITET

async def dodaj_prioritet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    ctx.user_data["priority"] = query.data.replace("prio_", "")
    
    await query.edit_message_text(
        f"📅 *Datum isteka za:* _{ctx.user_data['naziv']}_\n\n"
        f"Unesi: `31.12.2025`, `31/12/2025` ili `31-12-2025`",
        parse_mode="Markdown"
    )
    return DATUM

async def dodaj_datum(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    date_str = parse_date(update.message.text)
    if not date_str:
        await update.message.reply_text("❌ Neispravan format. Unesi: `31.12.2025`", parse_mode="Markdown")
        return DATUM
    
    docs = load_docs()
    doc = {
        "id": int(datetime.now().timestamp()),
        "user_id": update.effective_chat.id,
        "naziv": ctx.user_data["naziv"],
        "datum": date_str,
        "kategorija": ctx.user_data.get("kategorija"),
        "priority": ctx.user_data.get("priority", "medium"),
        "created_at": datetime.now().strftime("%d.%m.%Y")
    }
    docs.append(doc)
    save_docs(docs)
    
    label, _, _ = status_info(date_str, ctx.user_data.get("priority", "medium"))
    
    await update.message.reply_text(
        f"✅ *Sačuvano!*\n\n📄 {doc['naziv']}\n📅 {doc['datum']}\n🏷️ {doc.get('kategorija', 'Bez kategorije')}\n\nStatus: {label}",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def dodaj_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Otkazano.")
    return ConversationHandler.END

# ==================== OSTALE FUNKCIJE ====================
async def lista(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    docs = get_user_docs(user_id)
    
    if not docs:
        await update.message.reply_text("📭 Nema dokumenata. Dodaj prvi sa /dodaj")
        return
    
    docs_sorted = sorted(docs, key=lambda d: datetime.strptime(d["datum"], "%d.%m.%Y"))
    msg = "📋 *Svi dokumenti:*\n\n"
    
    for d in docs_sorted[:20]:
        label, _, _ = status_info(d["datum"], d.get("priority", "medium"))
        msg += f"{label} *{d['naziv']}*\n📅 {d['datum']}\n\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def hitno(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    docs = get_user_docs(user_id)
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    
    filtered = [(d, (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days) 
                for d in docs if 0 <= (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days <= 7]
    
    if not filtered:
        await update.message.reply_text("✅ Nema hitnih dokumenata.")
        return
    
    msg = f"🔥 *Hitno ({len(filtered)}):*\n\n"
    for d, diff in sorted(filtered, key=lambda x: x[1]):
        msg += f"• *{d['naziv']}* — za {diff} dana\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def uskoro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    docs = get_user_docs(user_id)
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    
    filtered = [(d, (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days) 
                for d in docs if 0 <= (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days <= 30]
    
    if not filtered:
        await update.message.reply_text("✅ Nema dokumenata koji ističu.")
        return
    
    msg = f"🟡 *Uskoro ističe ({len(filtered)}):*\n\n"
    for d, diff in sorted(filtered, key=lambda x: x[1]):
        msg += f"• *{d['naziv']}* — za {diff} dana\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def isteklo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    docs = get_user_docs(user_id)
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    
    filtered = [(d, abs((datetime.strptime(d["datum"], "%d.%m.%Y") - today).days)) 
                for d in docs if (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days < 0]
    
    if not filtered:
        await update.message.reply_text("✅ Nema isteklih dokumenata.")
        return
    
    msg = f"🔴 *Isteklo ({len(filtered)}):*\n\n"
    for d, diff in sorted(filtered, key=lambda x: x[1]):
        msg += f"• *{d['naziv']}* — {diff} dana isteklo\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def brisanje(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    docs = get_user_docs(user_id)
    
    if not docs:
        await update.message.reply_text("📭 Nema dokumenata za brisanje.")
        return
    
    ctx.user_data["docs_za_brisanje"] = docs
    
    keyboard = []
    for i, doc in enumerate(docs[:20]):
        keyboard.append([InlineKeyboardButton(f"{doc['naziv'][:30]}", callback_data=f"brisi_{i}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Otkaži", callback_data="main")])
    
    await update.message.reply_text(
        "🗑️ *Koji dokument da obrišem?*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def izvjestaj(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    msg = build_report(user_id)
    if msg:
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("✅ *Sve je uređeno!*", parse_mode="Markdown")

async def podsjetnik_on(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    settings = load_settings()
    if "users" not in settings:
        settings["users"] = {}
    if str(user_id) not in settings["users"]:
        settings["users"][str(user_id)] = {}
    settings["users"][str(user_id)]["podsjetnici"] = True
    save_settings(settings)
    await update.message.reply_text("🔔 *Podsjetnici uključeni!*", parse_mode="Markdown")

async def podsjetnik_off(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    settings = load_settings()
    if "users" in settings and str(user_id) in settings["users"]:
        settings["users"][str(user_id)]["podsjetnici"] = False
        save_settings(settings)
    await update.message.reply_text("🔕 *Podsjetnici isključeni.*", parse_mode="Markdown")

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_chat.id
    
    if data == "main":
        keyboard = [
            [InlineKeyboardButton("📄 Dodaj dokument", callback_data="dodaj")],
            [InlineKeyboardButton("📋 Moji dokumenti", callback_data="lista")],
            [InlineKeyboardButton("🔥 Hitni dokumenti", callback_data="hitno")],
            [InlineKeyboardButton("📊 Statistika", callback_data="statistika")],
            [InlineKeyboardButton("⚙️ Podešavanja", callback_data="settings")]
        ]
        await query.edit_message_text("🏠 *Glavni meni*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data == "dodaj":
        await query.edit_message_text("📄 *Naziv dokumenta?*", parse_mode="Markdown")
        return NAZIV
    
    elif data == "lista":
        docs = get_user_docs(user_id)
        if not docs:
            await query.edit_message_text("📭 Nema dokumenata.")
            return
        msg = "📋 *Svi dokumenti:*\n\n"
        for d in sorted(docs, key=lambda x: datetime.strptime(x["datum"], "%d.%m.%Y"))[:10]:
            label, _, _ = status_info(d["datum"], d.get("priority", "medium"))
            msg += f"{label} *{d['naziv']}*\n📅 {d['datum']}\n\n"
        await query.edit_message_text(msg, parse_mode="Markdown")
    
    elif data == "hitno":
        docs = get_user_docs(user_id)
        today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
        filtered = [(d, (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days) 
                    for d in docs if 0 <= (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days <= 7]
        if not filtered:
            await query.edit_message_text("✅ Nema hitnih.")
            return
        msg = f"🔥 *Hitno:*\n\n"
        for d, diff in filtered:
            msg += f"• {d['naziv']} — {diff} dana\n"
        await query.edit_message_text(msg, parse_mode="Markdown")
    
    elif data == "statistika":
        docs = get_user_docs(user_id)
        total = len(docs)
        await query.edit_message_text(f"📊 *Statistika*\n\n📄 Ukupno: {total}", parse_mode="Markdown")
    
    elif data == "settings":
        await query.edit_message_text(
            "⚙️ *Podešavanja*\n\n"
            "/podsjetnik_on — uključi\n"
            "/podsjetnik_off — isključi",
            parse_mode="Markdown"
        )
    
    elif data.startswith("brisi_"):
        idx = int(data.split("_")[1])
        docs = ctx.user_data.get("docs_za_brisanje", [])
        if 0 <= idx < len(docs):
            doc = docs[idx]
            all_docs = load_docs()
            all_docs = [d for d in all_docs if d["id"] != doc["id"]]
            save_docs(all_docs)
            await query.edit_message_text(f"✅ Obrisan: {doc['naziv']}")

# ==================== MAIN ====================
def main():
    if not TOKEN:
        logger.error("❌ BOT_TOKEN nije postavljen!")
        return
    
    # Kreiraj aplikaciju BEZ job_queue (da ne baca grešku)
    app = Application.builder().token(TOKEN).build()
    
    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("dodaj", dodaj_start),
            CallbackQueryHandler(callback_handler, pattern="^dodaj$")
        ],
        states={
            NAZIV: [MessageHandler(filters.TEXT & ~filters.COMMAND, dodaj_naziv)],
            KATEGORIJA: [CallbackQueryHandler(dodaj_kategorija, pattern="^kat_")],
            PRIORITET: [CallbackQueryHandler(dodaj_prioritet, pattern="^prio_")],
            DATUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, dodaj_datum)],
        },
        fallbacks=[CommandHandler("cancel", dodaj_cancel)],
        allow_reentry=True
    )
    
    # Dodaj sve handlere
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pomoc", pomoc))
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("hitno", hitno))
    app.add_handler(CommandHandler("uskoro", uskoro))
    app.add_handler(CommandHandler("isteklo", isteklo))
    app.add_handler(CommandHandler("brisanje", brisanje))
    app.add_handler(CommandHandler("izvjestaj", izvjestaj))
    app.add_handler(CommandHandler("podsjetnik_on", podsjetnik_on))
    app.add_handler(CommandHandler("podsjetnik_off", podsjetnik_off))
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    # Message handler za AI (mora biti posljednji)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Pokreni bota
    logger.info("🤖 Bot je pokrenut!")
    logger.info("📌 Komande: /start, /dodaj, /lista, /pomoc")
    
    # Railway će automatski restartovati bota ako padne
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
