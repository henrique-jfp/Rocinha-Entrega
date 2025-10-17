import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from math import radians, sin, cos, sqrt, asin

import pandas as pd
import google.generativeai as genai
from dotenv import load_dotenv
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.error import TelegramError

from database import (
    SessionLocal, init_db, User, Route, Package, DeliveryProof,
    Expense, Income, Mileage, AIReport, LinkToken
)


# Configurações e diretórios
load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "uploads"
IMPORTS_DIR = UPLOADS_DIR / "imports"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
IMPORTS_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8001")
BOT_USERNAME = os.getenv("BOT_USERNAME", "SEU_BOT_USERNAME")

# Coordenadas do ponto de início (sua loja/centro de distribuição)
# IMPORTANTE: Altere para as coordenadas reais da sua localização!
DEPOT_LAT = float(os.getenv("DEPOT_LAT", "-22.988000"))  # Exemplo: Rocinha, RJ
DEPOT_LON = float(os.getenv("DEPOT_LON", "-43.248000"))

# Configurar Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY and GEMINI_API_KEY != "your_api_key_here":
    genai.configure(api_key=GEMINI_API_KEY)
    # Usar gemini-1.5-pro (modelo estável da API v1beta)
    gemini_model = genai.GenerativeModel('gemini-1.5-pro')
else:
    gemini_model = None
BOT_TOKEN = os.getenv("BOT_TOKEN", "")


# Estados de conversa
IMPORT_ASK_NAME = 9
IMPORT_WAITING_FILE = 10
PHOTO1, PHOTO2, NAME, DOC, NOTES = range(5)
# Novo fluxo: seleção de modo e fotos em massa
MODE_SELECT, MASS_PHOTOS = range(50, 52)
ADD_DRIVER_TID, ADD_DRIVER_NAME = range(10, 12)
SEND_SELECT_ROUTE, SEND_SELECT_DRIVER = range(20, 22)
CONFIG_CHANNEL_SELECT_DRIVER, CONFIG_CHANNEL_ENTER_ID = range(23, 25)
CONFIG_HOME_SELECT_DRIVER, CONFIG_HOME_LOCATION = range(26, 28)  # Estados para configurar casa

# Estados financeiros (APENAS MANAGERS)
FIN_KM, FIN_FUEL_YN, FIN_FUEL_TYPE, FIN_FUEL_LITERS, FIN_FUEL_AMOUNT = range(30, 35)
FIN_INCOME, FIN_SALARY_YN, FIN_SALARY_NAME, FIN_SALARY_AMOUNT, FIN_SALARY_MORE = range(35, 40)
FIN_EXPENSES, FIN_NOTES = range(40, 42)


# ==================== OTIMIZAÇÃO DE ROTA (TSP) ====================

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula distância Haversine entre dois pontos (em km)."""
    R = 6371  # Raio da Terra em km
    
    # Converter para radianos
    lat1_rad = radians(lat1)
    lon1_rad = radians(lon1)
    lat2_rad = radians(lat2)
    lon2_rad = radians(lon2)
    
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = sin(dlat/2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    
    return R * c


def optimize_route_packages(db, packages: List[Package], start_lat: float, start_lon: float) -> int:
    """
    Calcula a ordem otimizada dos pacotes usando heurística Nearest Neighbor.
    Usa distância Haversine como métrica (melhor para caminhada/carro).
    Algoritmo rápido O(n²) adequado para rotas com muitos pacotes.
    
    Args:
        db: Sessão do banco de dados
        packages: Lista de pacotes da rota
        start_lat: Latitude do ponto de início (depot ou casa do motorista)
        start_lon: Longitude do ponto de início (depot ou casa do motorista)
    
    Returns:
        Número de pacotes otimizados
    """
    # 1. Filtrar pacotes que têm coordenadas
    packages_to_optimize = [
        p for p in packages 
        if p.latitude is not None and p.longitude is not None
    ]

    if len(packages_to_optimize) < 2:
        # Se tem 0 ou 1 pacote com coordenadas, não há o que otimizar
        order = 1
        for pkg in packages:
            pkg.order_in_route = order
            db.add(pkg)
            order += 1
        db.commit()
        return 0

    # 2. HEURÍSTICA NEAREST NEIGHBOR (vizinho mais próximo)
    # Muito mais rápido que TSP exato, adequado para 40+ pacotes
    
    unvisited = packages_to_optimize.copy()
    current_lat, current_lon = start_lat, start_lon
    optimized_order = []
    
    while unvisited:
        # Encontrar pacote mais próximo da posição atual
        nearest = min(
            unvisited,
            key=lambda p: haversine_distance(current_lat, current_lon, p.latitude, p.longitude)
        )
        optimized_order.append(nearest)
        unvisited.remove(nearest)
        current_lat, current_lon = nearest.latitude, nearest.longitude

    # 3. Atualizar ordem no banco de dados
    order = 1
    for pkg in optimized_order:
        pkg.order_in_route = order
        db.add(pkg)
        order += 1
    
    # 4. Pacotes sem coordenadas vão para o final
    for pkg in packages:
        if pkg.order_in_route is None:
            pkg.order_in_route = order
            db.add(pkg)
            order += 1

    db.commit()
    
    # Calcular distância total para log
    total_distance = 0.0
    current_lat, current_lon = start_lat, start_lon
    for pkg in optimized_order:
        total_distance += haversine_distance(current_lat, current_lon, pkg.latitude, pkg.longitude)
        current_lat, current_lon = pkg.latitude, pkg.longitude
    
    print(f"✅ Rota otimizada: {len(packages_to_optimize)} pacotes, distância: {total_distance:.2f} km")
    return len(packages_to_optimize)


# ==================== UTILIDADES ====================

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
    """Comando /start - Cadastro inicial e boas-vindas OU inicia entrega via deep link"""
    init_db()
    u = update.effective_user
    user = register_manager_if_first(u.id, u.full_name)

    # Verifica se veio do mapa (deep link de entrega)
    # IMPORTANTE: O Telegram sempre usa /start para deep links, não /entrega
    # O formato é: t.me/bot?start=PARAMETRO → bot recebe /start PARAMETRO
    args = context.args or []
    print(f"DEBUG /start: context.args = {args}")
    if not args and update.message and update.message.text:
        # Fallback: extrai parâmetro da mensagem de texto "/start <param>"
        parts = update.message.text.strip().split(maxsplit=1)
        print(f"DEBUG /start: update.message.text = '{update.message.text}'")
        print(f"DEBUG /start: parts = {parts}")
        if len(parts) == 2:
            args = [parts[1]]
            print(f"DEBUG /start: args from message = {args}")
    
    if args and len(args) >= 1:
        arg = args[0]
        print(f"DEBUG /start: processing arg = '{arg}'")
        
        # Remove prefixo "entrega_" se presente (vem do deep link)
        if arg.startswith("entrega_"):
            arg = arg[8:]  # Remove "entrega_" prefix
            print(f"DEBUG /start: removed entrega_ prefix, now arg = '{arg}'")
        
        # Formato token curto: deliverg_<token>
        if arg.startswith("deliverg_"):
            token = arg.split("deliverg_", 1)[1]
            print(f"DEBUG /start: deliverg_ token = '{token}'")
            db = SessionLocal()
            try:
                rec = db.query(LinkToken).filter(LinkToken.token == token, LinkToken.type == "deliver_group").first()
                print(f"DEBUG /start: LinkToken found = {rec is not None}")
                if rec:
                    print(f"DEBUG /start: rec.data = {rec.data}")
                    print(f"DEBUG /start: rec.type = {rec.type}")
                if rec and isinstance(rec.data, dict) and rec.data.get("ids"):
                    context.user_data["deliver_package_ids"] = list(map(int, rec.data["ids"]))
                    print(f"DEBUG /start: deliver_package_ids set to {context.user_data['deliver_package_ids']}")
                    keyboard = ReplyKeyboardMarkup([["Unitário", "Em massa"]], resize_keyboard=True, one_time_keyboard=True)
                    await update.message.reply_text(
                        "📦 *Entrega Múltipla*\n\n"
                        f"🎯 {len(context.user_data['deliver_package_ids'])} pacotes selecionados\n\n"
                        "Como será esta entrega?",
                        reply_markup=keyboard,
                        parse_mode='Markdown'
                    )
                    return MODE_SELECT
                else:
                    print("DEBUG /start: Token not found or invalid data")
                    await update.message.reply_text(
                        "❌ *Token Inválido*\n\n"
                        "Este link de entrega expirou ou é inválido.\n\n"
                        "Use o mapa interativo para gerar um novo link.",
                        parse_mode='Markdown'
                    )
                    return ConversationHandler.END
            finally:
                db.close()
        
        # Formato legado: deliver_group_<id1>_<id2>_...
        elif arg.startswith("deliver_group_"):
            try:
                ids_str = arg.split("deliver_group_", 1)[1]
                ids = [int(x) for x in ids_str.split("_") if x.isdigit()]
                if ids:
                    context.user_data["deliver_package_ids"] = ids
                    keyboard = ReplyKeyboardMarkup([["Unitário", "Em massa"]], resize_keyboard=True, one_time_keyboard=True)
                    await update.message.reply_text(
                        "📦 *Entrega Múltipla*\n\n"
                        f"🎯 {len(ids)} pacotes selecionados\n\n"
                        "Como será esta entrega?",
                        reply_markup=keyboard,
                        parse_mode='Markdown'
                    )
                    return MODE_SELECT
            except Exception:
                pass
        
        # Formato único: deliver_<id>
        elif arg.startswith("deliver_"):
            try:
                package_id_str = arg.split("deliver_", 1)[1]
                package_id = int(package_id_str)
                context.user_data["deliver_package_id"] = package_id
                
                keyboard = ReplyKeyboardMarkup([["Unitário", "Em massa"]], resize_keyboard=True, one_time_keyboard=True)
                await update.message.reply_text(
                    "📦 *Iniciar Entrega*\n\n"
                    "Como será esta entrega?",
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )
                return MODE_SELECT
            except (ValueError, IndexError):
                pass

    # Mensagem de boas-vindas personalizada (sem deep link)
    print("DEBUG /start: No delivery params, showing welcome message")
    if user.role == "manager":
        await update.message.reply_text(
            f"👋 Olá, *{u.first_name}*!\n\n"
            f"Bem-vindo ao sistema de entregas! Você está conectado como *Gerente*.\n\n"
            f"Use /help para ver todos os comandos disponíveis.",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f"👋 Olá, *{u.first_name}*!\n\n"
            f"Bem-vindo ao sistema de entregas! Você está conectado como *Motorista*.\n\n"
            f"Aguarde o gerente enviar uma rota para você. Use /help se precisar de ajuda.",
            parse_mode='Markdown'
        )
    return ConversationHandler.END
async def cmd_iniciar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /iniciar - Inicia entrega via deep link do mapa"""
    args = context.args or []
    if not args and update.message and update.message.text:
        # Fallback: extrai parâmetro da mensagem de texto "/iniciar <param>"
        parts = update.message.text.strip().split(maxsplit=1)
        if len(parts) == 2:
            args = [parts[1]]
    
    if args and len(args) == 1:
        # Aceita tanto "iniciar_deliver_X" quanto "deliver_X"
        arg = args[0]
        if arg.startswith("deliverg_"):
            token = arg.split("deliverg_", 1)[1]
            db = SessionLocal()
            try:
                rec = db.query(LinkToken).filter(LinkToken.token == token, LinkToken.type == "deliver_group").first()
                if rec and isinstance(rec.data, dict) and rec.data.get("ids"):
                    context.user_data["deliver_package_ids"] = list(map(int, rec.data["ids"]))
                    keyboard = ReplyKeyboardMarkup([["Unitário", "Em massa"]], resize_keyboard=True, one_time_keyboard=True)
                    await update.message.reply_text(
                        "📦 Como será esta entrega?",
                        reply_markup=keyboard
                    )
                    return MODE_SELECT
            finally:
                db.close()
        if arg.startswith("deliver_group_"):
            try:
                ids_str = arg.split("deliver_group_", 1)[1]
                ids = [int(x) for x in ids_str.split("_") if x.isdigit()]
                if ids:
                    context.user_data["deliver_package_ids"] = ids
                    keyboard = ReplyKeyboardMarkup([["Unitário", "Em massa"]], resize_keyboard=True, one_time_keyboard=True)
                    await update.message.reply_text(
                        "📦 Como será esta entrega?",
                        reply_markup=keyboard
                    )
                    return MODE_SELECT
            except Exception:
                pass
        if arg.startswith("iniciar_deliver_"):
            package_id_str = arg.split("iniciar_deliver_", 1)[1]
        elif arg.startswith("deliver_"):
            package_id_str = arg.split("deliver_", 1)[1]
        else:
            package_id_str = None
            
        if package_id_str:
            try:
                package_id = int(package_id_str)
                context.user_data["deliver_package_id"] = package_id
                keyboard = ReplyKeyboardMarkup([["Unitário", "Em massa"]], resize_keyboard=True, one_time_keyboard=True)
                await update.message.reply_text(
                    "📦 Como será esta entrega?",
                    reply_markup=keyboard
                )
                return MODE_SELECT
            except ValueError:
                pass
    
    # Se chamou /iniciar sem parâmetros ou com parâmetro inválido
    await update.message.reply_text(
        "⚠️ Comando inválido.\n\n"
        "Use o botão 'Entregar' no mapa interativo para iniciar uma entrega.",
        parse_mode='Markdown'
    )
    return ConversationHandler.END


async def cmd_entrega(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /entrega - Inicia fluxo de entrega (grupos ou único pacote)"""
    args = context.args or []
    print(f"DEBUG /entrega: context.args = {args}")
    
    if not args and update.message and update.message.text:
        # Fallback: extrai parâmetro da mensagem de texto "/entrega <param>"
        parts = update.message.text.strip().split(maxsplit=1)
        print(f"DEBUG /entrega: update.message.text = '{update.message.text}'")
        print(f"DEBUG /entrega: parts = {parts}")
        if len(parts) == 2:
            args = [parts[1]]
            print(f"DEBUG /entrega: args from message = {args}")
    
    if args and len(args) >= 1:
        arg = args[0]
        print(f"DEBUG /entrega: processing arg = '{arg}'")
        
        # Formato especial do deep link: entrega_deliverg_<token> ou entrega_deliver_<id>
        # O Telegram adiciona "entrega_" como prefixo quando usa /start com parâmetro
        if arg.startswith("entrega_"):
            arg = arg[8:]  # Remove "entrega_" prefix
            print(f"DEBUG /entrega: removed prefix, now arg = '{arg}'")
        
        # Formato token curto: deliverg_<token>
        if arg.startswith("deliverg_"):
            token = arg.split("deliverg_", 1)[1]
            print(f"DEBUG /entrega: deliverg_ token = '{token}'")
            db = SessionLocal()
            try:
                rec = db.query(LinkToken).filter(LinkToken.token == token, LinkToken.type == "deliver_group").first()
                print(f"DEBUG /entrega: LinkToken found = {rec is not None}")
                if rec:
                    print(f"DEBUG /entrega: rec.data = {rec.data}")
                    print(f"DEBUG /entrega: rec.type = {rec.type}")
                if rec and isinstance(rec.data, dict) and rec.data.get("ids"):
                    context.user_data["deliver_package_ids"] = list(map(int, rec.data["ids"]))
                    print(f"DEBUG /entrega: deliver_package_ids set to {context.user_data['deliver_package_ids']}")
                    keyboard = ReplyKeyboardMarkup([["Unitário", "Em massa"]], resize_keyboard=True, one_time_keyboard=True)
                    await update.message.reply_text(
                        "📦 *Entrega Múltipla*\n\n"
                        f"🎯 {len(context.user_data['deliver_package_ids'])} pacotes selecionados\n\n"
                        "Como será esta entrega?",
                        reply_markup=keyboard,
                        parse_mode='Markdown'
                    )
                    return MODE_SELECT
                else:
                    print("DEBUG /entrega: Token not found or invalid data")
                    await update.message.reply_text(
                        "❌ *Token Inválido*\n\n"
                        "Este link de entrega expirou ou é inválido.\n\n"
                        "Use o mapa interativo para gerar um novo link.",
                        parse_mode='Markdown'
                    )
                    return ConversationHandler.END
            finally:
                db.close()
        
        # Formato legado: deliver_group_<id1>_<id2>_...
        elif arg.startswith("deliver_group_"):
            try:
                ids_str = arg.split("deliver_group_", 1)[1]
                ids = [int(x) for x in ids_str.split("_") if x.isdigit()]
                if ids:
                    context.user_data["deliver_package_ids"] = ids
                    keyboard = ReplyKeyboardMarkup([["Unitário", "Em massa"]], resize_keyboard=True, one_time_keyboard=True)
                    await update.message.reply_text(
                        "📦 *Entrega Múltipla*\n\n"
                        f"🎯 {len(ids)} pacotes selecionados\n\n"
                        "Como será esta entrega?",
                        reply_markup=keyboard,
                        parse_mode='Markdown'
                    )
                    return MODE_SELECT
            except Exception as e:
                print(f"DEBUG /entrega: Error processing deliver_group_: {e}")
                pass
        
        # Formato único: deliver_<id>
        elif arg.startswith("deliver_"):
            try:
                package_id_str = arg.split("deliver_", 1)[1]
                package_id = int(package_id_str)
                context.user_data["deliver_package_id"] = package_id
                keyboard = ReplyKeyboardMarkup([["Unitário", "Em massa"]], resize_keyboard=True, one_time_keyboard=True)
                await update.message.reply_text(
                    "📦 *Iniciar Entrega*\n\n"
                    "Como será esta entrega?",
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )
                return MODE_SELECT
            except (ValueError, IndexError) as e:
                print(f"DEBUG /entrega: Error processing deliver_: {e}")
                pass
    
    # Se chamou /entrega sem parâmetros ou com parâmetro inválido
    print("DEBUG /entrega: No valid args, showing error")
    await update.message.reply_text(
        "⚠️ *Comando Incorreto*\n\n"
        "Use o botão *'Entregar'* no mapa interativo para iniciar uma entrega.\n\n"
        "💡 Este comando é usado automaticamente quando você clica nos botões de entrega.",
        parse_mode='Markdown'
    )
    return ConversationHandler.END


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando de ajuda personalizado por role"""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_user_id == update.effective_user.id).first()
        
        if not user:
            await update.message.reply_text(
                "⚠️ Você ainda não está registrado.\n\n"
                "Use /start para começar!",
                parse_mode='Markdown'
            )
            return
        
        if user.role == "manager":
            help_text = (
                "╔══════════════════════════╗\n"
                "║  🎯 *CENTRAL DO GERENTE*  ║\n"
                "╚══════════════════════════╝\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "📦 *GESTÃO DE ROTAS*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                "🆕 */importar*\n"
                "   └ Importa planilha Excel/CSV\n"
                "   └ Escolha o nome da rota\n"
                "   └ Sistema geocodifica endereços\n"
                "   └ Suporta múltiplos formatos\n\n"
                
                "🚚 */enviarrota*\n"
                "   └ Atribui rota ao motorista\n"
                "   └ Otimização automática ⚡\n"
                "   └ Link de rastreamento gerado\n"
                "   └ Notifica motorista no Telegram\n\n"
                
                "🗺️ */rastrear*\n"
                "   └ Acompanha rotas ativas\n"
                "   └ Localização GPS em tempo real\n"
                "   └ Atualização a cada 30 segundos\n"
                "   └ Status de cada entrega\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "👥 *GESTÃO DE EQUIPE*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                "➕ */cadastrardriver*\n"
                "   └ Adiciona novo motorista\n"
                "   └ Pede Telegram ID e nome\n"
                "   └ Acesso imediato ao sistema\n\n"
                
                "📋 */drivers*\n"
                "   └ Lista todos motoristas\n"
                "   └ 🟢 Em rota / ⚪ Disponível\n"
                "   └ 🗺️ Rastrear | 🗑️ Remover\n"
                "   └ Informações de contato\n\n"
                
                "🏠 */configurarcasa*\n"
                "   └ Define ponto de partida\n"
                "   └ Envia localização GPS\n"
                "   └ Rotas otimizadas personalizadas\n"
                "   └ Economia de combustível 📉\n\n"
                
                "📢 */configurarcanal*\n"
                "   └ Canal de entregas por motorista\n"
                "   └ Organiza provas de entrega\n"
                "   └ Fotos separadas por canal\n"
                "   └ Sem poluição no bot\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "💰 *FINANCEIRO & RELATÓRIOS*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                "📊 */registrardia*\n"
                "   └ Registra dados do dia\n"
                "   └ KM rodados e combustível\n"
                "   └ Receitas e despesas\n"
                "   └ Salários pagos\n\n"
                
                "🤖 */relatorio*\n"
                "   └ Relatório inteligente com IA\n"
                "   └ Análise de desempenho\n"
                "   └ Insights financeiros\n"
                "   └ Sugestões de otimização\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "⚙️ *RECURSOS AVANÇADOS*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                "🎯 *Otimização de Rotas:*\n"
                "   • Algoritmo Nearest Neighbor\n"
                "   • Calcula menor caminho\n"
                "   • Usa endereço do motorista\n"
                "   • Economia de tempo e combustível\n\n"
                
                "📍 *Rastreamento Real:*\n"
                "   • GPS ao vivo do motorista\n"
                "   • Histórico de entregas\n"
                "   • Tempo por entrega\n"
                "   • Provas fotográficas\n\n"
                
                "📱 *Notificações Push:*\n"
                "   • Entrega concluída ✅\n"
                "   • Falha na entrega ❌\n"
                "   • Atualização de status\n"
                "   • Fotos automáticas no canal\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🔧 *UTILITÁRIOS*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                "🆔 */meu_id* - Seu Telegram ID\n"
                "❓ */help* - Esta mensagem\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 *DICAS PRO*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                "1️⃣ *Nomeie rotas* (ex: Zona Sul, Centro)\n"
                "   → Facilita identificação\n\n"
                
                "2️⃣ *Configure canais separados*\n"
                "   → Organiza provas por motorista\n\n"
                
                "3️⃣ *Peça aos motoristas* para usar /configurarcasa\n"
                "   → Otimização personalizada\n\n"
                
                "4️⃣ *Use /rastrear* frequentemente\n"
                "   → Acompanhe progresso real\n\n"
                
                "5️⃣ *Relatórios IA* semanalmente\n"
                "   → Insights valiosos para decisões\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🚀 *WORKFLOW RECOMENDADO*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                "📥 *1. Importar* planilha com /importar\n"
                "↓\n"
                "🚚 *2. Enviar* rota com /enviarrota\n"
                "↓\n"
                "👀 *3. Rastrear* com /rastrear\n"
                "↓\n"
                "✅ *4. Receber* notificações automáticas\n"
                "↓\n"
                "📊 *5. Registrar* finanças com /registrardia\n"
                "↓\n"
                "🤖 *6. Analisar* com /relatorio\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "🌟 *Sistema completo de gestão*\n"
                "🌟 *Rastreamento em tempo real*\n"
                "🌟 *Otimização inteligente*\n"
                "🌟 *Relatórios com IA*\n\n"
                
                "💬 *Dúvidas?* Teste os comandos!\n"
                "⚡ *Comece agora* com /importar"
            )
        else:
            help_text = (
                "╔═══════════════════════════╗\n"
                "║  🚚 *CENTRAL DO MOTORISTA*  ║\n"
                "╚═══════════════════════════╝\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "📍 *COMO FUNCIONA*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                "1️⃣ Gerente atribui rota para você\n"
                "2️⃣ Você recebe link do mapa 🗺️\n"
                "3️⃣ Mapa mostra pacotes numerados\n"
                "4️⃣ Clique no pin para ver detalhes\n"
                "5️⃣ Use '🧭 Navegar' → Google Maps\n"
                "6️⃣ Chegou? Clique '✓ Entregar'\n"
                "7️⃣ Complete registro no Telegram\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "📸 *PROCESSO DE ENTREGA*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                "*Passo 1:* Foto do pacote\n"
                "   └ Mostre a etiqueta clara\n\n"
                
                "*Passo 2:* Foto do local\n"
                "   └ Porta, fachada ou recebedor\n\n"
                
                "*Passo 3:* Nome do recebedor\n"
                "   └ Quem assinou/recebeu\n\n"
                
                "*Passo 4:* Documento (CPF/RG)\n"
                "   └ Ou digite 'sem documento'\n\n"
                
                "*Passo 5:* Observações\n"
                "   └ Informações extras (opcional)\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🗺️ *RECURSOS DO MAPA*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                "⏱️ *Atualização automática* 30s\n"
                "📍 *Sua localização* em tempo real\n"
                "📊 *Contador* pendentes/entregues\n\n"
                
                "*Cores dos Pins:*\n"
                "🔵 Azul = Pendente\n"
                "🟢 Verde = Entregue ✅\n"
                "🔴 Vermelho = Falhou ❌\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🔧 *COMANDOS DISPONÍVEIS*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                "📦 */entregar* - Registrar entrega\n"
                "🆔 */meu_id* - Ver seu Telegram ID\n"
                "🏠 */configurarcasa* - Definir endereço\n"
                "❓ */help* - Esta mensagem\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 *DICAS IMPORTANTES*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                "✅ *Localização ativada*\n"
                "   → Gerente acompanha em tempo real\n\n"
                
                "✅ *Fotos claras e nítidas*\n"
                "   → Evita problemas futuros\n\n"
                
                "✅ *Use o mapa interativo*\n"
                "   → Melhor experiência de navegação\n\n"
                
                "✅ *Configure /configurarcasa*\n"
                "   → Rotas otimizadas para você\n\n"
                
                "✅ *Mapa funciona offline*\n"
                "   → Após carregar primeira vez\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "📱 *NOTIFICAÇÕES*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                "Você receberá mensagens quando:\n"
                "• Nova rota for atribuída 🎯\n"
                "• Entrega for confirmada ✅\n"
                "• Houver algum problema ⚠️\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                "🌟 *Trabalhe com eficiência*\n"
                "🌟 *Rastreamento em tempo real*\n"
                "🌟 *Rotas otimizadas*\n\n"
                
                "❓ *Dúvidas?* Fale com seu gerente!\n"
                "🚀 *Boa sorte nas entregas!*"
            )
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
        
    finally:
        db.close()


async def cmd_relatorio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gera relatório financeiro com análise de IA (Gemini)"""
    db = SessionLocal()
    try:
        # Verifica permissão
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            await update.message.reply_text(
                "⛔ *Acesso Negado*\n\n"
                "Apenas gerentes podem gerar relatórios.",
                parse_mode='Markdown'
            )
            return
        
        # Verifica se Gemini está configurado
        if not gemini_model:
            await update.message.reply_text(
                "⚠️ *IA Não Configurada*\n\n"
                "Configure a chave da API Gemini no arquivo `.env`:\n"
                "`GEMINI_API_KEY=sua_chave_aqui`\n\n"
                "Obtenha sua chave gratuita em:\n"
                "https://aistudio.google.com/app/apikey",
                parse_mode='Markdown'
            )
            return
        
        # Envia mensagem de processamento
        processing_msg = await update.message.reply_text(
            "🤖 *Gerando Relatório...*\n\n"
            "⏳ Coletando dados financeiros e de entregas...",
            parse_mode='Markdown'
        )
        
        # Coleta dados do mês atual
        now = datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Dados de entregas (packages não tem created_at, usar route.created_at)
        total_packages = db.query(Package).join(Route).filter(Route.created_at >= month_start).count()
        delivered_packages = db.query(Package).join(Route).filter(
            Route.created_at >= month_start,
            Package.status == "delivered"
        ).count()
        failed_packages = db.query(Package).join(Route).filter(
            Route.created_at >= month_start,
            Package.status == "failed"
        ).count()
        
        # Dados de rotas
        total_routes = db.query(Route).filter(Route.created_at >= month_start).count()
        active_drivers = db.query(User).filter(User.role == "driver").count()
        
        # Dados financeiros
        total_income = db.query(Income).filter(Income.date >= month_start.date()).count()
        total_expenses = db.query(Expense).filter(Expense.date >= month_start.date()).count()
        total_mileage = db.query(Mileage).filter(Mileage.date >= month_start.date()).count()
        
        # Monta prompt para a IA
        prompt = f"""Você é um analista financeiro especializado em logística e entregas. 
Analise os dados abaixo e forneça um relatório completo e profissional em português do Brasil.

**DADOS DO MÊS ATUAL ({now.strftime('%B/%Y')})**

📦 ENTREGAS:
- Total de pacotes: {total_packages}
- Entregues: {delivered_packages}
- Falhas: {failed_packages}
- Taxa de sucesso: {(delivered_packages/total_packages*100 if total_packages > 0 else 0):.1f}%

🚚 OPERAÇÕES:
- Rotas criadas: {total_routes}
- Motoristas ativos: {active_drivers}
- Média pacotes/rota: {(total_packages/total_routes if total_routes > 0 else 0):.1f}

💰 REGISTROS FINANCEIROS:
- Receitas registradas: {total_income}
- Despesas registradas: {total_expenses}
- Registros de KM: {total_mileage}

**IMPORTANTE:**
- Forneça uma análise detalhada com insights acionáveis
- Identifique pontos fortes e áreas de melhoria
- Sugira ações concretas para otimização
- Use emojis para tornar o relatório mais visual
- Seja objetivo mas completo (máximo 800 palavras)
- Estruture com seções: Resumo Executivo, Desempenho Operacional, Análise Financeira, Recomendações

Gere o relatório agora:"""

        # Atualiza mensagem
        await processing_msg.edit_text(
            "🤖 *Gerando Relatório...*\n\n"
            "🧠 IA analisando dados...",
            parse_mode='Markdown'
        )
        
        # Gera relatório com Gemini
        try:
            response = gemini_model.generate_content(prompt)
            ai_analysis = response.text
            
            # Salva no banco
            report = AIReport(
                user_id=me.id,
                report_type="monthly_financial",
                prompt_data=prompt,
                ai_response=ai_analysis
            )
            db.add(report)
            db.commit()
            
            # Divide relatório em mensagens (limite Telegram: 4096 chars)
            max_length = 4000
            if len(ai_analysis) <= max_length:
                await processing_msg.edit_text(
                    f"📊 *Relatório Financeiro - {now.strftime('%B/%Y')}*\n\n{ai_analysis}",
                    parse_mode='Markdown'
                )
            else:
                # Envia em partes
                await processing_msg.delete()
                parts = [ai_analysis[i:i+max_length] for i in range(0, len(ai_analysis), max_length)]
                
                await update.message.reply_text(
                    f"📊 *Relatório Financeiro - {now.strftime('%B/%Y')}*\n\n{parts[0]}",
                    parse_mode='Markdown'
                )
                
                for part in parts[1:]:
                    await update.message.reply_text(part, parse_mode='Markdown')
            
            # Mensagem final
            await update.message.reply_text(
                "✅ *Relatório salvo!*\n\n"
                f"🤖 Gerado por IA Gemini\n"
                f"📅 {now.strftime('%d/%m/%Y %H:%M')}\n\n"
                "_Use /relatorio novamente para atualizar._",
                parse_mode='Markdown'
            )
            
        except Exception as e:
            await processing_msg.edit_text(
                f"❌ *Erro ao gerar relatório*\n\n"
                f"Detalhes: {str(e)}\n\n"
                f"Verifique sua chave da API Gemini.",
                parse_mode='Markdown'
            )
    
    finally:
        db.close()


async def cmd_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando universal para cancelar qualquer operação em andamento"""
    # Limpa todos os dados do contexto do usuário
    context.user_data.clear()
    
    await update.message.reply_text(
        "❌ *Operação Cancelada*\n\n"
        "Todas as ações em andamento foram canceladas.\n\n"
        "Use /help para ver os comandos disponíveis.",
        parse_mode='Markdown'
    )
    return ConversationHandler.END


async def cmd_meu_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Detecta se é canal, grupo ou chat privado
    chat = update.effective_chat
    user_id = update.effective_user.id
    
    if chat.type == "private":
        # Chat privado - mostra ID do usuário
        await update.message.reply_text(
            f"🆔 *Seu Telegram ID*\n\n"
            f"ID: `{user_id}`\n\n"
            f"_Copie este número se o gerente solicitar._",
            parse_mode='Markdown'
        )
    elif chat.type == "channel":
        # Canal - mostra ID do canal
        await update.message.reply_text(
            f"📢 *ID deste Canal*\n\n"
            f"ID do Canal: `{chat.id}`\n\n"
            f"✅ *Use este ID no comando /configurarcanal*\n\n"
            f"_Copie o número acima (incluindo o `-`)_",
            parse_mode='Markdown'
        )
    elif chat.type in ["group", "supergroup"]:
        # Grupo - mostra ID do grupo
        await update.message.reply_text(
            f"👥 *ID deste Grupo*\n\n"
            f"ID do Grupo: `{chat.id}`\n\n"
            f"_Você também pode usar grupos para provas de entrega!_",
            parse_mode='Markdown'
        )


async def cmd_rastrear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Permite gerente rastrear rotas ativas em tempo real"""
    db = SessionLocal()
    try:
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            await update.message.reply_text(
                "⛔ *Acesso Negado*\n\n"
                "Apenas gerentes podem rastrear rotas.",
                parse_mode='Markdown'
            )
            return
        
        # Busca rotas com motoristas atribuídos
        routes = db.query(Route).filter(Route.assigned_to_id.isnot(None)).order_by(Route.created_at.desc()).all()
        
        if not routes:
            await update.message.reply_text(
                "📭 *Nenhuma Rota Ativa*\n\n"
                "Não há rotas atribuídas a motoristas no momento.\n\n"
                "Use /enviarrota para atribuir uma rota primeiro!",
                parse_mode='Markdown'
            )
            return
        
        # Cria keyboard com rotas
        keyboard = []
        for route in routes[:20]:  # Limita a 20 rotas
            driver = route.assigned_to
            driver_name = driver.full_name or f"ID {driver.telegram_user_id}" if driver else "Sem motorista"
            route_name = route.name or f"Rota {route.id}"
            
            # Conta pacotes
            total = db.query(Package).filter(Package.route_id == route.id).count()
            delivered = db.query(Package).filter(
                Package.route_id == route.id,
                Package.status == "delivered"
            ).count()
            
            # Botão com informações da rota
            keyboard.append([
                InlineKeyboardButton(
                    text=f"🗺️ {route_name} - {driver_name} ({delivered}/{total})",
                    callback_data=f"track_route:{route.id}"
                )
            ])
        
        await update.message.reply_text(
            "🗺️ *Rastreamento de Rotas*\n\n"
            "Selecione uma rota para abrir o mapa de rastreamento:\n\n"
            "_O mapa atualiza a cada 30 segundos automaticamente._",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        
    finally:
        db.close()


async def on_track_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para abrir link de rastreamento"""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    if not data.startswith("track_route:"):
        return
    
    route_id = int(data.split(":", 1)[1])
    
    db = SessionLocal()
    try:
        route = db.get(Route, route_id)
        if not route or not route.assigned_to:
            await query.answer("❌ Rota não encontrada!", show_alert=True)
            return
        
        driver = route.assigned_to
        driver_name = driver.full_name or f"ID {driver.telegram_user_id}"
        route_name = route.name or f"Rota {route.id}"
        
        # Gera link do mapa
        map_link = f"{BASE_URL}/map/{route.id}/{driver.telegram_user_id}"
        
        # Conta status dos pacotes
        total = db.query(Package).filter(Package.route_id == route.id).count()
        delivered = db.query(Package).filter(
            Package.route_id == route.id,
            Package.status == "delivered"
        ).count()
        pending = total - delivered
        
        await query.edit_message_text(
            f"🗺️ *Rastreamento em Tempo Real*\n\n"
            f"📦 *Rota:* {route_name}\n"
            f"👤 *Motorista:* {driver_name}\n\n"
            f"📊 *Status:*\n"
            f"• Pendentes: {pending}\n"
            f"• Entregues: {delivered}\n"
            f"• Total: {total}\n\n"
            f"🔗 *Link do Mapa:*\n"
            f"{map_link}\n\n"
            f"✅ Atualização automática a cada 30 segundos\n"
            f"📍 Ponto azul = localização do motorista\n\n"
            f"_Clique no link acima para abrir o mapa!_",
            parse_mode='Markdown'
        )
        
    finally:
        db.close()


async def cmd_configurarcanal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Configura canal do Telegram para receber provas de entrega de um motorista"""
    db = SessionLocal()
    try:
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            await update.message.reply_text(
                "⛔ *Acesso Negado*\n\n"
                "Apenas gerentes podem configurar canais.",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        # Lista motoristas
        drivers = db.query(User).filter(User.role == "driver").all()
        
        if not drivers:
            await update.message.reply_text(
                "📭 *Nenhum Motorista Cadastrado*\n\n"
                "Use /cadastrardriver para cadastrar motoristas primeiro!",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        # Cria keyboard com motoristas
        keyboard = []
        for driver in drivers[:20]:
            name = driver.full_name or f"ID {driver.telegram_user_id}"
            has_channel = "✅" if driver.channel_id else "⚪"
            
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{has_channel} {name}",
                    callback_data=f"config_channel:{driver.id}"
                )
            ])
        
        await update.message.reply_text(
            "📢 *Configurar Canal de Entregas*\n\n"
            "Selecione o motorista:\n\n"
            "✅ = Canal já configurado\n"
            "⚪ = Sem canal",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return CONFIG_CHANNEL_SELECT_DRIVER
        
    finally:
        db.close()


async def on_config_channel_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback quando motorista é selecionado para configurar canal"""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    if not data.startswith("config_channel:"):
        return CONFIG_CHANNEL_SELECT_DRIVER
    
    driver_id = int(data.split(":", 1)[1])
    context.user_data['config_channel_driver_id'] = driver_id
    
    db = SessionLocal()
    try:
        driver = db.get(User, driver_id)
        if not driver:
            await query.answer("❌ Motorista não encontrado!", show_alert=True)
            return ConversationHandler.END
        
        driver_name = driver.full_name or f"ID {driver.telegram_user_id}"
        current_channel = driver.channel_id or "Nenhum"
        
        await query.edit_message_text(
            f"📢 *Configurar Canal*\n\n"
            f"👤 *Motorista:* {driver_name}\n"
            f"📡 *Canal Atual:* `{current_channel}`\n\n"
            f"🔧 *Como obter o ID do canal:*\n\n"
            f"1️⃣ Crie um canal privado no Telegram\n"
            f"2️⃣ Adicione o bot como administrador\n"
            f"3️⃣ Envie /meu\\_id no canal\n"
            f"4️⃣ O bot responderá com o ID do canal\n"
            f"5️⃣ Copie o ID e envie aqui\n\n"
            f"💡 *Agora envie o ID do canal:*\n"
            f"Exemplo: `-1001234567890`\n\n"
            f"Ou envie *REMOVER* para desconfigurar o canal.",
            parse_mode='Markdown'
        )
        return CONFIG_CHANNEL_ENTER_ID
        
    finally:
        db.close()


async def on_config_channel_enter_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o ID do canal e salva"""
    channel_input = update.message.text.strip()
    driver_id = context.user_data.get('config_channel_driver_id')
    
    if not driver_id:
        await update.message.reply_text(
            "❌ *Sessão Expirada*\n\n"
            "Use /configurarcanal novamente.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    
    db = SessionLocal()
    try:
        driver = db.get(User, driver_id)
        if not driver:
            await update.message.reply_text(
                "❌ *Motorista não encontrado!*",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        driver_name = driver.full_name or f"ID {driver.telegram_user_id}"
        
        # Verifica se quer remover
        if channel_input.upper() == "REMOVER":
            driver.channel_id = None
            db.commit()
            
            await update.message.reply_text(
                f"✅ *Canal Removido!*\n\n"
                f"👤 *Motorista:* {driver_name}\n\n"
                f"As provas de entrega voltarão a ser enviadas para você.",
                parse_mode='Markdown'
            )
            context.user_data.clear()
            return ConversationHandler.END
        
        # Valida formato do ID do canal
        if not channel_input.startswith('-100'):
            await update.message.reply_text(
                "⚠️ *ID Inválido!*\n\n"
                "O ID do canal deve começar com `-100`\n"
                "Exemplo: `-1001234567890`\n\n"
                "Tente novamente ou envie *CANCELAR*.",
                parse_mode='Markdown'
            )
            return CONFIG_CHANNEL_ENTER_ID
        
        # Testa se o bot consegue acessar o canal
        try:
            await context.bot.send_message(
                chat_id=channel_input,
                text=f"✅ *Canal Configurado com Sucesso!*\n\n"
                     f"👤 *Motorista:* {driver_name}\n\n"
                     f"📸 As provas de entrega serão enviadas para este canal.",
                parse_mode='Markdown'
            )
            
            # Salva no banco
            driver.channel_id = channel_input
            db.commit()
            
            await update.message.reply_text(
                f"✅ *Canal Configurado!*\n\n"
                f"👤 *Motorista:* {driver_name}\n"
                f"📡 *Canal:* `{channel_input}`\n\n"
                f"📸 As próximas entregas dele serão enviadas para o canal!",
                parse_mode='Markdown'
            )
            context.user_data.clear()
            return ConversationHandler.END
            
        except Exception as e:
            await update.message.reply_text(
                f"❌ *Erro ao Acessar o Canal!*\n\n"
                f"Possíveis causas:\n"
                f"• O bot não foi adicionado como administrador\n"
                f"• O ID está incorreto\n"
                f"• O canal não existe\n\n"
                f"Detalhes: {str(e)}\n\n"
                f"Tente novamente ou envie *CANCELAR*.",
                parse_mode='Markdown'
            )
            return CONFIG_CHANNEL_ENTER_ID
    
    finally:
        db.close()


# ==================== CONFIGURAR ENDEREÇO DE CASA ====================

async def cmd_configurarcasa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manager configura endereço de casa de um motorista, ou motorista configura o próprio"""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.telegram_user_id == update.effective_user.id).first()
        if not user:
            await update.message.reply_text("❌ Usuário não encontrado. Use /start primeiro!")
            return ConversationHandler.END
        
        # Se for MOTORISTA, vai direto para enviar localização
        if user.role == "driver":
            await update.message.reply_text(
                "📍 *Configurar Seu Endereço de Casa*\n\n"
                "Para otimizar suas rotas, preciso saber seu ponto de partida!\n\n"
                "📲 *Envie sua localização:*\n"
                "1. Clique no 📎 (anexo)\n"
                "2. Escolha *'Localização'*\n"
                "3. Envie sua *localização atual* ou *procure seu endereço*\n\n"
                "💡 *Isso permite:*\n"
                "• Rotas otimizadas a partir da SUA casa\n"
                "• Menos km rodados = economia de combustível\n"
                "• Sequência de entregas mais eficiente\n\n"
                "Use /cancelar para desistir.",
                parse_mode='Markdown'
            )
            # Salva que é configuração própria
            context.user_data['config_home_driver_id'] = user.id
            return CONFIG_HOME_LOCATION
        
        # Se for MANAGER, lista motoristas para escolher
        drivers = db.query(User).filter(User.role == "driver").all()
        if not drivers:
            await update.message.reply_text(
                "📭 *Nenhum Motorista Cadastrado*\n\n"
                "Use /cadastrardriver primeiro!",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        keyboard = []
        for driver in drivers:
            driver_name = driver.full_name or f"ID {driver.telegram_user_id}"
            has_home = "🏠" if driver.home_latitude else "⚪"
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{has_home} {driver_name}",
                    callback_data=f"config_home:{driver.id}"
                )
            ])
        
        await update.message.reply_text(
            "👥 *Configurar Casa do Motorista*\n\n"
            "Selecione o motorista para configurar o endereço:\n\n"
            "🏠 = já configurado\n"
            "⚪ = não configurado\n\n"
            "Use /cancelar para desistir.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return CONFIG_HOME_SELECT_DRIVER
        
    finally:
        db.close()


async def on_config_home_select_driver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manager selecionou um motorista para configurar casa"""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    if not data.startswith("config_home:"):
        return ConversationHandler.END
    
    driver_id = int(data.split(":", 1)[1])
    
    db = SessionLocal()
    try:
        driver = db.get(User, driver_id)
        if not driver:
            await query.edit_message_text("❌ Motorista não encontrado!")
            return ConversationHandler.END
        
        driver_name = driver.full_name or f"ID {driver.telegram_user_id}"
        
        # Salva qual motorista está sendo configurado
        context.user_data['config_home_driver_id'] = driver_id
        
        await query.edit_message_text(
            f"📍 *Configurar Casa: {driver_name}*\n\n"
            f"Agora envie a localização da casa do motorista.\n\n"
            f"📲 *Como enviar:*\n"
            f"1. Clique no 📎 (anexo)\n"
            f"2. Escolha *'Localização'*\n"
            f"3. Envie a localização ou procure o endereço\n\n"
            f"💡 Você pode compartilhar a localização salva ou buscar um endereço específico.\n\n"
            f"Use /cancelar para desistir.",
            parse_mode='Markdown'
        )
        return CONFIG_HOME_LOCATION
        
    finally:
        db.close()


async def on_config_home_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe a localização e salva no motorista"""
    if not update.message.location:
        await update.message.reply_text(
            "⚠️ *Por favor, envie uma localização!*\n\n"
            "Use o botão de anexo 📎 → Localização\n\n"
            "Use /cancelar para desistir.",
            parse_mode='Markdown'
        )
        return CONFIG_HOME_LOCATION
    
    location = update.message.location
    driver_id = context.user_data.get('config_home_driver_id')
    
    if not driver_id:
        await update.message.reply_text("❌ Erro: Motorista não identificado!")
        return ConversationHandler.END
    
    db = SessionLocal()
    try:
        driver = db.get(User, driver_id)
        if not driver:
            await update.message.reply_text("❌ Motorista não encontrado!")
            return ConversationHandler.END
        
        # Salva coordenadas
        driver.home_latitude = location.latitude
        driver.home_longitude = location.longitude
        driver.home_address = f"Lat: {location.latitude:.6f}, Lon: {location.longitude:.6f}"
        db.commit()
        
        driver_name = driver.full_name or f"ID {driver.telegram_user_id}"
        
        await update.message.reply_text(
            f"✅ *Casa Configurada: {driver_name}*\n\n"
            f"📍 *Localização:*\n"
            f"Latitude: `{location.latitude:.6f}`\n"
            f"Longitude: `{location.longitude:.6f}`\n\n"
            f"🎯 *A partir de agora:*\n"
            f"• Rotas deste motorista serão otimizadas deste ponto\n"
            f"• Sequência calculada para menor distância\n"
            f"• Pode alterar quando quiser com /configurarcasa\n\n"
            f"💡 *Dica:* Atualize se o motorista mudar de endereço!",
            parse_mode='Markdown'
        )
        
        # Limpa o contexto
        context.user_data.pop('config_home_driver_id', None)
        return ConversationHandler.END
        
    finally:
        db.close()


# ==================== ENVIAR ROTA PARA MOTORISTA ====================

async def cmd_enviarrota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando para gerente enviar rota para motorista"""
    db = SessionLocal()
    try:
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            await update.message.reply_text(
                "⛔ *Acesso Negado*\n\n"
                "Apenas gerentes podem enviar rotas para motoristas.",
                parse_mode='Markdown'
            )
            return
        args = context.args or []
        if len(args) == 2:
            try:
                route_id = int(args[0])
                driver_tid = int(args[1])
            except ValueError:
                await update.message.reply_text(
                    "❌ *IDs Inválidos*\n\n"
                    "Use: `/enviarrota <id_rota> <id_motorista>`",
                    parse_mode='Markdown'
                )
                return
            route = db.get(Route, route_id)
            if not route:
                await update.message.reply_text(
                    "❌ *Rota Não Encontrada*\n\n"
                    f"Não existe rota com ID `{route_id}`.",
                    parse_mode='Markdown'
                )
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
            route_name = route.name or f"Rota {route.id}"
            driver_name = driver.full_name or f"ID {driver_tid}"
            
            try:
                # Envia para o motorista
                await context.bot.send_message(
                    chat_id=driver_tid,
                    text=(
                        f"🎯 *Nova Rota Atribuída!*\n\n"
                        f"📦 Rota: *{route_name}*\n"
                        f"📊 Total de Pacotes: *{count}*\n"
                        f"🗺️ Mapa Interativo: [Clique Aqui]({link})\n\n"
                        f"💡 _Abra o mapa para ver todas as entregas e começar!_"
                    ),
                    parse_mode='Markdown'
                )
                
                # Envia também para o gerente (para rastreamento)
                await update.message.reply_text(
                    f"✅ *Rota Enviada com Sucesso!*\n\n"
                    f"📦 *Rota:* {route_name}\n"
                    f"👤 *Motorista:* {driver_name}\n"
                    f"📊 *Pacotes:* {count}\n\n"
                    f"🗺️ *Link de Rastreamento:*\n"
                    f"{link}\n\n"
                    f"💡 _Use este link para acompanhar em tempo real!_\n"
                    f"_Atualização automática a cada 30 segundos._",
                    parse_mode='Markdown'
                )
            except Exception:
                await update.message.reply_text(
                    "⚠️ *Erro ao Enviar*\n\n"
                    "Não consegui enviar a mensagem ao motorista.\n\n"
                    "Possíveis causas:\n"
                    "• O motorista ainda não iniciou conversa com o bot\n"
                    "• O ID do motorista está incorreto\n\n"
                    "💡 Peça ao motorista para enviar /start no bot.",
                    parse_mode='Markdown'
                )
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
        await update.message.reply_text(
            "📭 *Nenhuma Rota Disponível*\n\n"
            "Use /importar para criar uma nova rota primeiro!",
            parse_mode='Markdown'
        )
        return
    
    # Criar keyboard com botões de info e deletar
    keyboard = []
    for r in routes[:25]:
        route_name = r.name or 'Rota'
        keyboard.append([
            InlineKeyboardButton(text=f"📦 {route_name} (ID {r.id})", callback_data=f"sel_route:{r.id}"),
            InlineKeyboardButton(text="🗑️", callback_data=f"delete_route:{r.id}")
        ])
    
    await update.message.reply_text(
        "🚚 *Enviar Rota para Motorista*\n\n"
        "Selecione a rota que deseja atribuir:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return SEND_SELECT_ROUTE


async def on_select_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback quando gerente seleciona uma rota"""
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
        await query.edit_message_text(
            "👥 *Nenhum Motorista Cadastrado*\n\n"
            "Use /cadastrardriver para adicionar motoristas primeiro!",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(text=f"👤 {(d.full_name or 'Sem nome')} (ID {d.telegram_user_id})",
                                       callback_data=f"sel_driver:{d.telegram_user_id}")]
                for d in drivers[:25]]
    await query.edit_message_text(
        f"🚚 *Rota Selecionada: ID {route_id}*\n\n"
        f"Agora escolha o motorista que receberá esta rota:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return SEND_SELECT_DRIVER


async def on_select_driver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback quando gerente seleciona motorista para receber rota"""
    query = update.callback_query
    data = query.data or ""
    if not data.startswith("sel_driver:"):
        await query.answer()
        return
    
    driver_tid = int(data.split(":", 1)[1])
    route_id = context.user_data.get("send_route_id")
    
    # Responde IMEDIATAMENTE ao callback para evitar timeout
    await query.answer("Processando rota...")
    
    if not route_id:
        await query.edit_message_text(
            "❌ *Erro Interno*\n\n"
            "Rota não selecionada. Tente novamente com /enviarrota.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    db = SessionLocal()
    try:
        route = db.get(Route, int(route_id))
        if not route:
            await query.edit_message_text(
                "❌ *Rota Não Encontrada*\n\n"
                f"A rota ID `{route_id}` não existe mais.",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        driver = get_user_by_tid(db, driver_tid)
        if not driver:
            driver = User(telegram_user_id=driver_tid, full_name=None, role="driver")
            db.add(driver)
            db.flush()
        
        route.assigned_to_id = driver.id
        db.commit()
        
        # Informações básicas
        count = db.query(Package).filter(Package.route_id == route.id).count()
        route_name = route.name or f"Rota {route.id}"
        driver_name = driver.full_name or f"ID {driver_tid}"
        
        # Edita mensagem para mostrar progresso
        await query.edit_message_text(
            f"⏳ *Processando Rota...*\n\n"
            f"📦 *Rota:* {route_name}\n"
            f"👤 *Motorista:* {driver_name}\n"
            f"📊 *Pacotes:* {count}\n\n"
            f"🔄 _Otimizando sequência de entregas..._",
            parse_mode='Markdown'
        )
        
        # ==================== OTIMIZAÇÃO DE ROTA POR MOTORISTA ====================
        # Busca todos os pacotes da rota
        all_packages = db.query(Package).filter(Package.route_id == route.id).all()
        
        # Usa o endereço de casa do motorista (se configurado) ou coordenadas padrão
        start_lat = driver.home_latitude or DEPOT_LAT
        start_lon = driver.home_longitude or DEPOT_LON
        
        # Otimiza a ordem usando TSP com o ponto de partida do motorista
        optimized_count = optimize_route_packages(db, all_packages, start_lat, start_lon)
        
        # Mensagem sobre otimização
        if driver.home_latitude and driver.home_longitude:
            opt_msg = f"\n🎯 *Rota otimizada* a partir da casa do motorista!"
        else:
            opt_msg = f"\n⚠️ _Motorista sem endereço cadastrado. Use /configurarcasa._"
        # ========================================================================
        
        link = f"{BASE_URL}/map/{route.id}/{driver_tid}"
        
        try:
            await context.bot.send_message(
                chat_id=driver_tid,
                text=(
                    f"🎯 *Nova Rota Atribuída!*\n\n"
                    f"📦 Rota: *{route_name}*\n"
                    f"📊 Total de Pacotes: *{count}*\n"
                    f"🗺️ Mapa Interativo: [Clique Aqui]({link})\n"
                    f"{opt_msg}\n\n"
                    f"💡 _Abra o mapa para ver todas as entregas e começar!_"
                ),
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            await query.edit_message_text(
                f"✅ *Rota Enviada com Sucesso!*\n\n"
                f"📦 *Rota:* {route_name}\n"
                f"👤 *Motorista:* {driver_name}\n"
                f"📊 *Pacotes:* {count}\n"
                f"{opt_msg}\n\n"
                f"🗺️ *Link de Rastreamento:*\n"
                f"{link}\n\n"
                f"💡 _Use este link para acompanhar em tempo real!_",
                parse_mode='Markdown'
            )
        except Exception:
            await query.edit_message_text(
                "⚠️ *Erro ao Enviar*\n\n"
                "Não consegui enviar a mensagem ao motorista.\n\n"
                "Possíveis causas:\n"
                "• O motorista ainda não iniciou conversa com o bot\n"
                "• O ID do motorista está incorreto\n\n"
                "💡 Peça ao motorista para enviar /start no bot.",
                parse_mode='Markdown'
            )
    finally:
        db.close()
    context.user_data.pop("send_route_id", None)
    return ConversationHandler.END


async def on_delete_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para excluir rota"""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    if not data.startswith("delete_route:"):
        return
    
    route_id = int(data.split(":", 1)[1])
    
    db = SessionLocal()
    try:
        # Verifica permissão
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            await query.answer("⛔ Apenas gerentes podem excluir rotas!", show_alert=True)
            return
        
        # Busca rota
        route = db.get(Route, route_id)
        if not route:
            await query.answer("❌ Rota não encontrada!", show_alert=True)
            return
        
        route_name = route.name or f"Rota {route.id}"
        
        # Conta pacotes e comprovantes
        package_count = db.query(Package).filter(Package.route_id == route_id).count()
        proof_count = db.query(DeliveryProof).join(Package).filter(Package.route_id == route_id).count()
        
        # Deleta comprovantes associados primeiro
        if proof_count > 0:
            db.query(DeliveryProof).filter(
                DeliveryProof.package_id.in_(
                    db.query(Package.id).filter(Package.route_id == route_id)
                )
            ).delete(synchronize_session=False)
        
        # Deleta pacotes
        db.query(Package).filter(Package.route_id == route_id).delete()
        
        # Deleta rota
        db.delete(route)
        db.commit()
        
        await query.edit_message_text(
            f"✅ *Rota Excluída!*\n\n"
            f"📦 {route_name}\n"
            f"🗑️ Foram removidos:\n"
            f"• {package_count} pacote(s)\n"
            f"• {proof_count} comprovante(s)\n\n"
            f"Use /importar para criar novas rotas.",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await query.answer(f"❌ Erro ao excluir: {str(e)}", show_alert=True)
    finally:
        db.close()


async def cmd_importar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            await update.message.reply_text(
                "⛔ *Acesso Negado*\n\n"
                "Apenas gerentes podem importar rotas.\n\n"
                "Se você é motorista, aguarde o gerente enviar as rotas para você!",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
    finally:
        db.close()
    
    await update.message.reply_text(
        "� *Importar Nova Rota*\n\n"
        "Primeiro, me diga:\n\n"
        "🏷️ *Qual é o nome desta rota?*\n\n"
        "_Exemplo: Zona Sul, Centro, Barra, etc._",
        parse_mode='Markdown'
    )
    return IMPORT_ASK_NAME


async def handle_route_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o nome da rota e pede o arquivo"""
    route_name = update.message.text.strip()
    
    if not route_name or len(route_name) < 2:
        await update.message.reply_text(
            "⚠️ *Nome muito curto!*\n\n"
            "Por favor, envie um nome com pelo menos 2 caracteres.",
            parse_mode='Markdown'
        )
        return IMPORT_ASK_NAME
    
    # Salva o nome no contexto
    context.user_data['route_name'] = route_name
    
    await update.message.reply_text(
        f"✅ *Nome da Rota:* {route_name}\n\n"
        "📂 *Agora envie o arquivo*\n\n"
        "Formatos aceitos: Excel (.xlsx) ou CSV (.csv)\n\n"
        "*Colunas necessárias:*\n"
        "• Código de Rastreio (obrigatório)\n"
        "• Endereço (obrigatório)\n"
        "• Latitude (opcional)\n"
        "• Longitude (opcional)\n"
        "• Bairro (opcional)\n\n"
        "💡 _O sistema reconhece automaticamente os nomes das colunas._",
        parse_mode='Markdown'
    )
    return IMPORT_WAITING_FILE


async def handle_import_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc:
        await update.message.reply_text(
            "❌ Nenhum arquivo detectado.\n\nPor favor, envie um arquivo .xlsx ou .csv.",
            parse_mode='Markdown'
        )
        return IMPORT_WAITING_FILE

    filename = doc.file_name or f"import_{update.message.message_id}"
    suffix = Path(filename).suffix.lower()
    if suffix not in [".xlsx", ".csv"]:
        await update.message.reply_text(
            "⚠️ *Formato Inválido*\n\n"
            "Por favor, envie apenas arquivos:\n"
            "• Excel (.xlsx)\n"
            "• CSV (.csv)\n\n"
            f"Arquivo recebido: `{suffix}`",
            parse_mode='Markdown'
        )
        return IMPORT_WAITING_FILE

    await update.message.chat.send_action(action=ChatAction.UPLOAD_DOCUMENT)
    await update.message.reply_text("⏳ Processando arquivo...", parse_mode='Markdown')
    
    file = await doc.get_file()
    local_path = IMPORTS_DIR / filename
    await file.download_to_drive(local_path)

    df = pd.read_excel(local_path) if suffix == ".xlsx" else pd.read_csv(local_path)
    items = parse_import_dataframe(df)
    if not items:
        await update.message.reply_text(
            "❌ *Erro ao Processar*\n\n"
            "Não encontrei dados válidos no arquivo.\n\n"
            "Verifique se o arquivo possui:\n"
            "• Pelo menos uma coluna com códigos de rastreio\n"
            "• Dados nas linhas (não apenas cabeçalhos)",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    db = SessionLocal()
    try:
        # Pega o nome da rota do contexto (salvo em handle_route_name)
        route_name = context.user_data.get('route_name', f"Rota {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        route = Route(name=route_name)
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
        
        # Salva route_id e tracking_codes no context para usar no scraping
        context.user_data['import_route_id'] = route.id
        context.user_data['import_tracking_codes'] = [it["tracking_code"] for it in items]
        context.user_data['import_package_count'] = len(items)
        
        # NOTA: A otimização agora é feita no /enviarrota, após selecionar o motorista
        
        # Pergunta se quer fazer scraping
        
        
        # Pergunta se quer fazer scraping
        keyboard = [['Sim', 'Não']]
        await update.message.reply_text(
            f"✅ *Pacotes Importados!*\n\n"
            f"🆔 ID da Rota: `{route.id}`\n"
            f"📦 Total de Pacotes: *{len(items)}*\n\n" + f"💡 *A rota será otimizada quando você atribuir a um motorista*\n" + f"_(Use /enviarrota)_\n\n"
            f"� *Deseja extrair telefones do app SPX?*\n\n"
            f"⚠️ _Você precisará ter o celular conectado via USB com o app SPX aberto._",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
            parse_mode='Markdown'
        )
        return ConversationHandler.END
        
    except Exception as e:
        db.rollback()
        await update.message.reply_text(f"❌ Erro ao importar: {str(e)}")
        return ConversationHandler.END
    finally:
        db.close()


    db = SessionLocal()
    try:
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            await update.message.reply_text(
                "⛔ *Acesso Negado*\n\n"
                "Apenas gerentes podem enviar rotas para motoristas.",
                parse_mode='Markdown'
            )
            return
        args = context.args or []
        if len(args) == 2:
            try:
                route_id = int(args[0])
                driver_tid = int(args[1])
            except ValueError:
                await update.message.reply_text(
                    "❌ *IDs Inválidos*\n\n"
                    "Use: `/enviarrota <id_rota> <id_motorista>`",
                    parse_mode='Markdown'
                )
                return
            route = db.get(Route, route_id)
            if not route:
                await update.message.reply_text(
                    "❌ *Rota Não Encontrada*\n\n"
                    f"Não existe rota com ID `{route_id}`.",
                    parse_mode='Markdown'
                )
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
            route_name = route.name or f"Rota {route.id}"
            driver_name = driver.full_name or f"ID {driver_tid}"
            
            try:
                # Envia para o motorista
                await context.bot.send_message(
                    chat_id=driver_tid,
                    text=(
                        f"🎯 *Nova Rota Atribuída!*\n\n"
                        f"📦 Rota: *{route_name}*\n"
                        f"📊 Total de Pacotes: *{count}*\n"
                        f"🗺️ Mapa Interativo: [Clique Aqui]({link})\n\n"
                        f"💡 _Abra o mapa para ver todas as entregas e começar!_"
                    ),
                    parse_mode='Markdown'
                )
                
                # Envia também para o gerente (para rastreamento)
                await update.message.reply_text(
                    f"✅ *Rota Enviada com Sucesso!*\n\n"
                    f"📦 *Rota:* {route_name}\n"
                    f"👤 *Motorista:* {driver_name}\n"
                    f"📊 *Pacotes:* {count}\n\n"
                    f"🗺️ *Link de Rastreamento:*\n"
                    f"{link}\n\n"
                    f"💡 _Use este link para acompanhar em tempo real!_\n"
                    f"_Atualização automática a cada 30 segundos._",
                    parse_mode='Markdown'
                )
            except Exception:
                await update.message.reply_text(
                    "⚠️ *Erro ao Enviar*\n\n"
                    "Não consegui enviar a mensagem ao motorista.\n\n"
                    "Possíveis causas:\n"
                    "• O motorista ainda não iniciou conversa com o bot\n"
                    "• O ID do motorista está incorreto\n\n"
                    "💡 Peça ao motorista para enviar /start no bot.",
                    parse_mode='Markdown'
                )
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
        await update.message.reply_text(
            "📭 *Nenhuma Rota Disponível*\n\n"
            "Use /importar para criar uma nova rota primeiro!",
            parse_mode='Markdown'
        )
        return
    
    # Criar keyboard com botões de info e deletar
    keyboard = []
    for r in routes[:25]:
        route_name = r.name or 'Rota'
        keyboard.append([
            InlineKeyboardButton(text=f"📦 {route_name} (ID {r.id})", callback_data=f"sel_route:{r.id}"),
            InlineKeyboardButton(text="🗑️", callback_data=f"delete_route:{r.id}")
        ])
    
    await update.message.reply_text(
        "🚚 *Enviar Rota para Motorista*\n\n"
        "Selecione a rota que deseja atribuir:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
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
        await query.edit_message_text(
            "👥 *Nenhum Motorista Cadastrado*\n\n"
            "Use /cadastrardriver para adicionar motoristas primeiro!",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(text=f"👤 {(d.full_name or 'Sem nome')} (ID {d.telegram_user_id})",
                                       callback_data=f"sel_driver:{d.telegram_user_id}")]
                for d in drivers[:25]]
    await query.edit_message_text(
        f"🚚 *Rota Selecionada: ID {route_id}*\n\n"
        f"Agora escolha o motorista que receberá esta rota:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return SEND_SELECT_DRIVER


async def on_select_driver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    if not data.startswith("sel_driver:"):
        await query.answer()
        return
    
    driver_tid = int(data.split(":", 1)[1])
    route_id = context.user_data.get("send_route_id")
    
    # Responde IMEDIATAMENTE ao callback para evitar timeout
    await query.answer("Processando rota...")
    
    if not route_id:
        await query.edit_message_text(
            "❌ *Erro Interno*\n\n"
            "Rota não selecionada. Tente novamente com /enviarrota.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    db = SessionLocal()
    try:
        route = db.get(Route, int(route_id))
        if not route:
            await query.edit_message_text(
                "❌ *Rota Não Encontrada*\n\n"
                f"A rota ID `{route_id}` não existe mais.",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        driver = get_user_by_tid(db, driver_tid)
        if not driver:
            driver = User(telegram_user_id=driver_tid, full_name=None, role="driver")
            db.add(driver)
            db.flush()
        
        route.assigned_to_id = driver.id
        db.commit()
        
        # Informações básicas
        count = db.query(Package).filter(Package.route_id == route.id).count()
        route_name = route.name or f"Rota {route.id}"
        driver_name = driver.full_name or f"ID {driver_tid}"
        
        # Edita mensagem para mostrar progresso
        await query.edit_message_text(
            f"⏳ *Processando Rota...*\n\n"
            f"📦 *Rota:* {route_name}\n"
            f"👤 *Motorista:* {driver_name}\n"
            f"📊 *Pacotes:* {count}\n\n"
            f"🔄 _Otimizando sequência de entregas..._",
            parse_mode='Markdown'
        )
        
        # ==================== OTIMIZAÇÃO DE ROTA POR MOTORISTA ====================
        # Busca todos os pacotes da rota
        all_packages = db.query(Package).filter(Package.route_id == route.id).all()
        
        # Usa o endereço de casa do motorista (se configurado) ou coordenadas padrão
        start_lat = driver.home_latitude or DEPOT_LAT
        start_lon = driver.home_longitude or DEPOT_LON
        
        # Otimiza a ordem usando TSP com o ponto de partida do motorista
        optimized_count = optimize_route_packages(db, all_packages, start_lat, start_lon)
        
        # Mensagem sobre otimização
        if driver.home_latitude and driver.home_longitude:
            opt_msg = f"\n🎯 *Rota otimizada* a partir da casa do motorista!"
        else:
            opt_msg = f"\n⚠️ _Motorista sem endereço cadastrado. Use /configurarcasa._"
        # ========================================================================
        
        link = f"{BASE_URL}/map/{route.id}/{driver_tid}"
        
        try:
            await context.bot.send_message(
                chat_id=driver_tid,
                text=(
                    f"🎯 *Nova Rota Atribuída!*\n\n"
                    f"📦 Rota: *{route_name}*\n"
                    f"📊 Total de Pacotes: *{count}*\n"
                    f"🗺️ Mapa Interativo: [Clique Aqui]({link})\n"
                    f"{opt_msg}\n\n"
                    f"💡 _Abra o mapa para ver todas as entregas e começar!_"
                ),
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            await query.edit_message_text(
                f"✅ *Rota Enviada com Sucesso!*\n\n"
                f"📦 *Rota:* {route_name}\n"
                f"👤 *Motorista:* {driver_name}\n"
                f"📊 *Pacotes:* {count}\n"
                f"{opt_msg}\n\n"
                f"🗺️ *Link de Rastreamento:*\n"
                f"{link}\n\n"
                f"💡 _Use este link para acompanhar em tempo real!_",
                parse_mode='Markdown'
            )
        except Exception:
            await query.edit_message_text(
                "⚠️ *Erro ao Enviar*\n\n"
                "Não consegui enviar a mensagem ao motorista.\n\n"
                "Possíveis causas:\n"
                "• O motorista ainda não iniciou conversa com o bot\n"
                "• O ID do motorista está incorreto\n\n"
                "💡 Peça ao motorista para enviar /start no bot.",
                parse_mode='Markdown'
            )
    finally:
        db.close()
    context.user_data.pop("send_route_id", None)
    return ConversationHandler.END


async def on_delete_driver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para excluir motorista"""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    if not data.startswith("delete_driver:"):
        return
    
    driver_id = int(data.split(":", 1)[1])
    
    db = SessionLocal()
    try:
        # Verifica permissão
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            await query.answer("⛔ Apenas gerentes podem excluir motoristas!", show_alert=True)
            return
        
        # Busca motorista
        driver = db.get(User, driver_id)
        if not driver:
            await query.answer("❌ Motorista não encontrado!", show_alert=True)
            return
        
        driver_name = driver.full_name or f"ID {driver.telegram_user_id}"
        
        # Verifica se tem rotas ativas
        active_routes = db.query(Route).filter(Route.assigned_to_id == driver_id).count()
        
        if active_routes > 0:
            await query.answer(
                f"⚠️ Este motorista tem {active_routes} rota(s) ativa(s)!\n"
                f"As rotas serão desvinculadas.",
                show_alert=True
            )
            # Desvincula rotas
            db.query(Route).filter(Route.assigned_to_id == driver_id).update({"assigned_to_id": None})
        
        # Deleta motorista
        db.delete(driver)
        db.commit()
        
        await query.edit_message_text(
            f"✅ *Motorista Excluído!*\n\n"
            f"👤 {driver_name}\n"
            f"🗑️ Foi removido do sistema.\n\n"
            f"Use /drivers para ver a lista atualizada.",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await query.answer(f"❌ Erro ao excluir: {str(e)}", show_alert=True)
    finally:
        db.close()


async def on_delete_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para excluir rota"""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    if not data.startswith("delete_route:"):
        return
    
    route_id = int(data.split(":", 1)[1])
    
    db = SessionLocal()
    try:
        # Verifica permissão
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            await query.answer("⛔ Apenas gerentes podem excluir rotas!", show_alert=True)
            return
        
        # Busca rota
        route = db.get(Route, route_id)
        if not route:
            await query.answer("❌ Rota não encontrada!", show_alert=True)
            return
        
        route_name = route.name or f"Rota {route.id}"
        
        # Conta pacotes e entregas
        package_count = db.query(Package).filter(Package.route_id == route_id).count()
        delivered_count = db.query(Package).filter(
            Package.route_id == route_id,
            Package.status == "delivered"
        ).count()
        
        if package_count > 0:
            await query.answer(
                f"⚠️ Esta rota tem {package_count} pacote(s)!\n"
                f"({delivered_count} entregue(s))\n"
                f"Todos serão deletados.",
                show_alert=True
            )
        
        # Deleta rota (cascade deleta pacotes e provas)
        db.delete(route)
        db.commit()
        
        await query.edit_message_text(
            f"✅ *Rota Excluída!*\n\n"
            f"📦 {route_name}\n"
            f"🗑️ {package_count} pacote(s) removido(s)\n\n"
            f"Use /enviarrota para ver a lista atualizada.",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await query.answer(f"❌ Erro ao excluir: {str(e)}", show_alert=True)
    finally:
        db.close()


# Cadastro/listagem de entregadores
async def add_driver_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            await update.message.reply_text(
                "⛔ *Acesso Negado*\n\n"
                "Apenas gerentes podem cadastrar motoristas.",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
    finally:
        db.close()
    await update.message.reply_text(
        "👤 *Cadastrar Novo Motorista*\n\n"
        "Informe o *Telegram User ID* do motorista.\n\n"
        "💡 _O motorista pode descobrir seu ID usando /meu\\_id_",
        parse_mode='Markdown'
    )
    return ADD_DRIVER_TID


async def add_driver_tid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip()
    try:
        tid = int(txt)
    except ValueError:
        await update.message.reply_text(
            "❌ *ID Inválido*\n\n"
            "Digite apenas números.\n\n"
            "Exemplo: `123456789`",
            parse_mode='Markdown'
        )
        return ADD_DRIVER_TID
    context.user_data["new_driver_tid"] = tid
    await update.message.reply_text(
        "✏️ *Quase Lá!*\n\n"
        "Agora informe o *nome completo* do motorista.",
        parse_mode='Markdown'
    )
    return ADD_DRIVER_NAME


async def add_driver_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text(
            "❌ *Nome Vazio*\n\n"
            "Por favor, informe um nome válido.",
            parse_mode='Markdown'
        )
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
    await update.message.reply_text(
        f"✅ *Motorista Cadastrado!*\n\n"
        f"👤 *Nome:* {name}\n"
        f"🆔 *ID:* `{tid}`\n\n"
        f"💡 _Você já pode enviar rotas com /enviarrota_",
        parse_mode='Markdown'
    )
    return ConversationHandler.END


async def list_drivers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = SessionLocal()
    try:
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            await update.message.reply_text(
                "⛔ *Acesso Negado*\n\n"
                "Apenas gerentes podem listar motoristas.",
                parse_mode='Markdown'
            )
            return
        drivers = db.query(User).filter(User.role == "driver").order_by(User.id.desc()).all()
    finally:
        db.close()
    if not drivers:
        await update.message.reply_text(
            "👥 *Nenhum Motorista Cadastrado*\n\n"
            "Use /cadastrardriver para adicionar o primeiro motorista!",
            parse_mode='Markdown'
        )
        return
    
    # Cria botões inline com opção de excluir e rastrear
    buttons = []
    for d in drivers:
        name = d.full_name or 'Sem nome'
        tid = d.telegram_user_id
        
        # Verifica se motorista tem rota ativa
        active_route = db.query(Route).filter(Route.assigned_to_id == d.id).first()
        
        if active_route:
            # Motorista em rota - mostra botão de rastreamento
            status_icon = "🟢"
            route_name = active_route.name or f"Rota {active_route.id}"
            
            buttons.append([
                InlineKeyboardButton(
                    f"{status_icon} {name} - {route_name}",
                    callback_data=f"driver_info:{d.id}"
                ),
                InlineKeyboardButton(
                    "🗺️",
                    callback_data=f"track_route:{active_route.id}"
                ),
                InlineKeyboardButton(
                    "�️",
                    callback_data=f"delete_driver:{d.id}"
                )
            ])
        else:
            # Motorista disponível - sem rastreamento
            status_icon = "⚪"
            
            buttons.append([
                InlineKeyboardButton(
                    f"{status_icon} {name} (ID: {tid})",
                    callback_data=f"driver_info:{d.id}"
                ),
                InlineKeyboardButton(
                    "🗑️",
                    callback_data=f"delete_driver:{d.id}"
                )
            ])
    
    keyboard = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(
        f"👥 *Lista de Motoristas* \\({len(drivers)}\\)\n\n"
        f"� Em rota  \\|  ⚪ Disponível\n"
        f"�️ Rastrear  \\|  🗑️ Excluir",
        reply_markup=keyboard,
        parse_mode='MarkdownV2'
    )


# Fluxo de entrega
async def deliver_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if len(args) != 1:
        await update.message.reply_text(
            "❌ *Comando Incorreto*\n\n"
            "Uso: `/entregar <id_pacote>`\n\n"
            "💡 _Use o botão 'Entregar' no mapa interativo!_",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    try:
        package_id = int(args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ *ID Inválido*\n\n"
            "O ID do pacote deve ser um número.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    context.user_data["deliver_package_id"] = package_id
    keyboard = ReplyKeyboardMarkup([["Unitário", "Em massa"]], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        "📦 Como será esta entrega?",
        reply_markup=keyboard
    )
    return MODE_SELECT


async def on_mode_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = (update.message.text or "").strip().lower()
    if choice.startswith("unit"):
        # Fluxo unitário (original)
        await update.message.reply_text(
            "📸 *Comprovante de Entrega - Passo 1/4*\n\n"
            "Envie a *Foto 1* (recebedor ou pacote).",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='Markdown'
        )
        return PHOTO1
    elif choice.startswith("em m") or choice == "em massa":
        # Fluxo em massa: coleta várias fotos de pacotes antes de prosseguir
        context.user_data["mass_mode"] = True
        context.user_data["mass_photos"] = []
        kb = ReplyKeyboardMarkup([["Próximo"]], resize_keyboard=True)
        await update.message.reply_text(
            "📸 *Entrega em massa*\n\n"
            "Envie a foto do pacote que vai ser entregue.\n\n"
            "Quando terminar, toque em *Próximo* para continuar as provas de entrega.",
            reply_markup=kb,
            parse_mode='Markdown'
        )
        return MASS_PHOTOS
    else:
        await update.message.reply_text("Escolha uma opção válida: Unitário ou Em massa.")
        return MODE_SELECT


async def mass_photos_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        photo = update.message.photo[-1]
        photos = context.user_data.get("mass_photos", [])
        photos.append(photo.file_id)
        context.user_data["mass_photos"] = photos
        kb = ReplyKeyboardMarkup([["Próximo"]], resize_keyboard=True)
        await update.message.reply_text(
            f"✅ Foto salva ({len(photos)}). Envie outra foto de pacote ou toque em *Próximo*.",
            reply_markup=kb,
            parse_mode='Markdown'
        )
        return MASS_PHOTOS
    # Caso o usuário envie texto enquanto está nesse estado
    text = (update.message.text or "").strip().lower()
    if text == "próximo" or text == "proximo":
        # Prossegue para foto do local (equivalente ao Passo 2)
        await update.message.reply_text(
            "📸 *Comprovante de Entrega - Passo 2/5*\n\n"
            "Agora envie a *foto do local da entrega* (porta, fachada ou recebedor).",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='Markdown'
        )
        return PHOTO2
    else:
        kb = ReplyKeyboardMarkup([["Próximo"]], resize_keyboard=True)
        await update.message.reply_text(
            "Envie uma foto do pacote ou toque em *Próximo* para continuar.",
            reply_markup=kb,
            parse_mode='Markdown'
        )
        return MASS_PHOTOS


async def photo1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text(
            "⚠️ *Foto Necessária*\n\n"
            "Por favor, envie uma foto válida.",
            parse_mode='Markdown'
        )
        return PHOTO1
    # Não baixa arquivo. Guarda apenas o file_id do Telegram
    photo = update.message.photo[-1]
    context.user_data["photo1_file_id"] = photo.file_id
    await update.message.reply_text(
        "📸 *Comprovante de Entrega - Passo 2/5*\n\n"
        "Agora envie a *segunda foto do local da entrega* (porta, fachada ou recebedor).\n\n"
        "_Dica: Mostre o contexto da entrega para comprovar o local._",
        parse_mode='Markdown'
    )
    return PHOTO2


async def photo2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text(
            "⚠️ *Foto Necessária*\n\n"
            "Por favor, envie uma foto válida.",
            parse_mode='Markdown'
        )
        return PHOTO2
    # Não baixa arquivo. Guarda apenas o file_id do Telegram
    photo = update.message.photo[-1]
    context.user_data["photo2_file_id"] = photo.file_id
    await update.message.reply_text(
        "✏️ *Comprovante de Entrega - Passo 3/5*\n\n"
        "Informe o *nome completo* de quem recebeu o pacote.",
        parse_mode='Markdown'
    )
    return NAME


async def recv_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text(
            "❌ *Nome Vazio*\n\n"
            "Por favor, informe o nome completo de quem recebeu.",
            parse_mode='Markdown'
        )
        return NAME
    context.user_data["receiver_name"] = text
    await update.message.reply_text(
        "🆔 *Comprovante de Entrega - Passo 4/5*\n\n"
        "Informe o *CPF* ou *RG* de quem recebeu.\n\n"
        "💡 _Se a pessoa não informou o documento, digite: sem documento_",
        parse_mode='Markdown'
    )
    return DOC


async def recv_doc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    context.user_data["receiver_document"] = text or "sem documento"
    kb = ReplyKeyboardMarkup([["⏭️ Pular"]], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text(
        "📝 *Comprovante de Entrega - Passo 5/5*\n\n"
        "Tem alguma *observação* sobre esta entrega?\n"
        "_(Exemplo: porteiro recebeu, deixado na portaria, etc)_\n\n"
        "💡 Ou pressione *'Pular'* para finalizar.",
        reply_markup=kb,
        parse_mode='Markdown'
    )
    return NOTES


async def recv_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text.lower() == "pular" or text.startswith("⏭️"):
        text = None
    context.user_data["notes"] = text
    return await finalize_delivery(update, context)


async def finalize_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pkg_ids = context.user_data.get("deliver_package_ids")
    pkg_id = context.user_data.get("deliver_package_id")
    if not pkg_id and not pkg_ids:
        await update.message.reply_text(
            "❌ *Erro Interno*\n\n"
            "Não foi possível identificar o pacote.\n\n"
            "Use /entregar novamente.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    db = SessionLocal()
    try:
        driver = get_user_by_tid(db, update.effective_user.id)
        # Persistimos ao menos a primeira foto de pacote (unitário ou em massa) + foto do local
        p1_for_db = context.user_data.get("photo1_file_id")
        mass_list = context.user_data.get("mass_photos") or []
        if not p1_for_db and mass_list:
            p1_for_db = mass_list[0]

        route_id = None
        delivered_ids: list[int] = []
        delivered_codes: list[str] = []
        primary_addr: str | None = None
        primary_neighborhood: str | None = None
        receiver_name_val = context.user_data.get("receiver_name")
        receiver_document_val = context.user_data.get("receiver_document")
        notes_val = context.user_data.get("notes")

        if pkg_ids:
            # Entrega em grupo
            packages = db.query(Package).filter(Package.id.in_(pkg_ids)).all()
            if not packages:
                await update.message.reply_text(
                    "❌ *Pacotes Não Encontrados*",
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
            route_id = packages[0].route_id if packages else None
            primary_addr = packages[0].address
            primary_neighborhood = packages[0].neighborhood
            for p in packages:
                proof = DeliveryProof(
                    package_id=p.id,
                    driver_id=driver.id if driver else None,
                    receiver_name=receiver_name_val,
                    receiver_document=receiver_document_val,
                    notes=notes_val,
                    photo1_path=p1_for_db,
                    photo2_path=context.user_data.get("photo2_file_id"),
                )
                db.add(proof)
                p.status = "delivered"
                delivered_ids.append(p.id)
                try:
                    delivered_codes.append(p.tracking_code)
                except Exception:
                    pass
            db.commit()
        else:
            # Entrega unitária
            package = db.get(Package, int(pkg_id))
            if not package:
                await update.message.reply_text(
                    "❌ *Pacote Não Encontrado*\n\n"
                    f"O pacote ID `{pkg_id}` não existe.",
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
            route_id = package.route_id
            primary_addr = package.address
            primary_neighborhood = package.neighborhood
            proof = DeliveryProof(
                package_id=package.id,
                driver_id=driver.id if driver else None,
                receiver_name=receiver_name_val,
                receiver_document=receiver_document_val,
                notes=notes_val,
                photo1_path=p1_for_db,
                photo2_path=context.user_data.get("photo2_file_id"),
            )
            db.add(proof)
            package.status = "delivered"
            delivered_ids = [package.id]
            try:
                delivered_codes = [package.tracking_code]
            except Exception:
                delivered_codes = []
            db.commit()

    finally:
        db.close()

    # Notificar managers OU canal configurado do motorista
    try:
        db2 = SessionLocal()
        # Recarrega driver e, se necessário, a rota
        driver = get_user_by_tid(db2, update.effective_user.id)
        # Captura route_id e nome da rota
        route_name = None
        if route_id is not None:
            try:
                route_obj = db2.query(Route).filter(Route.id == route_id).first()
                route_name = route_obj.name if route_obj and route_obj.name else f"Rota {route_id}"
            except Exception:
                route_name = f"Rota {route_id}"
    finally:
        db2.close()
    
    if driver:
        receiver_name = context.user_data.get('receiver_name') or '-'
        receiver_doc = context.user_data.get('receiver_document') or '-'
        notes = context.user_data.get('notes') or '-'
        driver_name = driver.full_name or f"ID {driver.telegram_user_id}"
        
        # Calcula progresso da rota
        db_progress = SessionLocal()
        try:
            if route_id is not None:
                total_packages = db_progress.query(Package).filter(Package.route_id == route_id).count()
                delivered_packages = db_progress.query(Package).filter(
                    Package.route_id == route_id,
                    Package.status == "delivered"
                ).count()
            else:
                total_packages = 0
                delivered_packages = 0
            remaining_packages = max(0, total_packages - delivered_packages)
            route_name = route_name or (f"Rota {route_id}" if route_id is not None else "Rota")
        finally:
            db_progress.close()
        
        # Mensagem formatada para o canal (sem asteriscos, mais limpo)
        # Monta resumo: suporta múltiplos pacotes
        if pkg_ids:
            codes = [c for c in delivered_codes if c]
            codes_list = ", ".join(codes)  # Todos os códigos sem abreviação
            summary = (
                f"✅ Entregas Concluídas!\n\n"
                f"Motorista: {driver_name}\n"
                f"Pacotes: {len(delivered_ids)}\n"
                f"Códigos: {codes_list}\n"
                f"Endereço: {primary_addr or '-'}\n"
                f"Bairro: {primary_neighborhood or '-'}\n"
                f"Recebedor: {receiver_name}\n"
                f"Documento: {receiver_doc}\n"
                f"Observações: {notes}\n"
                f"Data/Hora: {datetime.now().strftime('%d/%m/%Y às %H:%M')}"
            )
        else:
            summary = (
                f"✅ Entrega Concluída!\n\n"
                f"Motorista: {driver_name}\n"
                f"Pacote: {(delivered_codes[0] if delivered_codes else '-') }\n"
                f"Endereço: {primary_addr or '-'}\n"
                f"Bairro: {primary_neighborhood or '-'}\n"
                f"Recebedor: {receiver_name}\n"
                f"Documento: {receiver_doc}\n"
                f"Observações: {notes}\n"
                f"Data/Hora: {datetime.now().strftime('%d/%m/%Y às %H:%M')}"
            )
        
        # Mensagem de progresso
        progress_message = (
            f"📊 Status da Rota: {route_name}\n\n"
            f"✅ Entregues: {delivered_packages}\n"
            f"⏳ Pendentes: {remaining_packages}\n"
            f"📦 Total: {total_packages}\n\n"
            f"Progresso: {(delivered_packages/total_packages*100 if total_packages > 0 else 0):.0f}%"
        )
        
        # Verifica se motorista tem canal configurado
        if driver.channel_id:
            # Envia para o CANAL
            try:
                # Envia informações
                await context.bot.send_message(
                    chat_id=driver.channel_id,
                    text=summary
                )
                
                # Envia fotos como grupo/media
                p1 = context.user_data.get("photo1_file_id")
                p2 = context.user_data.get("photo2_file_id")
                mass_list = context.user_data.get("mass_photos") or []
                
                # Prioriza enviar fotos em massa (se houver)
                if mass_list:
                    # Envia em grupos de até 10
                    batch = []
                    for idx, fid in enumerate(mass_list, start=1):
                        cap = "Pacote"
                        batch.append(InputMediaPhoto(fid, caption=cap if idx == 1 else None))
                        if len(batch) == 10:
                            try:
                                await context.bot.send_media_group(chat_id=driver.channel_id, media=batch)
                            except Exception:
                                for item in batch:
                                    try:
                                        await context.bot.send_photo(chat_id=driver.channel_id, photo=item.media, caption=item.caption)
                                    except Exception:
                                        pass
                            batch = []
                    if batch:
                        try:
                            await context.bot.send_media_group(chat_id=driver.channel_id, media=batch)
                        except Exception:
                            for item in batch:
                                try:
                                    await context.bot.send_photo(chat_id=driver.channel_id, photo=item.media, caption=item.caption)
                                except Exception:
                                    pass
                    # Envia foto do local (se houver)
                    if p2:
                        try:
                            await context.bot.send_photo(chat_id=driver.channel_id, photo=p2, caption="Local/Porta")
                        except Exception:
                            pass
                else:
                    # Fluxo unitário normal
                    if p1 and p2:
                        media = [
                            InputMediaPhoto(p1, caption="Foto 1 - Recebedor/Pacote"),
                            InputMediaPhoto(p2, caption="Foto 2 - Local/Porta")
                        ]
                        try:
                            await context.bot.send_media_group(chat_id=driver.channel_id, media=media)
                        except Exception:
                            if p1:
                                try:
                                    await context.bot.send_photo(chat_id=driver.channel_id, photo=p1, caption="Foto 1 - Recebedor/Pacote")
                                except Exception:
                                    pass
                            if p2:
                                try:
                                    await context.bot.send_photo(chat_id=driver.channel_id, photo=p2, caption="Foto 2 - Local/Porta")
                                except Exception:
                                    pass
                    else:
                        if p1:
                            try:
                                await context.bot.send_photo(chat_id=driver.channel_id, photo=p1, caption="Foto 1 - Recebedor/Pacote")
                            except Exception:
                                pass
                        if p2:
                            try:
                                await context.bot.send_photo(chat_id=driver.channel_id, photo=p2, caption="Foto 2 - Local/Porta")
                            except Exception:
                                pass
                
                # Envia progresso após as fotos
                await context.bot.send_message(
                    chat_id=driver.channel_id,
                    text=progress_message
                )
                
            except Exception as e:
                # Se falhar, envia para os managers como fallback
                await notify_managers(f"⚠️ Erro ao enviar para canal: {str(e)}\n\n{summary}", context)
                
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
                                await context.bot.send_photo(chat_id=m.telegram_user_id, photo=p1, caption="Foto 1")
                            except Exception:
                                pass
                        if p2:
                            try:
                                await context.bot.send_photo(chat_id=m.telegram_user_id, photo=p2, caption="Foto 2")
                            except Exception:
                                pass
        else:
            # Sem canal configurado - envia para os MANAGERS (comportamento original)
            await notify_managers(summary, context)
            
            p1 = context.user_data.get("photo1_file_id")
            p2 = context.user_data.get("photo2_file_id")
            mass_list = context.user_data.get("mass_photos") or []
            if p1 or p2:
                dbm = SessionLocal()
                try:
                    managers = dbm.query(User).filter(User.role == "manager").all()
                finally:
                    dbm.close()
                for m in managers:
                    if mass_list:
                        # Envia mass photos em lotes
                        batch = []
                        for idx, fid in enumerate(mass_list, start=1):
                            cap = "Pacote"
                            batch.append(InputMediaPhoto(fid, caption=cap if idx == 1 else None))
                            if len(batch) == 10:
                                try:
                                    await context.bot.send_media_group(chat_id=m.telegram_user_id, media=batch)
                                except Exception:
                                    for item in batch:
                                        try:
                                            await context.bot.send_photo(chat_id=m.telegram_user_id, photo=item.media, caption=item.caption)
                                        except Exception:
                                            pass
                                batch = []
                        if batch:
                            try:
                                await context.bot.send_media_group(chat_id=m.telegram_user_id, media=batch)
                            except Exception:
                                for item in batch:
                                    try:
                                        await context.bot.send_photo(chat_id=m.telegram_user_id, photo=item.media, caption=item.caption)
                                    except Exception:
                                        pass
                        if p2:
                            try:
                                await context.bot.send_photo(chat_id=m.telegram_user_id, photo=p2, caption="Local/Porta")
                            except Exception:
                                pass
                    else:
                        # Fluxo unitário
                        if p1 and p2:
                            media = [
                                InputMediaPhoto(p1, caption="Foto 1 - Recebedor/Pacote"),
                                InputMediaPhoto(p2, caption="Foto 2 - Local/Porta")
                            ]
                            try:
                                await context.bot.send_media_group(chat_id=m.telegram_user_id, media=media)
                            except Exception:
                                # Se falhar, envia separadas
                                if p1:
                                    try:
                                        await context.bot.send_photo(chat_id=m.telegram_user_id, photo=p1, caption="Foto 1 - Recebedor/Pacote")
                                    except Exception:
                                        pass
                                if p2:
                                    try:
                                        await context.bot.send_photo(chat_id=m.telegram_user_id, photo=p2, caption="Foto 2 - Local/Porta")
                                    except Exception:
                                        pass
                        else:
                            if p1:
                                try:
                                    await context.bot.send_photo(chat_id=m.telegram_user_id, photo=p1, caption="Foto 1 - Recebedor/Pacote")
                                except Exception:
                                    pass
                            if p2:
                                try:
                                    await context.bot.send_photo(chat_id=m.telegram_user_id, photo=p2, caption="Foto 2 - Local/Porta")
                                except Exception:
                                    pass
                
                # Envia progresso após as fotos para os managers
                dbm2 = SessionLocal()
                try:
                    managers = dbm2.query(User).filter(User.role == "manager").all()
                finally:
                    dbm2.close()
                for m in managers:
                    try:
                        await context.bot.send_message(
                            chat_id=m.telegram_user_id,
                            text=progress_message
                        )
                    except Exception:
                        pass

    # Monta link do mapa interativo para continuar a rota
    map_url = None
    try:
        if route_id is not None and driver and getattr(driver, "telegram_user_id", None):
            map_url = f"{BASE_URL}/map/{route_id}/{driver.telegram_user_id}"
    except Exception:
        map_url = None

    final_msg = (
        "✅ *Entrega Registrada!*\n\n"
        f"📦 O pacote foi marcado como entregue.\n"
        f"👔 Os gerentes foram notificados.\n\n"
        + (f"🗺️ Abra o mapa para a próxima entrega:\n{map_url}\n\n" if map_url else "")
        + "💡 _Continue para a próxima entrega no mapa!_"
    )
    await update.message.reply_text(
        final_msg,
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
    
    # Botão rápido (opcional) para abrir o mapa
    if map_url:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="🗺️ Abrir mapa interativo",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Abrir mapa", url=map_url)]
                ])
            )
        except Exception:
            pass
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "🚫 *Operação Cancelada*\n\n"
        "Nenhuma alteração foi salva.",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
    return ConversationHandler.END


# ===== FINANCIAL SYSTEM (MANAGERS ONLY) =====

async def fin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o fluxo de registro financeiro do dia (APENAS MANAGERS)"""
    user = update.effective_user
    db = SessionLocal()
    try:
        db_user = db.query(User).filter(User.telegram_user_id == user.id).first()
        if not db_user or db_user.role != "manager":
            await update.message.reply_text("⛔ Apenas managers podem registrar dados financeiros.")
            return ConversationHandler.END
        
        context.user_data['fin_salaries'] = []
        today = datetime.now().strftime("%d/%m/%Y")
        await update.message.reply_text(
            f"📊 *Registro Financeiro - {today}*\n\n"
            f"Vamos registrar os dados do dia!\n\n"
            f"*1/8* - Quantos KM foram rodados hoje?\n"
            f"_(Digite o total de KM ou /cancel para cancelar)_",
            parse_mode='Markdown'
        )
        return FIN_KM
    finally:
        db.close()


async def fin_km(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe KM rodados"""
    try:
        km = float(update.message.text.replace(',', '.'))
        if km < 0:
            raise ValueError
        context.user_data['fin_km'] = km
        
        keyboard = [['Sim', 'Não']]
        await update.message.reply_text(
            f"✅ {km} KM registrados.\n\n"
            f"*2/8* - Houve abastecimento hoje?",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
            parse_mode='Markdown'
        )
        return FIN_FUEL_YN
    except ValueError:
        await update.message.reply_text("❌ Valor inválido. Digite apenas números (ex: 150 ou 150.5):")
        return FIN_KM


async def fin_fuel_yn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pergunta se houve abastecimento"""
    resp = update.message.text.strip().lower()
    if resp in ['sim', 's', 'yes']:
        keyboard = [['Etanol', 'GNV']]
        await update.message.reply_text(
            "*3/8* - Qual tipo de combustível?",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
            parse_mode='Markdown'
        )
        return FIN_FUEL_TYPE
    else:
        context.user_data['fin_fuel'] = None
        await update.message.reply_text(
            "✅ Sem abastecimento registrado.\n\n"
            "*4/8* - Qual foi o ganho total com rotas hoje? (R$)\n"
            "_(Digite o valor ou 0 se não houver)_",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='Markdown'
        )
        return FIN_INCOME


async def fin_fuel_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe tipo de combustível"""
    fuel_type = update.message.text.strip().upper()
    if fuel_type not in ['ETANOL', 'GNV']:
        await update.message.reply_text("❌ Escolha Etanol ou GNV:")
        return FIN_FUEL_TYPE
    
    context.user_data['fin_fuel_type'] = fuel_type
    await update.message.reply_text(
        f"*3.1/8* - Quantos litros/m³ de {fuel_type}?",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
    return FIN_FUEL_LITERS


async def fin_fuel_liters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe litros de combustível"""
    try:
        liters = float(update.message.text.replace(',', '.'))
        if liters <= 0:
            raise ValueError
        context.user_data['fin_fuel_liters'] = liters
        
        fuel_type = context.user_data['fin_fuel_type']
        await update.message.reply_text(
            f"*3.2/8* - Qual foi o valor total pago pelos {liters} {'litros' if fuel_type == 'ETANOL' else 'm³'} de {fuel_type}? (R$)",
            parse_mode='Markdown'
        )
        return FIN_FUEL_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ Valor inválido. Digite apenas números:")
        return FIN_FUEL_LITERS


async def fin_fuel_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe valor pago no combustível"""
    try:
        amount = float(update.message.text.replace(',', '.').replace('R$', '').strip())
        if amount <= 0:
            raise ValueError
        
        fuel_type = context.user_data['fin_fuel_type']
        liters = context.user_data['fin_fuel_liters']
        
        context.user_data['fin_fuel'] = {
            'type': fuel_type,
            'liters': liters,
            'amount': amount
        }
        
        await update.message.reply_text(
            f"✅ Abastecimento registrado:\n"
            f"• {fuel_type}: {liters} {'L' if fuel_type == 'ETANOL' else 'm³'} por R$ {amount:.2f}\n\n"
            f"*4/8* - Qual foi o ganho total com rotas hoje? (R$)\n"
            "_(Digite o valor ou 0 se não houver)_",
            parse_mode='Markdown'
        )
        return FIN_INCOME
    except ValueError:
        await update.message.reply_text("❌ Valor inválido. Digite apenas números (ex: 150.00):")
        return FIN_FUEL_AMOUNT


async def fin_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe ganho total do dia"""
    try:
        income = float(update.message.text.replace(',', '.').replace('R$', '').strip())
        if income < 0:
            raise ValueError
        context.user_data['fin_income'] = income
        
        keyboard = [['Sim', 'Não']]
        await update.message.reply_text(
            f"✅ Ganho registrado: R$ {income:.2f}\n\n"
            f"*5/8* - Houve pagamento de salários hoje?",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
            parse_mode='Markdown'
        )
        return FIN_SALARY_YN
    except ValueError:
        await update.message.reply_text("❌ Valor inválido. Digite apenas números (ex: 500.00 ou 0):")
        return FIN_INCOME


async def fin_salary_yn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pergunta se houve pagamento de salários"""
    resp = update.message.text.strip().lower()
    if resp in ['sim', 's', 'yes']:
        await update.message.reply_text(
            "*5.1/8* - Nome do funcionário:",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='Markdown'
        )
        return FIN_SALARY_NAME
    else:
        await update.message.reply_text(
            "✅ Sem salários registrados.\n\n"
            "*6/8* - Outras despesas? (manutenção, pedágio, etc)\n"
            "_(Digite o valor total ou 0)_",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='Markdown'
        )
        return FIN_EXPENSES


async def fin_salary_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe nome do funcionário"""
    name = update.message.text.strip()
    context.user_data['fin_temp_salary_name'] = name
    await update.message.reply_text(
        f"*5.2/8* - Valor pago a {name}? (R$)",
        parse_mode='Markdown'
    )
    return FIN_SALARY_AMOUNT


async def fin_salary_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe valor do salário"""
    try:
        amount = float(update.message.text.replace(',', '.').replace('R$', '').strip())
        if amount <= 0:
            raise ValueError
        
        name = context.user_data['fin_temp_salary_name']
        context.user_data['fin_salaries'].append({'name': name, 'amount': amount})
        
        keyboard = [['Sim', 'Não']]
        await update.message.reply_text(
            f"✅ Salário registrado: {name} - R$ {amount:.2f}\n\n"
            f"*5.3/8* - Registrar mais algum salário?",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
            parse_mode='Markdown'
        )
        return FIN_SALARY_MORE
    except ValueError:
        await update.message.reply_text("❌ Valor inválido. Digite apenas números (ex: 1500.00):")
        return FIN_SALARY_AMOUNT


async def fin_salary_more(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pergunta se há mais salários"""
    resp = update.message.text.strip().lower()
    if resp in ['sim', 's', 'yes']:
        await update.message.reply_text(
            "*5.1/8* - Nome do funcionário:",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='Markdown'
        )
        return FIN_SALARY_NAME
    else:
        await update.message.reply_text(
            "*6/8* - Outras despesas? (manutenção, pedágio, etc)\n"
            "_(Digite o valor total ou 0)_",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='Markdown'
        )
        return FIN_EXPENSES


async def fin_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe outras despesas"""
    try:
        expenses = float(update.message.text.replace(',', '.').replace('R$', '').strip())
        if expenses < 0:
            raise ValueError
        context.user_data['fin_expenses'] = expenses
        
        await update.message.reply_text(
            f"*7/8* - Observações do dia? (opcional)\n"
            f"_(Digite suas observações ou /pular para pular)_",
            parse_mode='Markdown'
        )
        return FIN_NOTES
    except ValueError:
        await update.message.reply_text("❌ Valor inválido. Digite apenas números (ex: 50.00 ou 0):")
        return FIN_EXPENSES


async def fin_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe observações e finaliza"""
    notes = update.message.text.strip()
    if notes == '/pular':
        notes = ''
    
    context.user_data['fin_notes'] = notes
    
    # Salvar tudo no banco
    user = update.effective_user
    db = SessionLocal()
    try:
        today = datetime.now().date()
        
        # 1. Salvar KM
        km_total = context.user_data.get('fin_km', 0)
        if km_total > 0:
            mileage = Mileage(
                date=today,
                km_start=0,
                km_end=km_total,
                km_total=km_total,
                notes=notes or None,
                created_by=user.id
            )
            db.add(mileage)
        
        # 2. Salvar combustível
        fuel_data = context.user_data.get('fin_fuel')
        if fuel_data:
            expense_fuel = Expense(
                date=today,
                type='combustivel',
                description=f"{fuel_data['liters']} {'L' if fuel_data['type'] == 'ETANOL' else 'm³'} de {fuel_data['type']}",
                amount=fuel_data['amount'],
                fuel_type=fuel_data['type'],
                fuel_liters=fuel_data['liters'],
                created_by=user.id
            )
            db.add(expense_fuel)
        
        # 3. Salvar ganhos
        income_amount = context.user_data.get('fin_income', 0)
        if income_amount > 0:
            income = Income(
                date=today,
                description=f"Ganho total do dia",
                amount=income_amount,
                created_by=user.id
            )
            db.add(income)
        
        # 4. Salvar salários
        salaries = context.user_data.get('fin_salaries', [])
        for sal in salaries:
            expense_salary = Expense(
                date=today,
                type='salario',
                description=f"Salário de {sal['name']}",
                amount=sal['amount'],
                employee_name=sal['name'],
                created_by=user.id
            )
            db.add(expense_salary)
        
        # 5. Salvar outras despesas
        other_expenses = context.user_data.get('fin_expenses', 0)
        if other_expenses > 0:
            expense_other = Expense(
                date=today,
                type='outros',
                description='Despesas diversas (manutenção, pedágio, etc)',
                amount=other_expenses,
                created_by=user.id
            )
            db.add(expense_other)
        
        db.commit()
        
        # Montar resumo
        total_expenses = (
            (fuel_data['amount'] if fuel_data else 0) +
            sum(s['amount'] for s in salaries) +
            other_expenses
        )
        balance = income_amount - total_expenses
        
        summary = f"📊 *Registro Financeiro Concluído!*\n\n"
        summary += f"📅 Data: {today.strftime('%d/%m/%Y')}\n\n"
        summary += f"🚗 *KM Rodados:* {km_total} km\n\n"
        
        if fuel_data:
            summary += f"⛽ *Combustível:*\n"
            summary += f"  • {fuel_data['type']}: {fuel_data['liters']} {'L' if fuel_data['type'] == 'ETANOL' else 'm³'}\n"
            summary += f"  • Valor: R$ {fuel_data['amount']:.2f}\n\n"
        
        summary += f"💰 *Ganhos:* R$ {income_amount:.2f}\n\n"
        
        summary += f"💸 *Despesas:*\n"
        if fuel_data:
            summary += f"  • Combustível: R$ {fuel_data['amount']:.2f}\n"
        if salaries:
            summary += f"  • Salários: R$ {sum(s['amount'] for s in salaries):.2f}\n"
            for sal in salaries:
                summary += f"    - {sal['name']}: R$ {sal['amount']:.2f}\n"
        if other_expenses > 0:
            summary += f"  • Outros: R$ {other_expenses:.2f}\n"
        summary += f"  *Total:* R$ {total_expenses:.2f}\n\n"
        
        summary += f"📈 *Saldo:* R$ {balance:.2f}"
        if balance < 0:
            summary += " ⚠️ (Prejuízo)"
        
        if notes:
            summary += f"\n\n📝 *Observações:* {notes}"
        
        await update.message.reply_text(summary, parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
        
    except Exception as e:
        db.rollback()
        await update.message.reply_text(f"❌ Erro ao salvar dados: {str(e)}")
    finally:
        db.close()
        context.user_data.clear()
    
    return ConversationHandler.END


async def _post_init(application):
    """Executa após inicialização da Application: garante que webhook esteja desabilitado."""
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook removido no startup (drop_pending_updates=True)")
    except Exception as e:
        print(f"⚠️ Falha ao remover webhook no startup: {e}")


def build_application():
    if not BOT_TOKEN:
        raise RuntimeError("Defina a variável de ambiente BOT_TOKEN")
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(_post_init).build()
    
    # Configura todos os handlers
    setup_bot_handlers(app)
    
    return app


def setup_bot_handlers(app: Application):
    """
    Configura os handlers do bot sem iniciar polling.
    Usado para integração com webhook no unified_app.py
    """
    # Comandos básicos
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("meu_id", cmd_meu_id))
    app.add_handler(CommandHandler("relatorio", cmd_relatorio))
    app.add_handler(CommandHandler("cancelar", cmd_cancelar))

    import_conv = ConversationHandler(
        entry_points=[CommandHandler("importar", cmd_importar)],
        states={
            IMPORT_ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_route_name)],
            IMPORT_WAITING_FILE: [MessageHandler(filters.Document.ALL, handle_import_file)],
        },
        fallbacks=[CommandHandler("cancelar", cmd_cancelar)],
        name="import_conv",
        persistent=False,
    )
    app.add_handler(import_conv)

    app.add_handler(CommandHandler("rastrear", cmd_rastrear))
    app.add_handler(CallbackQueryHandler(on_track_route, pattern=r"^track_route:\d+$"))
    
    config_channel_conv = ConversationHandler(
        entry_points=[CommandHandler("configurarcanal", cmd_configurarcanal)],
        states={
            CONFIG_CHANNEL_SELECT_DRIVER: [CallbackQueryHandler(on_config_channel_select, pattern=r"^config_channel:\d+$")],
            CONFIG_CHANNEL_ENTER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_config_channel_enter_id)],
        },
        fallbacks=[CommandHandler("cancelar", cmd_cancelar)],
        name="config_channel_conv",
        persistent=False,
    )
    app.add_handler(config_channel_conv)
    
    config_home_conv = ConversationHandler(
        entry_points=[CommandHandler("configurarcasa", cmd_configurarcasa)],
        states={
            CONFIG_HOME_SELECT_DRIVER: [
                CallbackQueryHandler(on_config_home_select_driver, pattern=r"^config_home:\d+$")
            ],
            CONFIG_HOME_LOCATION: [
                MessageHandler(filters.LOCATION, on_config_home_location),
            ],
        },
        fallbacks=[CommandHandler("cancelar", cmd_cancelar)],
        name="config_home_conv",
        persistent=False,
    )
    app.add_handler(config_home_conv)
    
    # Conversation handler para enviar rota
    send_route_conv = ConversationHandler(
        entry_points=[CommandHandler("enviarrota", cmd_enviarrota)],
        states={
            SEND_SELECT_ROUTE: [CallbackQueryHandler(on_select_route, pattern=r"^sel_route:\d+$")],
            SEND_SELECT_DRIVER: [CallbackQueryHandler(on_select_driver, pattern=r"^sel_driver:\d+$")],
        },
        fallbacks=[CommandHandler("cancelar", cmd_cancelar)],
        name="send_route_conv",
        persistent=False,
    )
    app.add_handler(send_route_conv)
    
    app.add_handler(CallbackQueryHandler(on_select_route, pattern=r"^sel_route:\d+$"))
    app.add_handler(CallbackQueryHandler(on_select_driver, pattern=r"^sel_driver:\d+$"))
    app.add_handler(CallbackQueryHandler(on_delete_driver, pattern=r"^delete_driver:\d+$"))
    app.add_handler(CallbackQueryHandler(on_delete_route, pattern=r"^delete_route:\d+$"))

    delivery_conv = ConversationHandler(
        entry_points=[
            CommandHandler("entregar", deliver_start),
            CommandHandler("entrega", cmd_entrega),
            CommandHandler("iniciar", cmd_iniciar),
            CommandHandler("start", cmd_start),
        ],
        states={
            MODE_SELECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_mode_select)],
            MASS_PHOTOS: [
                MessageHandler(filters.PHOTO, mass_photos_add),
                MessageHandler(filters.TEXT & ~filters.COMMAND, mass_photos_add),
            ],
            PHOTO1: [MessageHandler(filters.PHOTO, photo1)],
            PHOTO2: [MessageHandler(filters.PHOTO, photo2)],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_name)],
            DOC: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_doc)],
            NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_notes)],
        },
        fallbacks=[CommandHandler("cancelar", cmd_cancelar)],
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
        fallbacks=[CommandHandler("cancelar", cmd_cancelar)],
        name="add_driver_conv",
        persistent=False,
    )
    app.add_handler(add_driver_conv)
    app.add_handler(CommandHandler("drivers", list_drivers))

    financial_conv = ConversationHandler(
        entry_points=[CommandHandler("registrardia", fin_start)],
        states={
            FIN_KM: [MessageHandler(filters.TEXT & ~filters.COMMAND, fin_km)],
            FIN_FUEL_YN: [MessageHandler(filters.TEXT & ~filters.COMMAND, fin_fuel_yn)],
            FIN_FUEL_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, fin_fuel_type)],
            FIN_FUEL_LITERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, fin_fuel_liters)],
            FIN_FUEL_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, fin_fuel_amount)],
            FIN_INCOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, fin_income)],
            FIN_SALARY_YN: [MessageHandler(filters.TEXT & ~filters.COMMAND, fin_salary_yn)],
            FIN_SALARY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, fin_salary_name)],
            FIN_SALARY_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, fin_salary_amount)],
            FIN_SALARY_MORE: [MessageHandler(filters.TEXT & ~filters.COMMAND, fin_salary_more)],
            FIN_EXPENSES: [MessageHandler(filters.TEXT & ~filters.COMMAND, fin_expenses)],
            FIN_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, fin_notes)],
        },
        fallbacks=[CommandHandler("cancelar", cmd_cancelar)],
        name="financial_conv",
        persistent=False,
    )
    app.add_handler(financial_conv)

    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            err = context.error
            print(f"[ERROR] {err}")
            err_text = str(err) if err is not None else ""
            conflict = "terminated by other getUpdates request" in err_text
            if conflict or not isinstance(update, Update):
                return
            if getattr(update, 'message', None):
                try:
                    await update.message.reply_text("⚠️ Ocorreu um erro temporário. Tente novamente em instantes.")
                except Exception:
                    pass
        except Exception:
            pass

    app.add_error_handler(on_error)


def main():
    app = build_application()
    print("Bot iniciado. Pressione Ctrl+C para sair.")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()


