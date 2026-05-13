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
from openai import AsyncOpenAI

# ==================== LOGGING ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== KONFIGURACIJA ====================
TOKEN = os.environ.get("BOT_TOKEN")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")

# Provjera da li je API ključ postavljen
if not DEEPSEEK_API_KEY:
    logger.warning("⚠️ DEEPSEEK_API_KEY nije postavljen! AI chat neće raditi.")

# Inicijalizacija DeepSeek klijenta (ako ima ključa)
deepseek_client = None
if DEEPSEEK_API_KEY:
    deepseek_client = AsyncOpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com/v1"
    )
    logger.info("✅ DeepSeek AI klijent inicijaliziran")

# Fajlovi za podatke - koristimo Railway volume (perzistentni storage)
DATA_FILE = "data/dokumenti.json"
SETTINGS_FILE = "data/settings.json"
USERS_FILE = "data/users.json"
CHAT_HISTORY_FILE = "data/chat_history.json"

# Kreiraj data folder ako ne postoji
os.makedirs("data", exist_ok=True)

# Konstantne za ConversationHandler
NAZIV, DATUM, KATEGORIJA, PRIORITET, NAPOMENA = range(5)
KATEGORIJE = ["📄 Lična", "💼 Poslovna", "🏥 Zdravstvo", "🚗 Auto", "🏠 Stambena", "🔒 Osiguranje", "🎓 Obrazovna", "💳 Finansijska"]
PRIORITETI = [("🔴 Visok", "high"), ("🟠 Srednji", "medium"), ("🟢 Nizak", "low")]

# ==================== POMOĆNE FUNKCIJE ====================
def load_docs() -> List[Dict]:
    """Učitaj dokumente iz JSON fajla"""
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Greška pri učitavanju dokumenata: {e}")
    return []

def save_docs(docs: List[Dict]) -> bool:
    """Sačuvaj dokumente u JSON fajl"""
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(docs, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Greška pri čuvanju dokumenata: {e}")
        return False

def load_settings() -> Dict:
    """Učitaj podešavanja"""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Greška pri učitavanju podešavanja: {e}")
    return {"users": {}}

def save_settings(s: Dict) -> bool:
    """Sačuvaj podešavanja"""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Greška pri čuvanju podešavanja: {e}")
        return False

def load_users() -> Dict:
    """Učitaj korisnike"""
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Greška pri učitavanju korisnika: {e}")
    return {}

def save_users(users: Dict) -> bool:
    """Sačuvaj korisnike"""
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Greška pri čuvanju korisnika: {e}")
        return False

def load_chat_history(user_id: int) -> List[Dict]:
    """Učitaj prethodne poruke za korisnika"""
    try:
        if os.path.exists(CHAT_HISTORY_FILE):
            with open(CHAT_HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
                return history.get(str(user_id), [])[-10:]
    except Exception as e:
        logger.error(f"Greška pri učitavanju chat historije: {e}")
    return []

def save_chat_history(user_id: int, messages: List[Dict]) -> None:
    """Sačuvaj chat history za korisnika"""
    try:
        history = {}
        if os.path.exists(CHAT_HISTORY_FILE):
            with open(CHAT_HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        
        history[str(user_id)] = messages[-10:]
        with open(CHAT_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Greška pri čuvanju chat historije: {e}")

def get_user_docs(user_id: int) -> List[Dict]:
    """Dohvati dokumente samo za određenog korisnika"""
    docs = load_docs()
    return [d for d in docs if d.get("user_id") == user_id]

def status_info(date_str: str, priority: str = "medium") -> tuple:
    """Vrati status dokumenta sa emojijima"""
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
    """Parsiraj datum iz različitih formata"""
    formats = ["%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y"]
    for fmt in formats:
        try:
            return datetime.strptime(text.strip(), fmt).strftime("%d.%m.%Y")
        except:
            continue
    return None

def build_report(user_id: int) -> Optional[str]:
    """Napravi izvještaj za korisnika"""
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

    msg = f"🌅 *Jutarnji izvještaj* — {today.strftime('%d.%m.%Y')}\n\n"
    
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

# ==================== AI CHAT FUNKCIJA ====================
async def ai_chat(user_id: int, message: str) -> Optional[str]:
    """Komuniciraj sa DeepSeek AI"""
    if not deepseek_client:
        return "🤖 AI chat trenutno nije dostupan. Administrator će uskoro omogućiti ovu funkciju."
    
    try:
        # Učitaj prethodni kontekst
        history = load_chat_history(user_id)
        
        # Pripremi poruke za API
        messages = [
            {"role": "system", "content": "Ti si koristan asistent na srpskom/bosanskom/hrvatskom jeziku. Odgovaraj kratko i precizno, maksimalno 3 rečenice."}
        ]
        
        # Dodaj prethodne poruke iz historije
        for h in history:
            messages.append(h)
        
        # Dodaj trenutnu poruku
        messages.append({"role": "user", "content": message})
        
        # Pozovi DeepSeek API
        response = await deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            max_tokens=300,
            temperature=0.7
        )
        
        ai_response = response.choices[0].message.content
        
        # Sačuvaj historiju
        messages.append({"role": "assistant", "content": ai_response})
        save_chat_history(user_id, messages)
        
        return ai_response
        
    except Exception as e:
        logger.error(f"AI chat greška: {e}")
        return "❌ Nažalost, došlo je do greške. Pokušaj ponovo za minut."

# ==================== TELEGRAM HANDLERI ====================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Početna poruka i meni"""
    user_id = update.effective_chat.id
    username = update.effective_user.username or "Korisnik"
    
    # Registruj korisnika
    users = load_users()
    if str(user_id) not in users:
        users[str(user_id)] = {
            "username": username,
            "first_name": update.effective_user.first_name,
            "registered_at": datetime.now().strftime("%d.%m.%Y %H:%M")
        }
        save_users(users)
        logger.info(f"Novi korisnik registrovan: {username} ({user_id})")
    
    keyboard = [
        [InlineKeyboardButton("📄 Dodaj dokument", callback_data="dodaj")],
        [InlineKeyboardButton("📋 Moji dokumenti", callback_data="lista")],
        [InlineKeyboardButton("🔥 Hitni dokumenti", callback_data="hitno")],
        [InlineKeyboardButton("📊 Statistika", callback_data="statistika")],
        [InlineKeyboardButton("⚙️ Podešavanja", callback_data="settings")]
    ]
    
    await update.message.reply_text(
        f"👋 *Zdravo {update.effective_user.first_name}!*\n\n"
        f"Dobrodošao u *Evidenciju dokumenata* 📋\n\n"
        f"🤖 *Meni:*\n"
        f"• Dodaj dokumente sa rokovima\n"
        f"• Prati šta ističe\n"
        f"• Postavi podsjetnike\n"
        f"• Pitaj AI asistenta bilo šta!\n\n"
        f"📌 *Komande:*\n"
        f"/dodaj — dodaj dokument\n"
        f"/lista — svi dokumenti\n"
        f"/uskoro — ističe uskoro\n"
        f"/hitno — ističe u 7 dana\n"
        f"/isteklo — istekli dokumenti\n"
        f"/statistika — pregled\n"
        f"/pomoc — sve komande\n\n"
        f"💬 *Prosto pitaj:*\n"
        f"Napiši bilo šta i AI će ti odgovoriti!",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def pomoc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Prikaži sve komande"""
    await update.message.reply_text(
        "📚 *Sve komande:*\n\n"
        "📄 *Upravljanje dokumentima:*\n"
        "/dodaj — dodaj novi dokument\n"
        "/lista — prikaži sve dokumente\n"
        "/uskoro — dokumenti koji ističu za 30 dana\n"
        "/hitno — dokumenti koji ističu za 7 dana\n"
        "/isteklo — istekli dokumenti\n"
        "/brisanje — obriši dokument\n\n"
        "📊 *Statistika:*\n"
        "/statistika — pregled i grafikoni\n\n"
        "🔔 *Podsjetnici:*\n"
        "/podsjetnik_on — uključi jutarnje podsjetnike\n"
        "/podsjetnik_off — isključi podsjetnike\n"
        "/izvjestaj — ručno generiši izvještaj\n\n"
        "💬 *AI Chat:*\n"
        "Samo napiši bilo koju poruku i AI će odgovoriti!\n\n"
        "❓ *Pomoć:*\n"
        "/pomoc — ova poruka\n"
        "/start — glavni meni",
        parse_mode="Markdown"
    )

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Obradi sve poruke koje nisu komande"""
    user_id = update.effective_chat.id
    message_text = update.message.text.strip()
    
    # Ako je poruka broj (za brisanje) - preskoči
    if message_text.isdigit() and ctx.user_data.get("docs_za_brisanje"):
        return
    
    # Pokaži da bot kuca
    await ctx.bot.send_chat_action(chat_id=user_id, action="typing")
    
    # Pošalji AI odgovor
    response = await ai_chat(user_id, message_text)
    await update.message.reply_text(response, parse_mode="Markdown")

async def statistika(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Prikaži statistiku dokumenata"""
    user_id = update.effective_chat.id
    docs = get_user_docs(user_id)
    
    if not docs:
        await update.message.reply_text("📭 Nema dokumenata za statistiku. Dodaj prvi sa /dodaj")
        return
    
    total = len(docs)
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    
    expired = critical = soon = ok = 0
    for d in docs:
        diff = (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days
        if diff < 0:
            expired += 1
        elif diff <= 7:
            critical += 1
        elif diff <= 30:
            soon += 1
        else:
            ok += 1
    
    # Statistika po kategorijama
    cats = {}
    for d in docs:
        cat = d.get("kategorija", "Bez kategorije")
        cats[cat] = cats.get(cat, 0) + 1
    
    msg = f"📊 *Statistika dokumenata*\n\n"
    msg += f"📄 Ukupno: *{total}*\n"
    msg += f"🔴 Isteklo: *{expired}*\n"
    msg += f"🔥 Kritično (0-7 dana): *{critical}*\n"
    msg += f"🟡 Uskoro (8-30 dana): *{soon}*\n"
    msg += f"🟢 Ok (>30 dana): *{ok}*\n\n"
    msg += f"📂 *Kategorije:*\n"
    for cat, count in sorted(cats.items(), key=lambda x: x[1], reverse=True)[:5]:
        msg += f"• {cat}: {count}\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

# ==================== DODAVANJE DOKUMENATA ====================
async def dodaj_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Počni proces dodavanja dokumenta"""
    await update.message.reply_text(
        "📄 *Naziv dokumenta?*\n\n"
        "Primjeri: _Registracija vozila, Pasoš, Ugovor o radu_",
        parse_mode="Markdown"
    )
    return NAZIV

async def dodaj_naziv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Primi naziv dokumenta"""
    ctx.user_data["naziv"] = update.message.text.strip()
    
    keyboard = [[InlineKeyboardButton(kat, callback_data=f"kat_{kat}")] for kat in KATEGORIJE]
    keyboard.append([InlineKeyboardButton("⏭️ Preskoči", callback_data="kat_skip")])
    
    await update.message.reply_text(
        f"📂 *Izaberi kategoriju za:* _{ctx.user_data['naziv']}_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return KATEGORIJA

async def dodaj_kategorija(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Primi kategoriju"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "kat_skip":
        ctx.user_data["kategorija"] = None
    else:
        ctx.user_data["kategorija"] = query.data.replace("kat_", "")
    
    keyboard = [[InlineKeyboardButton(naziv, callback_data=f"prio_{vrijednost}")] for naziv, vrijednost in PRIORITETI]
    
    await query.edit_message_text(
        f"⚠️ *Izaberi prioritet za:* _{ctx.user_data['naziv']}_\n\n"
        f"🔴 Visok — alarm za 7 dana\n"
        f"🟠 Srednji — alarm za 30 dana\n"
        f"🟢 Nizak — običan",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return PRIORITET

async def dodaj_prioritet(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Primi prioritet"""
    query = update.callback_query
    await query.answer()
    
    ctx.user_data["priority"] = query.data.replace("prio_", "")
    
    await query.edit_message_text(
        f"📅 *Datum isteka za:* _{ctx.user_data['naziv']}_\n\n"
        f"Unesi datum: `31.12.2025`, `31/12/2025` ili `31-12-2025`",
        parse_mode="Markdown"
    )
    return DATUM

async def dodaj_datum(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Primi datum i sačuvaj dokument"""
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
        "created_at": datetime.now().strftime("%d.%m.%Y %H:%M")
    }
    docs.append(doc)
    save_docs(docs)
    
    label, _, _ = status_info(date_str, ctx.user_data.get("priority", "medium"))
    
    await update.message.reply_text(
        f"✅ *Sačuvano!*\n\n"
        f"📄 {doc['naziv']}\n"
        f"📅 {doc['datum']}\n"
        f"🏷️ {doc.get('kategorija', 'Bez kategorije')}\n"
        f"⚠️ Prioritet: {doc.get('priority', 'srednji')}\n"
        f"\nStatus: {label}",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def dodaj_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Otkaži dodavanje"""
    await update.message.reply_text("❌ Otkazano.")
    return ConversationHandler.END

# ==================== OSTALE FUNKCIJE ====================
async def lista(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Prikaži sve dokumente"""
    user_id = update.effective_chat.id
    docs = get_user_docs(user_id)
    
    if not docs:
        await update.message.reply_text("📭 Nema dokumenata. Dodaj prvi sa /dodaj")
        return
    
    docs_sorted = sorted(docs, key=lambda d: datetime.strptime(d["datum"], "%d.%m.%Y"))
    msg = "📋 *Svi dokumenti:*\n\n"
    
    for d in docs_sorted[:20]:
        label, _, _ = status_info(d["datum"], d.get("priority", "medium"))
        msg += f"{label} *{d['naziv']}*\n"
        msg += f"📅 {d['datum']}"
        if d.get("kategorija"):
            msg += f" [{d['kategorija']}]"
        msg += "\n\n"
    
    if len(docs_sorted) > 20:
        msg += f"\n_... i još {len(docs_sorted) - 20} dokumenata_"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def hitno(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Prikaži hitne dokumente (istiću u 7 dana)"""
    user_id = update.effective_chat.id
    docs = get_user_docs(user_id)
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    
    filtered = []
    for d in docs:
        diff = (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days
        if 0 <= diff <= 7:
            filtered.append((d, diff))
    
    filtered.sort(key=lambda x: x[1])
    
    if not filtered:
        await update.message.reply_text("✅ Nema hitnih dokumenata (istiću u 7 dana).")
        return
    
    msg = f"🔥 *HITNO! Ističe u 7 dana ({len(filtered)}):*\n\n"
    for d, diff in filtered:
        msg += f"• *{d['naziv']}* — za {diff} dana ⚠️\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def uskoro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Prikaži dokumente koji ističu za 30 dana"""
    user_id = update.effective_chat.id
    docs = get_user_docs(user_id)
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    
    filtered = []
    for d in docs:
        diff = (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days
        if 0 <= diff <= 30:
            filtered.append((d, diff))
    
    filtered.sort(key=lambda x: x[1])
    
    if not filtered:
        await update.message.reply_text("✅ Nema dokumenata koji ističu u narednih 30 dana.")
        return
    
    msg = f"🟡 *Uskoro ističe ({len(filtered)}):*\n\n"
    for d, diff in filtered:
        msg += f"• *{d['naziv']}* — za {diff} dana\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def isteklo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Prikaži istekle dokumente"""
    user_id = update.effective_chat.id
    docs = get_user_docs(user_id)
    today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    
    filtered = []
    for d in docs:
        diff = (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days
        if diff < 0:
            filtered.append((d, abs(diff)))
    
    filtered.sort(key=lambda x: x[1])
    
    if not filtered:
        await update.message.reply_text("✅ Nema isteklih dokumenata.")
        return
    
    msg = f"🔴 *Isteklo ({len(filtered)}):*\n\n"
    for d, diff in filtered:
        msg += f"• *{d['naziv']}* — {diff} dana isteklo\n"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

async def brisanje(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Obriši dokument"""
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
        "🗑️ *Koji dokument želiš da obrišeš?*\n\n⚠️ *Ova radnja je trajna!*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def izvjestaj(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Pošalji izvještaj"""
    user_id = update.effective_chat.id
    msg = build_report(user_id)
    if msg:
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("✅ *Sve je uređeno!* Nema isteklih ni dokumenata koji uskoro ističu.", parse_mode="Markdown")

async def podsjetnik_on(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Uključi podsjetnike"""
    user_id = update.effective_chat.id
    settings = load_settings()
    if "users" not in settings:
        settings["users"] = {}
    if str(user_id) not in settings["users"]:
        settings["users"][str(user_id)] = {}
    settings["users"][str(user_id)]["podsjetnici"] = True
    save_settings(settings)
    await update.message.reply_text("🔔 *Podsjetnici uključeni!* Svaki dan u 8:00 dobijaš izvještaj.", parse_mode="Markdown")

async def podsjetnik_off(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Isključi podsjetnike"""
    user_id = update.effective_chat.id
    settings = load_settings()
    if "users" in settings and str(user_id) in settings["users"]:
        settings["users"][str(user_id)]["podsjetnici"] = False
        save_settings(settings)
    await update.message.reply_text("🔕 *Podsjetnici isključeni.*", parse_mode="Markdown")

async def podsjetnik_job(ctx: ContextTypes.DEFAULT_TYPE):
    """Job za slanje jutarnjih podsjetnika"""
    settings = load_settings()
    for user_id, user_settings in settings.get("users", {}).items():
        if user_settings.get("podsjetnici", False):
            msg = build_report(int(user_id))
            if msg:
                try:
                    await ctx.bot.send_message(chat_id=int(user_id), text=msg, parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Greška pri slanju podsjetnika korisniku {user_id}: {e}")

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Obradi sve callback dugmadi"""
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
        await query.edit_message_text(
            "📄 *Naziv dokumenta?*\n\nPrimjeri: _Registracija, Pasoš, Ugovor_",
            parse_mode="Markdown"
        )
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
            await query.edit_message_text("✅ Nema hitnih dokumenata.")
            return
        
        msg = f"🔥 *Hitno ({len(filtered)}):*\n\n"
        for d, diff in filtered:
            msg += f"• {d['naziv']} — {diff} dana\n"
        await query.edit_message_text(msg, parse_mode="Markdown")
    
    elif data == "statistika":
        docs = get_user_docs(user_id)
        if not docs:
            await query.edit_message_text("📭 Nema dokumenata.")
            return
        
        total = len(docs)
        today = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
        expired = sum(1 for d in docs if (datetime.strptime(d["datum"], "%d.%m.%Y") - today).days < 0)
        
        await query.edit_message_text(
            f"📊 *Statistika*\n\n📄 Ukupno: {total}\n🔴 Isteklo: {expired}\n✅ Aktivnih: {total - expired}",
            parse_mode="Markdown"
        )
    
    elif data == "settings":
        await query.edit_message_text(
            "⚙️ *Podešavanja*\n\n"
            "🔔 /podsjetnik_on — uključi podsjetnike\n"
            "🔕 /podsjetnik_off — isključi podsjetnike",
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
            await query.edit_message_text(f"✅ *Obrisan:* {doc['naziv']}", parse_mode="Markdown")

# ==================== MAIN ====================
def main():
    """Pokreni bota"""
    if not TOKEN:
        logger.error("BOT_TOKEN nije postavljen!")
        return
    
    # Kreiraj aplikaciju
    app = Application.builder().token(TOKEN).build()
    
    # Conversation handler za dodavanje dokumenata
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
    )
    
    # Dodaj sve handlere
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("pomoc", pomoc))
    app.add_handler(CommandHandler("dodaj", dodaj_start))
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("hitno", hitno))
    app.add_handler(CommandHandler("uskoro", uskoro))
    app.add_handler(CommandHandler("isteklo", isteklo))
    app.add_handler(CommandHandler("statistika", statistika))
    app.add_handler(CommandHandler("brisanje", brisanje))
    app.add_handler(CommandHandler("izvjestaj", izvjestaj))
    app.add_handler(CommandHandler("podsjetnik_on", podsjetnik_on))
    app.add_handler(CommandHandler("podsjetnik_off", podsjetnik_off))
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    # Message handler za AI chat (mora biti posljednji)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Dodaj job queue za jutarnje podsjetnike
    app.job_queue.run_daily(podsjetnik_job, time=time(hour=8, minute=0), name="jutarnji_podsjetnici")
    
    # Pokreni bota
    logger.info("🤖 Bot je pokrenut!")
    logger.info("📌 Komande: /start, /dodaj, /lista, /hitno, /statistika, /pomoc")
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
