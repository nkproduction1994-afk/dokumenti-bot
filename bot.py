import os
import json
import asyncio
import random
import httpx
from datetime import datetime, time
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, JobQueue

TOKEN = os.environ.get("BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DATA_FILE = "dokumenti.json"
SETTINGS_FILE = "settings.json"
NAPOMENE_FILE = "napomene.json"
FAJLOVI_FILE = "fajlovi.json"
FILES_DIR = "files"

NAZIV, DATUM = range(2)
NAP_TEKST, NAP_DATUM, NAP_VRIJEME, NAP_DOKUMENT = range(4, 8)
SACUVAJ_NAZIV, SACUVAJ_FAJL, SACUVAJ_DOKUMENT = range(8, 11)

# ── Goca fraze ──────────────────────────────────────────────────────────────
GOCA_FRAZE = [
    "🐌 Da li ste znali da puževi mogu spavati mesecima bez hrane?",
    "🐌 Da li ste znali da puževi imaju hiljade sitnih zuba na jeziku?",
    "🐌 Da li ste znali da puževi ostavljaju sluz kako bi lakše klizili po površinama?",
    "🐌 Da li ste znali da neki puževi mogu nositi kućicu težu od svog tela?",
    "🐌 Da li ste znali da puževi mogu preživeti i veoma hladne uslove skrivajući se u zemlji?",
]

# ── Osnovno: dokumenti ──────────────────────────────────────────────────────
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

def parse_datetime(date_str, time_str):
    """Parsira datum i vrijeme, vraća datetime ili None."""
    date = parse_date(date_str)
    if not date:
        return None
    try:
        t = datetime.strptime(time_str.strip(), "%H:%M")
        dt = datetime.strptime(date, "%d.%m.%Y").replace(hour=t.hour, minute=t.minute, second=0)
        return dt
    except:
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

# ── Napomene ─────────────────────────────────────────────────────────────────
def load_napomene():
    if os.path.exists(NAPOMENE_FILE):
        with open(NAPOMENE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_napomene(naps):
    with open(NAPOMENE_FILE, "w", encoding="utf-8") as f:
        json.dump(naps, f, ensure_ascii=False, indent=2)

async def napomena_job(ctx: ContextTypes.DEFAULT_TYPE):
    """Šalje napomenu korisniku u zakazano vrijeme."""
    data = ctx.job.data
    chat_id = data["chat_id"]
    tekst = data["tekst"]
    nap_id = data["id"]

    msg = f"🔔 *Podsjetnik!*\n\n{tekst}"
    await ctx.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")

    # Obriši iz liste napomena
    naps = load_napomene()
    naps = [n for n in naps if n["id"] != nap_id]
    save_napomene(naps)

def schedule_napomena(job_queue, napomena, chat_id):
    """Zakazuje job za napomenu."""
    dt = datetime.strptime(napomena["datetime"], "%d.%m.%Y %H:%M")
    now = datetime.now()
    if dt <= now:
        return False
    delay = (dt - now).total_seconds()
    job_queue.run_once(
        napomena_job,
        when=delay,
        data={"chat_id": chat_id, "tekst": napomena["tekst"], "id": napomena["id"]},
        name=f"nap_{napomena['id']}"
    )
    return True

async def napomena_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📝 *Nova napomena / podsjetnik*\n\n"
        "Unesi tekst napomene:\n"
        "_(npr. Produžiti registraciju auta, Platiti osiguranje...)_",
        parse_mode="Markdown"
    )
    return NAP_TEKST

async def napomena_tekst(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["nap_tekst"] = update.message.text.strip()
    await update.message.reply_text(
        f"📅 *Datum podsjetnika za:* _{ctx.user_data['nap_tekst']}_\n\n"
        "Unesi datum: `31.12.2025`",
        parse_mode="Markdown"
    )
    return NAP_DATUM

async def napomena_datum(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    date_str = parse_date(update.message.text)
    if not date_str:
        await update.message.reply_text("❌ Neispravan format datuma. Unesi: `31.12.2025`", parse_mode="Markdown")
        return NAP_DATUM
    ctx.user_data["nap_datum"] = date_str
    await update.message.reply_text(
        f"⏰ *Vrijeme podsjetnika za {date_str}:*\n\n"
        "Unesi sat i minut: `08:30`",
        parse_mode="Markdown"
    )
    return NAP_VRIJEME

async def napomena_vrijeme(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    time_str = update.message.text.strip()
    dt = parse_datetime(ctx.user_data["nap_datum"], time_str)
    if not dt:
        await update.message.reply_text("❌ Neispravan format vremena. Unesi npr: `08:30`", parse_mode="Markdown")
        return NAP_VRIJEME

    if dt <= datetime.now():
        await update.message.reply_text("❌ Taj datum/vrijeme je u prošlosti. Unesi budući datum.", parse_mode="Markdown")
        return NAP_DATUM

    ctx.user_data["nap_datetime"] = dt.strftime("%d.%m.%Y %H:%M")

    # Ponudi vezivanje za dokument
    docs = load_docs()
    if docs:
        docs_sorted = sorted(docs, key=lambda d: datetime.strptime(d["datum"], "%d.%m.%Y"))
        msg = "📎 *Veži za dokument?* (opcionalno)\n\nPošalji broj ili `0` za preskakanje:\n\n"
        for i, d in enumerate(docs_sorted, 1):
            msg += f"{i}. {d['naziv']} — {d['datum']}\n"
        ctx.user_data["docs_za_nap"] = docs_sorted
        await update.message.reply_text(msg, parse_mode="Markdown")
        return NAP_DOKUMENT
    else:
        await _sacuvaj_napomenu(update, ctx, dokument=None)
        return ConversationHandler.END

async def napomena_dokument(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    dokument = None
    docs_lista = ctx.user_data.get("docs_za_nap", [])

    if text != "0":
        try:
            br = int(text)
            if 1 <= br <= len(docs_lista):
                dokument = docs_lista[br - 1]
        except:
            pass

    await _sacuvaj_napomenu(update, ctx, dokument=dokument)
    return ConversationHandler.END

async def _sacuvaj_napomenu(update, ctx, dokument):
    naps = load_napomene()
    settings = load_settings()
    chat_id = settings.get("chat_id", update.effective_chat.id)

    nap = {
        "id": int(datetime.now().timestamp() * 1000),
        "tekst": ctx.user_data["nap_tekst"],
        "datetime": ctx.user_data["nap_datetime"],
        "dokument": dokument["naziv"] if dokument else None,
        "chat_id": chat_id
    }
    naps.append(nap)
    save_napomene(naps)

    schedule_napomena(ctx.application.job_queue, nap, chat_id)

    doc_info = f"\n📎 Vezano za: *{dokument['naziv']}*" if dokument else ""
    await update.message.reply_text(
        f"✅ *Podsjetnik sačuvan!*\n\n"
        f"📝 {nap['tekst']}\n"
        f"⏰ {nap['datetime']}"
        f"{doc_info}",
        parse_mode="Markdown"
    )

async def napomena_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Otkazano.")
    return ConversationHandler.END

async def lista_napomena(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    naps = load_napomene()
    now = datetime.now()
    # Filtriraj samo buduće
    aktivne = [n for n in naps if datetime.strptime(n["datetime"], "%d.%m.%Y %H:%M") > now]
    aktivne.sort(key=lambda x: x["datetime"])

    if not aktivne:
        await update.message.reply_text("📭 Nema aktivnih podsjetnika.")
        return

    msg = f"🔔 *Aktivni podsjetnici ({len(aktivne)}):*\n\n"
    for i, n in enumerate(aktivne, 1):
        doc_info = f" _(📎 {n['dokument']})_" if n.get("dokument") else ""
        msg += f"{i}. *{n['tekst']}*\n⏰ {n['datetime']}{doc_info}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def brisanje_napomene(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    naps = load_napomene()
    now = datetime.now()
    aktivne = [n for n in naps if datetime.strptime(n["datetime"], "%d.%m.%Y %H:%M") > now]
    aktivne.sort(key=lambda x: x["datetime"])

    if not aktivne:
        await update.message.reply_text("📭 Nema aktivnih podsjetnika za brisanje.")
        return

    msg = "🗑 *Koji podsjetnik obrisati?*\n\nPošalji broj:\n\n"
    for i, n in enumerate(aktivne, 1):
        msg += f"{i}. {n['tekst']} — {n['datetime']}\n"

    ctx.user_data["naps_za_brisanje"] = aktivne
    await update.message.reply_text(msg, parse_mode="Markdown")

# ── Fajlovi ──────────────────────────────────────────────────────────────────
def load_fajlovi():
    if os.path.exists(FAJLOVI_FILE):
        with open(FAJLOVI_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_fajlovi(fajlovi):
    with open(FAJLOVI_FILE, "w", encoding="utf-8") as f:
        json.dump(fajlovi, f, ensure_ascii=False, indent=2)

def ensure_files_dir():
    if not os.path.exists(FILES_DIR):
        os.makedirs(FILES_DIR)

async def sacuvaj_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💾 *Čuvanje fajla*\n\n"
        "Prvo unesi naziv/opis fajla:\n"
        "_(npr. Ugovor o radu, Polica osiguranja, Tehnički pregled...)_",
        parse_mode="Markdown"
    )
    return SACUVAJ_NAZIV

async def sacuvaj_naziv(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["fajl_naziv"] = update.message.text.strip()
    await update.message.reply_text(
        f"📎 *Pošalji fajl za:* _{ctx.user_data['fajl_naziv']}_\n\n"
        "Podržano: PDF, slike, Word, Excel, ZIP i ostalo.",
        parse_mode="Markdown"
    )
    return SACUVAJ_FAJL

async def sacuvaj_fajl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    # Prihvata dokument, sliku, audio, video...
    file_obj = None
    original_name = "fajl"

    if update.message.document:
        file_obj = update.message.document
        original_name = file_obj.file_name or "dokument"
    elif update.message.photo:
        file_obj = update.message.photo[-1]
        original_name = f"slika_{int(datetime.now().timestamp())}.jpg"
    elif update.message.audio:
        file_obj = update.message.audio
        original_name = file_obj.file_name or "audio.mp3"
    elif update.message.video:
        file_obj = update.message.video
        original_name = file_obj.file_name or "video.mp4"
    else:
        await update.message.reply_text(
            "❌ Pošalji fajl (dokument, sliku, audio ili video).",
            parse_mode="Markdown"
        )
        return SACUVAJ_FAJL

    ensure_files_dir()
    fajl_id = int(datetime.now().timestamp() * 1000)
    ext = os.path.splitext(original_name)[1] if "." in original_name else ""
    local_name = f"{fajl_id}{ext}"
    local_path = os.path.join(FILES_DIR, local_name)

    tg_file = await file_obj.get_file()
    await tg_file.download_to_drive(local_path)

    ctx.user_data["fajl_id"] = fajl_id
    ctx.user_data["fajl_local"] = local_path
    ctx.user_data["fajl_original"] = original_name
    ctx.user_data["fajl_tg_id"] = file_obj.file_id

    # Ponudi vezivanje za dokument
    docs = load_docs()
    if docs:
        docs_sorted = sorted(docs, key=lambda d: datetime.strptime(d["datum"], "%d.%m.%Y"))
        msg = "📎 *Veži za dokument?* (opcionalno)\n\nPošalji broj ili `0` za preskakanje:\n\n"
        for i, d in enumerate(docs_sorted, 1):
            msg += f"{i}. {d['naziv']} — {d['datum']}\n"
        ctx.user_data["docs_za_fajl"] = docs_sorted
        await update.message.reply_text(msg, parse_mode="Markdown")
        return SACUVAJ_DOKUMENT
    else:
        await _sacuvaj_fajl_finalize(update, ctx, dokument=None)
        return ConversationHandler.END

async def sacuvaj_dokument(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    dokument = None
    docs_lista = ctx.user_data.get("docs_za_fajl", [])

    if text != "0":
        try:
            br = int(text)
            if 1 <= br <= len(docs_lista):
                dokument = docs_lista[br - 1]
        except:
            pass

    await _sacuvaj_fajl_finalize(update, ctx, dokument=dokument)
    return ConversationHandler.END

async def _sacuvaj_fajl_finalize(update, ctx, dokument):
    fajlovi = load_fajlovi()
    fajl = {
        "id": ctx.user_data["fajl_id"],
        "naziv": ctx.user_data["fajl_naziv"],
        "original_name": ctx.user_data["fajl_original"],
        "local_path": ctx.user_data["fajl_local"],
        "tg_file_id": ctx.user_data["fajl_tg_id"],
        "dokument": dokument["naziv"] if dokument else None,
        "datum_unosa": datetime.now().strftime("%d.%m.%Y %H:%M")
    }
    fajlovi.append(fajl)
    save_fajlovi(fajlovi)

    doc_info = f"\n📎 Vezano za: *{dokument['naziv']}*" if dokument else ""
    await update.message.reply_text(
        f"✅ *Fajl sačuvan!*\n\n"
        f"📄 {fajl['naziv']}\n"
        f"🗂 {fajl['original_name']}"
        f"{doc_info}\n\n"
        "Koristiti /fajlovi za pregled svih fajlova.",
        parse_mode="Markdown"
    )

async def sacuvaj_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Otkazano.")
    return ConversationHandler.END

async def lista_fajlova(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    fajlovi = load_fajlovi()
    if not fajlovi:
        await update.message.reply_text(
            "📭 Nema sačuvanih fajlova.\n\nKoristi /sacuvaj da dodaš fajl."
        )
        return

    msg = f"📁 *Sačuvani fajlovi ({len(fajlovi)}):*\n\n"
    for i, f in enumerate(fajlovi, 1):
        doc_info = f" _(📎 {f['dokument']})_" if f.get("dokument") else ""
        msg += f"{i}. *{f['naziv']}*\n🗂 {f['original_name']}{doc_info}\n📅 {f['datum_unosa']}\n\n"

    msg += "💡 Pošalji broj (npr. `2`) da dobiješ fajl nazad."
    ctx.user_data["fajlovi_lista"] = fajlovi
    await update.message.reply_text(msg, parse_mode="Markdown")

async def fajlovi_dokumenta(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args
    if not args:
        await update.message.reply_text(
            "Koristi: `/fajlovi_dokumenta Naziv dokumenta`",
            parse_mode="Markdown"
        )
        return

    naziv_trazeni = " ".join(args).strip().lower()
    fajlovi = load_fajlovi()
    filtrirani = [f for f in fajlovi if f.get("dokument", "").lower() == naziv_trazeni]

    if not filtrirani:
        await update.message.reply_text(
            f"📭 Nema fajlova vezanih za *{' '.join(args)}*.\n\n"
            "Provjeri naziv dokumenta sa /lista",
            parse_mode="Markdown"
        )
        return

    msg = f"📁 *Fajlovi za {' '.join(args)} ({len(filtrirani)}):*\n\n"
    for i, f in enumerate(filtrirani, 1):
        msg += f"{i}. *{f['naziv']}*\n🗂 {f['original_name']}\n📅 {f['datum_unosa']}\n\n"

    msg += "💡 Pošalji broj da dobiješ fajl."
    ctx.user_data["fajlovi_lista"] = filtrirani
    await update.message.reply_text(msg, parse_mode="Markdown")

async def brisanje_fajla(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    fajlovi = load_fajlovi()
    if not fajlovi:
        await update.message.reply_text("📭 Nema fajlova za brisanje.")
        return

    msg = "🗑 *Koji fajl obrisati?*\n\nPošalji broj:\n\n"
    for i, f in enumerate(fajlovi, 1):
        msg += f"{i}. {f['naziv']} — {f['original_name']}\n"

    ctx.user_data["fajlovi_za_brisanje"] = fajlovi
    await update.message.reply_text(msg, parse_mode="Markdown")

# ── AI ───────────────────────────────────────────────────────────────────────
AI_SYSTEM_PROMPT = """Ti si prijateljski asistent integriran u Telegram bota.
Primarno pomažeš korisniku da prati rokove važnosti dokumenata, ali možeš razgovarati o bilo čemu.

Imaš pristup internetu putem Google pretrage — koristi ga kad god trebaš aktualne informacije (vijesti, vremenska prognoza, kursevi, sportski rezultati, itd.).

Kada korisnik želi dodati dokument (npr. "dodaj registraciju auta do 15.3.2026" ili "vozačka ističe 01.06.2026"):
Vrati SAMO JSON u ovom formatu, bez ikakvog drugog teksta:
{"action": "dodaj_dokument", "naziv": "Naziv dokumenta", "datum": "DD.MM.YYYY"}

U svim ostalim slučajevima odgovaraj normalno na bosanskom/srpskom jeziku.
Budi koncizan, prijateljski i praktičan. Koristi emotikone umjereno."""

async def ai_chat(user_message: str, docs_context: str, history: list) -> str:
    if not GEMINI_API_KEY:
        return "❌ AI nije konfigurisan. Postavi GEMINI_API_KEY environment varijablu."

    system_with_context = f"{AI_SYSTEM_PROMPT}\n\nTrenutno stanje dokumenata:\n{docs_context}"

    contents = [
        {"role": "user", "parts": [{"text": system_with_context}]},
        {"role": "model", "parts": [{"text": "Razumijem, spreman sam pomoći."}]},
    ]
    for msg in history:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    contents.append({"role": "user", "parts": [{"text": user_message}]})

    payload = {
        "contents": contents,
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "maxOutputTokens": 1500,
            "temperature": 0.7,
        }
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"

    async with httpx.AsyncClient(timeout=45.0) as client:
        for attempt in range(3):
            response = await client.post(url, json=payload)
            if response.status_code == 429:
                wait = 10 * (attempt + 1)
                await asyncio.sleep(wait)
                continue
            response.raise_for_status()
            data = response.json()
            parts = data["candidates"][0]["content"]["parts"]
            text_parts = [p["text"] for p in parts if "text" in p]
            return "\n".join(text_parts) if text_parts else "⚠️ Nisam dobio odgovor."
        return "⚠️ Gemini je zauzet, pokušaj za koji trenutak."

# ── Jutarnji podsjetnik ──────────────────────────────────────────────────────
async def podsjetnik_job(ctx: ContextTypes.DEFAULT_TYPE):
    settings = load_settings()
    chat_id = settings.get("chat_id")
    if not chat_id:
        return
    msg = build_report()
    if msg:
        await ctx.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")

# ── Komande ──────────────────────────────────────────────────────────────────
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
        "🔔 *Podsjetnici i napomene:*\n"
        "/napomena — dodaj prilagođeni podsjetnik\n"
        "/napomene — lista aktivnih podsjetnika\n"
        "/brisanje\\_napomene — obriši podsjetnik\n"
        "/podsjetnik\\_on — uključi jutarnji podsjetnik (08:00)\n"
        "/podsjetnik\\_off — isključi jutarnji podsjetnik\n"
        f"Status jutarnjeg: {podsjetnici}\n\n"
        "📁 *Fajlovi:*\n"
        "/sacuvaj — sačuvaj fajl\n"
        "/fajlovi — lista sačuvanih fajlova\n"
        "/fajlovi\\_dokumenta — fajlovi vezani za dokument\n"
        "/brisanje\\_fajla — obriši fajl\n\n"
        "🤖 *AI Asistent:*\n"
        "/ai ili /pitaj — razgovaraj sa AI asistentom\n\n"
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
    if "ai_history" not in ctx.user_data:
        ctx.user_data["ai_history"] = []

    args = ctx.args
    if args:
        user_text = " ".join(args)
        await _process_ai_message(update, ctx, user_text)
    else:
        ctx.user_data["ai_mode"] = True
        await update.message.reply_text(
            "🤖 *AI Asistent aktivan!*\n\n"
            "Pitaj me bilo šta — o dokumentima, vijestima, vremenu, ili bilo čemu drugom.\n\n"
            "Primjeri:\n"
            "• _Koji dokumenti ističu uskoro?_\n"
            "• _Kakvo je vrijeme u Sarajevu?_\n"
            "• _Dodaj vozačku dozvolu do 15.3.2027_\n\n"
            "Za izlaz iz AI moda piši /kraj, /stop ili _Misko kraj_",
            parse_mode="Markdown"
        )

async def ai_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["ai_mode"] = False
    ctx.user_data["ai_history"] = []
    await update.message.reply_text(
        "👋 AI mod zatvoren. Historija razgovora obrisana.\n\nKoristi /ai za novi razgovor.",
        parse_mode="Markdown"
    )

async def _process_ai_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE, user_text: str):
    docs_context = build_docs_context()
    history = ctx.user_data.get("ai_history", [])

    thinking_msg = await update.message.reply_text("🤖 _Razmišljam..._", parse_mode="Markdown")

    try:
        response_text = await ai_chat(user_text, docs_context, history)

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
                    ctx.user_data["ai_history"] = history + [
                        {"role": "user", "content": user_text},
                        {"role": "assistant", "content": f"Dodao sam dokument: {naziv}, datum: {date_str}"}
                    ]
                    return
            except json.JSONDecodeError:
                pass

        await thinking_msg.edit_text(response_text, parse_mode="Markdown")

        new_history = history + [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": response_text}
        ]
        ctx.user_data["ai_history"] = new_history[-10:]

    except httpx.HTTPStatusError as e:
        await thinking_msg.edit_text(f"❌ API greška: {e.response.status_code}. Provjeri API ključ.")
    except Exception as e:
        await thinking_msg.edit_text(f"❌ Greška: {str(e)}")

async def goca_zanimljivost(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tekst = random.choice(GOCA_FRAZE)
    await update.message.reply_text(tekst)

# ── Glavni text handler ───────────────────────────────────────────────────────
async def brzi_unos(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    text = update.message.text.strip()
    text_lower = text.lower()

    # Goca trigger (uvijek aktivan)
    if text_lower == "goca":
        await goca_zanimljivost(update, ctx)
        return

    # Misko trigger — aktivira AI mod
    if text_lower.startswith("misko"):
        ostatak = text[5:].strip()
        # "Misko kraj/stop" — zatvori AI mod
        if ostatak.lower() in ["kraj", "stop", "izlaz"]:
            ctx.user_data["ai_mode"] = False
            ctx.user_data["ai_history"] = []
            await update.message.reply_text("👋 AI mod zatvoren.")
            return
        # Aktiviraj AI mod
        ctx.user_data["ai_mode"] = True
        ctx.user_data.setdefault("ai_history", [])
        if ostatak:
            # Odmah obradi pitanje: "Misko kakvo je vrijeme?"
            await _process_ai_message(update, ctx, ostatak)
        else:
            await update.message.reply_text(
                "🤖 *Misko aktivan!*\n\nPitaj me bilo šta. Za izlaz piši _Misko kraj_.",
                parse_mode="Markdown"
            )
        return

    # AI mod aktivan — sve poruke idu AI-u
    if ctx.user_data.get("ai_mode", False):
        if text_lower in ["/kraj", "/stop", "kraj", "stop", "izlaz"]:
            ctx.user_data["ai_mode"] = False
            ctx.user_data["ai_history"] = []
            await update.message.reply_text("👋 AI mod zatvoren.")
            return
        await _process_ai_message(update, ctx, text)
        return

    # Brisanje napomene po broju
    if "naps_za_brisanje" in ctx.user_data:
        try:
            br = int(text)
            lista_nap = ctx.user_data["naps_za_brisanje"]
            if 1 <= br <= len(lista_nap):
                nap = lista_nap[br - 1]
                naps = load_napomene()
                naps = [n for n in naps if n["id"] != nap["id"]]
                save_napomene(naps)
                # Otkaži job ako postoji
                jobs = ctx.job_queue.get_jobs_by_name(f"nap_{nap['id']}")
                for job in jobs:
                    job.schedule_removal()
                del ctx.user_data["naps_za_brisanje"]
                await update.message.reply_text(f"✅ Podsjetnik obrisan: *{nap['tekst']}*", parse_mode="Markdown")
                return
        except:
            del ctx.user_data["naps_za_brisanje"]

    # Slanje fajla po broju
    if "fajlovi_lista" in ctx.user_data:
        try:
            br = int(text)
            lista_f = ctx.user_data["fajlovi_lista"]
            if 1 <= br <= len(lista_f):
                fajl = lista_f[br - 1]
                # Pokušaj poslati preko Telegram file_id (brže)
                tg_id = fajl.get("tg_file_id")
                local = fajl.get("local_path")
                caption = f"📄 *{fajl['naziv']}*\n🗂 {fajl['original_name']}"
                if tg_id:
                    try:
                        await update.message.reply_document(document=tg_id, caption=caption, parse_mode="Markdown")
                        del ctx.user_data["fajlovi_lista"]
                        return
                    except:
                        pass
                # Fallback: lokalni fajl
                if local and os.path.exists(local):
                    with open(local, "rb") as fp:
                        await update.message.reply_document(
                            document=fp,
                            filename=fajl["original_name"],
                            caption=caption,
                            parse_mode="Markdown"
                        )
                    del ctx.user_data["fajlovi_lista"]
                    return
                else:
                    await update.message.reply_text("❌ Fajl nije pronađen na disku.")
                    del ctx.user_data["fajlovi_lista"]
                    return
        except ValueError:
            del ctx.user_data["fajlovi_lista"]

    # Brisanje fajla po broju
    if "fajlovi_za_brisanje" in ctx.user_data:
        try:
            br = int(text)
            lista_f = ctx.user_data["fajlovi_za_brisanje"]
            if 1 <= br <= len(lista_f):
                fajl = lista_f[br - 1]
                fajlovi = load_fajlovi()
                fajlovi = [f for f in fajlovi if f["id"] != fajl["id"]]
                save_fajlovi(fajlovi)
                # Obriši lokalni fajl
                local = fajl.get("local_path")
                if local and os.path.exists(local):
                    os.remove(local)
                del ctx.user_data["fajlovi_za_brisanje"]
                await update.message.reply_text(f"✅ Obrisan fajl: *{fajl['naziv']}*", parse_mode="Markdown")
                return
        except:
            del ctx.user_data["fajlovi_za_brisanje"]

    # Brisanje dokumenta po broju
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

    # Bot šuti ako AI mod nije aktivan i poruka nije prepoznata
    pass

# ── main ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TOKEN).build()

    # ConversationHandler za dodaj dokument
    conv_dodaj = ConversationHandler(
        entry_points=[CommandHandler("dodaj", dodaj_start)],
        states={
            NAZIV: [MessageHandler(filters.TEXT & ~filters.COMMAND, dodaj_naziv)],
            DATUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, dodaj_datum)],
        },
        fallbacks=[CommandHandler("cancel", dodaj_cancel)],
    )

    # ConversationHandler za napomenu
    conv_napomena = ConversationHandler(
        entry_points=[CommandHandler("napomena", napomena_start)],
        states={
            NAP_TEKST: [MessageHandler(filters.TEXT & ~filters.COMMAND, napomena_tekst)],
            NAP_DATUM: [MessageHandler(filters.TEXT & ~filters.COMMAND, napomena_datum)],
            NAP_VRIJEME: [MessageHandler(filters.TEXT & ~filters.COMMAND, napomena_vrijeme)],
            NAP_DOKUMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, napomena_dokument)],
        },
        fallbacks=[CommandHandler("cancel", napomena_cancel)],
    )

    # ConversationHandler za čuvanje fajla
    conv_sacuvaj = ConversationHandler(
        entry_points=[CommandHandler("sacuvaj", sacuvaj_start)],
        states={
            SACUVAJ_NAZIV: [MessageHandler(filters.TEXT & ~filters.COMMAND, sacuvaj_naziv)],
            SACUVAJ_FAJL: [MessageHandler(
                filters.Document.ALL | filters.PHOTO | filters.AUDIO | filters.VIDEO,
                sacuvaj_fajl
            )],
            SACUVAJ_DOKUMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, sacuvaj_dokument)],
        },
        fallbacks=[CommandHandler("cancel", sacuvaj_cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("uskoro", uskoro))
    app.add_handler(CommandHandler("isteklo", isteklo))
    app.add_handler(CommandHandler("brisanje", brisanje))
    app.add_handler(CommandHandler("izvjestaj", izvjestaj))
    app.add_handler(CommandHandler("podsjetnik_on", podsjetnik_on))
    app.add_handler(CommandHandler("podsjetnik_off", podsjetnik_off))
    app.add_handler(CommandHandler("napomene", lista_napomena))
    app.add_handler(CommandHandler("brisanje_napomene", brisanje_napomene))
    app.add_handler(CommandHandler("fajlovi", lista_fajlova))
    app.add_handler(CommandHandler("fajlovi_dokumenta", fajlovi_dokumenta))
    app.add_handler(CommandHandler("brisanje_fajla", brisanje_fajla))
    app.add_handler(CommandHandler(["ai", "pitaj"], ai_komanda))
    app.add_handler(CommandHandler(["kraj", "stop"], ai_stop))
    app.add_handler(conv_dodaj)
    app.add_handler(conv_napomena)
    app.add_handler(conv_sacuvaj)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, brzi_unos))

    # Obnovi jutarnji podsjetnik ako je bio uključen
    settings = load_settings()
    if settings.get("podsjetnici", False) and settings.get("chat_id"):
        app.job_queue.run_daily(
            podsjetnik_job,
            time=time(hour=8, minute=0, second=0),
            name="jutarnji"
        )
        print("Jutarnji podsjetnik aktivan — 08:00")

    # Obnovi napomene iz fajla (nakon restarta bota)
    naps = load_napomene()
    chat_id = settings.get("chat_id")
    if chat_id and naps:
        now = datetime.now()
        obnovljeno = 0
        for nap in naps:
            dt = datetime.strptime(nap["datetime"], "%d.%m.%Y %H:%M")
            if dt > now:
                schedule_napomena(app.job_queue, nap, chat_id)
                obnovljeno += 1
        if obnovljeno:
            print(f"Obnovljeno {obnovljeno} podsjetnika iz fajla.")

    ensure_files_dir()
    print("Bot pokrenut!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
