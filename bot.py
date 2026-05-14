async def brzi_unos(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    text_lower = text.lower()

    # Goca trigger (uvijek aktivan)
    if text_lower == "goca":
        await goca_zanimljivost(update, ctx)
        return

    # Brisanje napomene po broju (mora biti prije AI moda)
    if "naps_za_brisanje" in ctx.user_data:
        try:
            br = int(text)
            lista_nap = ctx.user_data["naps_za_brisanje"]
            if 1 <= br <= len(lista_nap):
                nap = lista_nap[br - 1]
                naps = load_napomene()
                naps = [n for n in naps if n["id"] != nap["id"]]
                save_napomene(naps)
                jobs = ctx.job_queue.get_jobs_by_name(f"nap_{nap['id']}")
                for job in jobs:
                    job.schedule_removal()
                del ctx.user_data["naps_za_brisanje"]
                await update.message.reply_text(f"✅ Podsjetnik obrisan: *{nap['tekst']}*", parse_mode="Markdown")
                return
        except:
            del ctx.user_data["naps_za_brisanje"]

    # Slanje fajla po broju (iz /fajlovi)
    if "fajlovi_lista" in ctx.user_data:
        try:
            br = int(text)
            lista_f = ctx.user_data["fajlovi_lista"]
            if 1 <= br <= len(lista_f):
                fajl = lista_f[br - 1]
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
                f"✅ <b>Sačuvano!</b>\n\n📄 {h(doc['naziv'])}\n📅 {h(date_str)}\nStatus: {label}",
                parse_mode="HTML"
            )
            return

    # Misko trigger — aktivira AI mod (ali tek nakon svih gore navedenih provjera)
    if text_lower.startswith("misko"):
        ostatak = text[5:].strip()
        if ostatak.lower() in ["kraj", "stop", "izlaz"]:
            ctx.user_data["ai_mode"] = False
            ctx.user_data["ai_history"] = []
            await update.message.reply_text("👋 AI mod zatvoren.")
            return
        ctx.user_data["ai_mode"] = True
        ctx.user_data.setdefault("ai_history", [])
        if ostatak:
            await _process_ai_message(update, ctx, ostatak)
        else:
            await update.message.reply_text(
                "🤖 *Misko aktivan!*\n\nPitaj me bilo šta. Za izlaz piši _Misko kraj_.",
                parse_mode="Markdown"
            )
        return

    # AI mod aktivan (samo ako nema čekajućih interakcija i nije riječ "misko" trigger)
    if ctx.user_data.get("ai_mode", False) and not ctx.user_data.get("in_conv", False):
        if text_lower in ["/kraj", "/stop", "kraj", "stop", "izlaz"]:
            ctx.user_data["ai_mode"] = False
            ctx.user_data["ai_history"] = []
            await update.message.reply_text("👋 AI mod zatvoren.")
            return
        await _process_ai_message(update, ctx, text)
        return

    # Ako ništa nije prepoznato, bot šuti
    pass
