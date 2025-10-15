import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from database import SessionLocal, init_db, User, Route, Package, DeliveryProof


# Configurações e diretórios
load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "uploads"
IMPORTS_DIR = UPLOADS_DIR / "imports"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
IMPORTS_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8001")
BOT_USERNAME = os.getenv("BOT_USERNAME", "SEU_BOT_USERNAME")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")


# Estados de conversa
IMPORT_WAITING_FILE = 10
PHOTO1, PHOTO2, NAME, DOC, NOTES = range(5)
ADD_DRIVER_TID, ADD_DRIVER_NAME = range(10, 12)
SEND_SELECT_ROUTE, SEND_SELECT_DRIVER = range(20, 22)


# Utilidades
def _find_column(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    cols = {c.lower(): c for c in df.columns}
    for name in candidates:
        if name.lower() in cols:
            return cols[name.lower()]
    return None


def parse_import_dataframe(df: pd.DataFrame) -> list[dict]:
    col_tracking = _find_column(
        df,
        [
            "spx tn",
            "tracking",
            "codigo",
            "tracking_code",
            "rastreamento",
            "codigo de rastreio",
            "código",
            "tracking id",
        ],
    ) or df.columns[0]
    col_address = _find_column(df, ["destination address", "address", "endereco", "endereço", "destino"]) or df.columns[1]
    col_lat = _find_column(df, ["latitude", "lat"])  # opcional
    col_lng = _find_column(df, ["longitude", "lng", "long"])  # opcional
    col_bairro = _find_column(df, ["bairro", "neighborhood"])  # opcional

    items: list[dict] = []
    for _, row in df.iterrows():
        tracking_code = str(row.get(col_tracking, "")).strip()
        if not tracking_code:
            continue
        address = str(row.get(col_address, "")).strip() or None
        neighborhood = None
        if col_bairro:
            neighborhood = str(row.get(col_bairro, "")).strip() or None
        lat = None
        lng = None
        if col_lat and pd.notna(row.get(col_lat)):
            try:
                lat = float(row[col_lat])
            except Exception:
                lat = None
        if col_lng and pd.notna(row.get(col_lng)):
            try:
                lng = float(row[col_lng])
            except Exception:
                lng = None

        items.append(
            {
                "tracking_code": tracking_code,
                "address": address,
                "neighborhood": neighborhood,
                "latitude": lat,
                "longitude": lng,
                "raw_data": row.to_dict(),
            }
        )
    return items


def get_user_by_tid(db, tid: int) -> Optional[User]:
    return db.query(User).filter(User.telegram_user_id == tid).first()


def register_manager_if_first(telegram_user_id: int, full_name: Optional[str]) -> User:
    db = SessionLocal()
    try:
        existing_manager = db.query(User).filter(User.role == "manager").first()
        user = get_user_by_tid(db, telegram_user_id)
        if not user:
            role = "manager" if not existing_manager else "driver"
            user = User(telegram_user_id=telegram_user_id, full_name=full_name, role=role)
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            if full_name and user.full_name != full_name:
                user.full_name = full_name
                db.commit()
        return user
    finally:
        db.close()


async def notify_managers(text: str, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        managers = db.query(User).filter(User.role == "manager").all()
    finally:
        db.close()
    for m in managers:
        try:
            await context.bot.send_message(chat_id=m.telegram_user_id, text=text)
        except Exception:
            pass


# Comandos
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_db()
    u = update.effective_user
    user = register_manager_if_first(u.id, u.full_name)

    args = context.args or []
    if args and len(args) == 1 and args[0].startswith("deliver_"):
        package_id_str = args[0].split("deliver_", 1)[1]
        try:
            package_id = int(package_id_str)
        except ValueError:
            package_id = None
        if package_id:
            context.user_data["deliver_package_id"] = package_id
            await update.message.reply_text("Vamos registrar a entrega. Envie a Foto 1 do recebedor/pacote (obrigatório).")
            return PHOTO1

    role_text = "manager" if user.role == "manager" else "driver"
    await update.message.reply_text(
        f"Olá {u.first_name}! Você está registrado como {role_text}. Use /importar (manager), /enviarrota, /cadastrardriver, /drivers ou /meu_id."
    )
    return ConversationHandler.END


async def cmd_meu_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Seu Telegram User ID é: {update.effective_user.id}")


async def cmd_importar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            await update.message.reply_text("Apenas managers podem importar rotas.")
            return ConversationHandler.END
    finally:
        db.close()
    await update.message.reply_text("Envie o arquivo .xlsx ou .csv desta conversa.")
    return IMPORT_WAITING_FILE


async def handle_import_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc:
        await update.message.reply_text("Por favor, envie um arquivo .xlsx ou .csv.")
        return IMPORT_WAITING_FILE

    filename = doc.file_name or f"import_{update.message.message_id}"
    suffix = Path(filename).suffix.lower()
    if suffix not in [".xlsx", ".csv"]:
        await update.message.reply_text("Formato inválido. Envie um .xlsx ou .csv.")
        return IMPORT_WAITING_FILE

    await update.message.chat.send_action(action=ChatAction.UPLOAD_DOCUMENT)
    file = await doc.get_file()
    local_path = IMPORTS_DIR / filename
    await file.download_to_drive(local_path)

    df = pd.read_excel(local_path) if suffix == ".xlsx" else pd.read_csv(local_path)
    items = parse_import_dataframe(df)
    if not items:
        await update.message.reply_text("Não encontrei linhas válidas no arquivo.")
        return ConversationHandler.END

    db = SessionLocal()
    try:
        route = Route(name=f"Rota {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        db.add(route)
        db.flush()
        for it in items:
            db.add(
                Package(
                    route_id=route.id,
                    tracking_code=it["tracking_code"],
                    address=it.get("address"),
                    neighborhood=it.get("neighborhood"),
                    latitude=it.get("latitude"),
                    longitude=it.get("longitude"),
                    status="pending",
                    raw_data=it.get("raw_data"),
                )
            )
        db.commit()
        await update.message.reply_text(f"Rota importada com sucesso! ID da Rota: {route.id}. Pacotes: {len(items)}")
    finally:
        db.close()
    return ConversationHandler.END


async def cmd_enviarrota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            await update.message.reply_text("Apenas managers podem enviar rota.")
            return
        args = context.args or []
        if len(args) == 2:
            try:
                route_id = int(args[0])
                driver_tid = int(args[1])
            except ValueError:
                await update.message.reply_text("IDs inválidos.")
                return
            route = db.get(Route, route_id)
            if not route:
                await update.message.reply_text("Rota não encontrada.")
                return
            driver = get_user_by_tid(db, driver_tid)
            if not driver:
                driver = User(telegram_user_id=driver_tid, full_name=None, role="driver")
                db.add(driver)
                db.flush()
            route.assigned_to_id = driver.id
            db.commit()
            count = db.query(Package).filter(Package.route_id == route.id).count()
            link = f"{BASE_URL}/map/{route.id}/{driver_tid}"
            try:
                await context.bot.send_message(chat_id=driver_tid, text=f"Você recebeu uma nova rota! {count} pacotes. Abra o mapa para começar: {link}")
                await update.message.reply_text("Rota enviada ao entregador.")
            except Exception:
                await update.message.reply_text("Não consegui enviar ao entregador. Ele já iniciou o bot com /start?")
            return
    finally:
        db.close()

    # Interativo: listar rotas
    db = SessionLocal()
    try:
        routes = db.query(Route).order_by(Route.created_at.desc()).all()
    finally:
        db.close()
    if not routes:
        await update.message.reply_text("Nenhuma rota importada ainda. Use /importar primeiro.")
        return
    keyboard = [[InlineKeyboardButton(text=f"{r.name or 'Rota'} (ID {r.id})", callback_data=f"sel_route:{r.id}")]
                for r in routes[:25]]
    await update.message.reply_text("Qual rota você deseja enviar?", reply_markup=InlineKeyboardMarkup(keyboard))
    return SEND_SELECT_ROUTE


async def on_select_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if not data.startswith("sel_route:"):
        return
    route_id = int(data.split(":", 1)[1])
    context.user_data["send_route_id"] = route_id

    db = SessionLocal()
    try:
        drivers = db.query(User).filter(User.role == "driver").order_by(User.id.desc()).all()
    finally:
        db.close()
    if not drivers:
        await query.edit_message_text("Nenhum entregador cadastrado ainda. Use /cadastrardriver para cadastrar.")
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(text=f"{(d.full_name or 'Sem nome')} (ID {d.telegram_user_id})",
                                       callback_data=f"sel_driver:{d.telegram_user_id}")]
                for d in drivers[:25]]
    await query.edit_message_text("Para qual entregador deseja enviar?", reply_markup=InlineKeyboardMarkup(keyboard))
    return SEND_SELECT_DRIVER


async def on_select_driver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if not data.startswith("sel_driver:"):
        return
    driver_tid = int(data.split(":", 1)[1])
    route_id = context.user_data.get("send_route_id")
    if not route_id:
        await query.edit_message_text("Rota não selecionada.")
        return ConversationHandler.END

    db = SessionLocal()
    try:
        route = db.get(Route, int(route_id))
        if not route:
            await query.edit_message_text("Rota não encontrada.")
            return ConversationHandler.END
        driver = get_user_by_tid(db, driver_tid)
        if not driver:
            driver = User(telegram_user_id=driver_tid, full_name=None, role="driver")
            db.add(driver)
            db.flush()
        route.assigned_to_id = driver.id
        db.commit()
        count = db.query(Package).filter(Package.route_id == route.id).count()
        link = f"{BASE_URL}/map/{route.id}/{driver_tid}"
        try:
            await context.bot.send_message(chat_id=driver_tid, text=f"Você recebeu uma nova rota! {count} pacotes. Abra o mapa para começar: {link}")
            await query.edit_message_text("Rota enviada ao entregador.")
        except Exception:
            await query.edit_message_text("Não consegui enviar ao entregador. Ele já iniciou o bot com /start?")
    finally:
        db.close()
    context.user_data.pop("send_route_id", None)
    return ConversationHandler.END


# Cadastro/listagem de entregadores
async def add_driver_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            await update.message.reply_text("Apenas managers podem cadastrar entregadores.")
            return ConversationHandler.END
    finally:
        db.close()
    await update.message.reply_text("Informe o Telegram User ID do entregador (número).")
    return ADD_DRIVER_TID


async def add_driver_tid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    try:
        tid = int(txt)
    except ValueError:
        await update.message.reply_text("ID inválido. Digite apenas números.")
        return ADD_DRIVER_TID
    context.user_data["new_driver_tid"] = tid
    await update.message.reply_text("Informe o nome completo do entregador.")
    return ADD_DRIVER_NAME


async def add_driver_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("Nome inválido. Tente novamente.")
        return ADD_DRIVER_NAME
    tid = context.user_data.get("new_driver_tid")
    db = SessionLocal()
    try:
        user = get_user_by_tid(db, tid)
        if user:
            user.full_name = name
            user.role = "driver"
        else:
            db.add(User(telegram_user_id=tid, full_name=name, role="driver"))
        db.commit()
    finally:
        db.close()
    context.user_data.pop("new_driver_tid", None)
    await update.message.reply_text("Entregador cadastrado/atualizado com sucesso.")
    return ConversationHandler.END


async def list_drivers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            await update.message.reply_text("Apenas managers podem listar entregadores.")
            return
        drivers = db.query(User).filter(User.role == "driver").order_by(User.id.desc()).all()
    finally:
        db.close()
    if not drivers:
        await update.message.reply_text("Nenhum entregador cadastrado.")
        return
    lines = [f"- {d.full_name or 'Sem nome'} (Telegram ID: {d.telegram_user_id})" for d in drivers]
    await update.message.reply_text("Entregadores:\n" + "\n".join(lines))


# Fluxo de entrega
async def deliver_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if len(args) != 1:
        await update.message.reply_text("Uso: /entregar <package_id>")
        return ConversationHandler.END
    try:
        package_id = int(args[0])
    except ValueError:
        await update.message.reply_text("package_id inválido.")
        return ConversationHandler.END
    context.user_data["deliver_package_id"] = package_id
    await update.message.reply_text("Envie a Foto 1 do recebedor/pacote (obrigatório).")
    return PHOTO1


async def photo1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Envie uma foto válida para Foto 1.")
        return PHOTO1
    # Não baixa arquivo. Guarda apenas o file_id do Telegram
    photo = update.message.photo[-1]
    context.user_data["photo1_file_id"] = photo.file_id
    await update.message.reply_text("Agora envie a Foto 2 do local/porta (obrigatório).")
    return PHOTO2


async def photo2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("Envie uma foto válida para Foto 2.")
        return PHOTO2
    # Não baixa arquivo. Guarda apenas o file_id do Telegram
    photo = update.message.photo[-1]
    context.user_data["photo2_file_id"] = photo.file_id
    await update.message.reply_text("Nome de quem recebeu?")
    return NAME


async def recv_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text("Informe um nome válido.")
        return NAME
    context.user_data["receiver_name"] = text
    await update.message.reply_text("RG de quem recebeu? (Se não tiver, digite 'não informou')")
    return DOC


async def recv_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    context.user_data["receiver_document"] = text or "não informou"
    kb = ReplyKeyboardMarkup([["Pular"]], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("Alguma observação? (Opcional)", reply_markup=kb)
    return NOTES


async def recv_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text.lower() == "pular":
        text = None
    context.user_data["notes"] = text
    return await finalize_delivery(update, context)


async def finalize_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pkg_id = context.user_data.get("deliver_package_id")
    if not pkg_id:
        await update.message.reply_text("Não foi possível identificar o pacote.")
        return ConversationHandler.END

    db = SessionLocal()
    try:
        package = db.get(Package, int(pkg_id))
        if not package:
            await update.message.reply_text("Pacote não encontrado.")
            return ConversationHandler.END

        driver = get_user_by_tid(db, update.effective_user.id)
        proof = DeliveryProof(
            package_id=package.id,
            driver_id=driver.id if driver else None,
            receiver_name=context.user_data.get("receiver_name"),
            receiver_document=context.user_data.get("receiver_document"),
            notes=context.user_data.get("notes"),
            # Armazena o file_id do Telegram nos campos existentes
            photo1_path=context.user_data.get("photo1_file_id"),
            photo2_path=context.user_data.get("photo2_file_id"),
        )
        db.add(proof)
        package.status = "delivered"
        db.commit()

    finally:
        db.close()

    # Notificar managers com resumo básico
    try:
        db2 = SessionLocal()
        package = db2.get(Package, int(pkg_id)) if db2 else None
    finally:
        db2.close()
    if package:
        summary = (
            f"Entrega concluída\n"
            f"Pacote: {package.tracking_code}\n"
            f"Endereço: {package.address or '-'}\n"
            f"Notas: {context.user_data.get('notes') or '-'}"
        )
        await notify_managers(summary, context)
        # Envia as fotos aos managers para consulta/baixa no próprio Telegram
        p1 = context.user_data.get("photo1_file_id")
        p2 = context.user_data.get("photo2_file_id")
        if p1 or p2:
            dbm = SessionLocal()
            try:
                managers = dbm.query(User).filter(User.role == "manager").all()
            finally:
                dbm.close()
            for m in managers:
                if p1:
                    try:
                        await context.bot.send_photo(chat_id=m.telegram_user_id, photo=p1)
                    except Exception:
                        pass
                if p2:
                    try:
                        await context.bot.send_photo(chat_id=m.telegram_user_id, photo=p2)
                    except Exception:
                        pass

    await update.message.reply_text("Entrega registrado com sucesso!", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Operação cancelada.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def build_application():
    if not BOT_TOKEN:
        raise RuntimeError("Defina a variável de ambiente BOT_TOKEN")
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("meu_id", cmd_meu_id))

    import_conv = ConversationHandler(
        entry_points=[CommandHandler("importar", cmd_importar)],
        states={
            IMPORT_WAITING_FILE: [MessageHandler(filters.Document.ALL, handle_import_file)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="import_conv",
        persistent=False,
    )
    app.add_handler(import_conv)

    app.add_handler(CommandHandler("enviarrota", cmd_enviarrota))
    app.add_handler(CallbackQueryHandler(on_select_route, pattern=r"^sel_route:\d+$"))
    app.add_handler(CallbackQueryHandler(on_select_driver, pattern=r"^sel_driver:\d+$"))

    delivery_conv = ConversationHandler(
        entry_points=[CommandHandler("entregar", deliver_start)],
        states={
            PHOTO1: [MessageHandler(filters.PHOTO, photo1)],
            PHOTO2: [MessageHandler(filters.PHOTO, photo2)],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_name)],
            DOC: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_doc)],
            NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_notes)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="delivery_conv",
        persistent=False,
    )
    app.add_handler(delivery_conv)

    add_driver_conv = ConversationHandler(
        entry_points=[CommandHandler("cadastrardriver", add_driver_start)],
        states={
            ADD_DRIVER_TID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_driver_tid)],
            ADD_DRIVER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_driver_name)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="add_driver_conv",
        persistent=False,
    )
    app.add_handler(add_driver_conv)
    app.add_handler(CommandHandler("drivers", list_drivers))

    return app


def main():
    app = build_application()
    print("Bot iniciado. Pressione Ctrl+C para sair.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
