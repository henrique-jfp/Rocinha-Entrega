import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from math import radians, sin, cos, sqrt, asin

import pandas as pd
try:
    from groq import Groq  # type: ignore
except Exception:
    Groq = None  # Import opcional; IA fica desativada se não disponível
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

from database import (
    SessionLocal, init_db, User, Route, Package, DeliveryProof,
    Expense, Income, Mileage, AIReport, LinkToken
)
from sqlalchemy import func, text  # ✅ FASE 4.1: Importa func para queries SQL

# Logging estruturado
from shared.logger import logger, log_bot_command


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
# Configurar Groq API (substitui Gemini)
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
groq_client = None
ai_model_name = None

if GROQ_API_KEY and Groq is not None:
    try:
        groq_client = Groq(api_key=GROQ_API_KEY)
        # Modelos disponíveis (nov 2024): llama-3.3-70b-versatile, llama-3.1-8b-instant, gemma2-9b-it
        ai_model_name = "llama-3.3-70b-versatile"  # Modelo mais recente e poderoso
        logger.info("Groq API inicializada com sucesso", extra={"model": ai_model_name})
    except Exception as e:
        logger.error("Erro ao inicializar Groq API", exc_info=True)
        logger.warning("Relatórios com IA estarão indisponíveis")
        groq_client = None
        ai_model_name = None
else:
    logger.warning("GROQ_API_KEY não configurada - relatórios com IA indisponíveis")
    
BOT_TOKEN = os.getenv("BOT_TOKEN", "")


# Estados de conversa
# IMPORT_ASK_NAME = 9  # ✅ REMOVIDO: Nome da rota agora é detectado automaticamente da coluna AT ID
IMPORT_WAITING_FILE = 10
IMPORT_CONFIRMING = 11  # ✅ FASE 3.2: Novo estado para confirmação de importação
PHOTO1, PHOTO2, NAME, DOC, NOTES = range(5)
# Novo fluxo: seleção de modo e fotos em massa
MODE_SELECT, MASS_PHOTOS = range(50, 52)
# Fluxo rápido de insucesso (falha na entrega)
FAIL_PHOTO, FAIL_NOTES = range(70, 72)
ADD_DRIVER_TID, ADD_DRIVER_NAME = range(10, 12)
SEND_SELECT_ROUTE, SEND_SELECT_DRIVER = range(20, 22)
CONFIG_CHANNEL_SELECT_DRIVER, CONFIG_CHANNEL_ENTER_ID = range(23, 25)
CONFIG_HOME_SELECT_DRIVER, CONFIG_HOME_LOCATION = range(26, 28)  # Estados para configurar casa

# ❌ REMOVIDO: Estados financeiros obsoletos (/registrardia foi substituído por automação)
# FIN_KM, FIN_FUEL_YN, FIN_FUEL_TYPE, FIN_FUEL_LITERS, FIN_FUEL_AMOUNT = range(30, 35)
# FIN_INCOME, FIN_SALARY_YN, FIN_SALARY_NAME, FIN_SALARY_AMOUNT, FIN_SALARY_MORE = range(35, 40)
# FIN_EXPENSE_CATEGORY, FIN_EXPENSE_AMOUNT, FIN_EXPENSE_MORE, FIN_EXPENSES, FIN_NOTES = range(40, 45)

# Estados para finalização de rota
FINALIZE_KM = 60
FINALIZE_EXTRA_EXPENSE_TYPE, FINALIZE_EXTRA_EXPENSE_VALUE, FINALIZE_EXTRA_EXPENSE_MORE = range(61, 64)
FINALIZE_EXTRA_INCOME_TYPE, FINALIZE_EXTRA_INCOME_VALUE = range(64, 66)

# ==================== CACHE SIMPLES PARA RELATÓRIOS ====================
# Cache em memória para evitar reprocessar dados que mudam pouco
# TTL de 5 minutos para estatísticas mensais
_report_cache = {}
_cache_ttl_seconds = 300  # 5 minutos

def _get_cached_monthly_stats(month: int, year: int):
    """Retorna estatísticas do cache se ainda válidas"""
    cache_key = f"monthly_stats_{month}_{year}"
    if cache_key in _report_cache:
        cached_data, cached_time = _report_cache[cache_key]
        age_seconds = (datetime.now() - cached_time).total_seconds()
        if age_seconds < _cache_ttl_seconds:
            logger.debug(f"Cache HIT para {cache_key} (idade: {age_seconds:.1f}s)")
            return cached_data
        else:
            logger.debug(f"Cache EXPIRED para {cache_key} (idade: {age_seconds:.1f}s)")
    return None

def _set_cached_monthly_stats(month: int, year: int, data):
    """Salva estatísticas no cache"""
    cache_key = f"monthly_stats_{month}_{year}"
    _report_cache[cache_key] = (data, datetime.now())
    logger.debug(f"Cache SET para {cache_key}")


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


def parse_import_dataframe(df: pd.DataFrame) -> tuple[list[dict], dict]:
    """
    Parse DataFrame de importação e retorna items + relatório de detecção.
    
    Returns:
        tuple: (items, detection_report)
        
        detection_report = {
            'route_name': 'AT20251015EM37',  # Nome detectado da rota
            'columns_found': {'tracking': 'SPX TN', 'address': 'Destination Address', ...},
            'columns_missing': ['phone', 'neighborhood'],
            'rows_total': 150,
            'rows_valid': 145,
            'rows_skipped': 5,
            'warnings': ['Linha 23: Coordenada inválida', ...]
        }
    """
    # ✅ FASE 3.1: RELATÓRIO DE DETECÇÃO
    report = {
        'route_name': None,
        'columns_found': {},
        'columns_missing': [],
        'rows_total': len(df),
        'rows_valid': 0,
        'rows_skipped': 0,
        'warnings': []
    }
    
    # ✅ DETECÇÃO AUTOMÁTICA DO NOME DA ROTA (coluna AT ID)
    col_route_id = _find_column(df, ["at id", "atid", "at_id", "route id", "route_id"])
    if col_route_id and len(df) > 0:
        # Pega o primeiro valor não vazio da coluna AT ID
        for idx, row in df.iterrows():
            route_name = str(row.get(col_route_id, "")).strip()
            if route_name and len(route_name) > 2:
                report['route_name'] = route_name
                report['columns_found']['route_id'] = col_route_id
                break
    
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

    # Registra colunas encontradas
    report['columns_found']['tracking'] = col_tracking
    if col_address:
        report['columns_found']['address'] = col_address
    else:
        report['columns_missing'].append('address')
    
    if col_lat:
        report['columns_found']['latitude'] = col_lat
    else:
        report['columns_missing'].append('latitude')
    
    if col_lng:
        report['columns_found']['longitude'] = col_lng
    else:
        report['columns_missing'].append('longitude')
    
    if col_bairro:
        report['columns_found']['neighborhood'] = col_bairro
    else:
        report['columns_missing'].append('neighborhood')

    items: list[dict] = []
    for idx, row in df.iterrows():
        try:
            tracking_code = str(row.get(col_tracking, "")).strip()
            if not tracking_code:
                report['rows_skipped'] += 1
                report['warnings'].append(f"Linha {idx+2}: Código de rastreio vazio")
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
                    # ✅ FASE 3.1: VALIDA COORDENADAS
                    if lat < -90 or lat > 90:
                        report['warnings'].append(f"Linha {idx+2}: Latitude inválida ({lat}) - código: {tracking_code}")
                        lat = None
                except (ValueError, TypeError) as e:
                    logger.warning(
                        f"Não foi possível converter latitude: {row.get(col_lat)}",
                        extra={"tracking_code": tracking_code, "error": str(e)}
                    )
                    report['warnings'].append(f"Linha {idx+2}: Latitude não numérica - código: {tracking_code}")
                    lat = None
            if col_lng and pd.notna(row.get(col_lng)):
                try:
                    lng = float(row[col_lng])
                    # ✅ FASE 3.1: VALIDA COORDENADAS
                    if lng < -180 or lng > 180:
                        report['warnings'].append(f"Linha {idx+2}: Longitude inválida ({lng}) - código: {tracking_code}")
                        lng = None
                except (ValueError, TypeError) as e:
                    logger.warning(
                        f"Não foi possível converter longitude: {row.get(col_lng)}",
                        extra={"tracking_code": tracking_code, "error": str(e)}
                    )
                    report['warnings'].append(f"Linha {idx+2}: Longitude não numérica - código: {tracking_code}")
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
            report['rows_valid'] += 1
            
        except Exception as e:
            report['rows_skipped'] += 1
            report['warnings'].append(f"Linha {idx+2}: Erro ao processar - {str(e)}")
    
    return items, report


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
        except Exception as e:
            logger.error(
                f"Falha ao enviar notificação para gerente {m.telegram_user_id}",
                exc_info=True,
                extra={"manager_id": m.telegram_user_id, "error": str(e)}
            )


class DeliveryLinkError(Exception):
    """Raised when a delivery deep link is invalid or cannot be processed."""

    def __init__(self, message: str, parse_mode: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.parse_mode = parse_mode


def _extract_command_argument(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    """Return the first argument passed to a command, including text fallback."""
    if context.args:
        return context.args[0]
    if update.message and update.message.text:
        parts = update.message.text.strip().split(maxsplit=1)
        if len(parts) == 2:
            return parts[1]
    return None


def _normalize_delivery_argument(raw_arg: str) -> str:
    """Remove known prefixes from Telegram deep-link arguments."""
    for prefix in ("entrega_", "iniciar_"):
        if raw_arg.startswith(prefix):
            raw_arg = raw_arg[len(prefix):]
    # Trata prefixo específico de insucesso: entrega_fail_ -> fail_
    if raw_arg.startswith("fail_"):
        return raw_arg
    if raw_arg.startswith("entrega_fail_"):
        return "fail_" + raw_arg.split("entrega_fail_", 1)[1]
    return raw_arg


def _build_delivery_mode_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard reused when prompting the driver to choose delivery mode."""
    return ReplyKeyboardMarkup([["Unitário", "Em massa"]], resize_keyboard=True, one_time_keyboard=True)


async def _prompt_delivery_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, package_ids: List[int]) -> int:
    """Store target package IDs and prompt the driver to choose the flow."""
    keyboard = _build_delivery_mode_keyboard()
    if len(package_ids) > 1:
        context.user_data["deliver_package_ids"] = package_ids
        context.user_data.pop("deliver_package_id", None)
        await update.message.reply_text(
            "📦 *Entrega Múltipla*\n\n"
            f"🎯 {len(package_ids)} pacotes selecionados\n\n"
            "Como será esta entrega?",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    else:
        context.user_data["deliver_package_id"] = package_ids[0]
        context.user_data.pop("deliver_package_ids", None)
        await update.message.reply_text(
            "📦 *Iniciar Entrega*\n\n"
            "Como será esta entrega?",
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    return MODE_SELECT


async def _process_delivery_argument(update: Update, context: ContextTypes.DEFAULT_TYPE, raw_arg: str) -> Optional[int]:
    """Processa argumentos de deep link e retorna o próximo estado da conversa."""
    if not raw_arg:
        return None

    arg = _normalize_delivery_argument(raw_arg.strip())
    if not arg:
        return None

    if arg.startswith("deliverg_"):
        token = arg.split("deliverg_", 1)[1]
        db = SessionLocal()
        try:
            rec = db.query(LinkToken).filter(LinkToken.token == token, LinkToken.type == "deliver_group").first()
            if rec and isinstance(rec.data, dict) and rec.data.get("ids"):
                try:
                    ids = [int(i) for i in rec.data["ids"]]
                except Exception as convert_err:
                    raise DeliveryLinkError(f"❌ Erro ao processar token: {convert_err}", 'Markdown') from convert_err
                if not ids:
                    raise DeliveryLinkError(
                        "❌ *Token Inválido*\n\nEste link de entrega expirou ou é inválido.\n\nUse o mapa interativo para gerar um novo link.",
                        'Markdown'
                    )
                return await _prompt_delivery_mode(update, context, ids)
        finally:
            db.close()
        raise DeliveryLinkError(
            "❌ *Token Inválido*\n\nEste link de entrega expirou ou é inválido.\n\nUse o mapa interativo para gerar um novo link.",
            'Markdown'
        )

    if arg.startswith("deliver_group_"):
        ids_str = arg.split("deliver_group_", 1)[1]
        ids = [int(x) for x in ids_str.split("_") if x.isdigit()]
        if not ids:
            raise DeliveryLinkError(
                "❌ *Pacotes Não Encontrados*\n\nO link informado não contém pacotes válidos.",
                'Markdown'
            )
        return await _prompt_delivery_mode(update, context, ids)

    if arg.startswith("iniciar_deliver_"):
        package_id_str = arg.split("iniciar_deliver_", 1)[1]
        try:
            package_id = int(package_id_str)
        except ValueError as err:
            raise DeliveryLinkError("❌ *ID Inválido*\n\nO ID do pacote precisa ser numérico.", 'Markdown') from err
        return await _prompt_delivery_mode(update, context, [package_id])

    if arg.startswith("deliver_"):
        package_id_str = arg.split("deliver_", 1)[1]
        try:
            package_id = int(package_id_str)
        except ValueError as err:
            raise DeliveryLinkError("❌ *ID Inválido*\n\nO ID do pacote precisa ser numérico.", 'Markdown') from err
        return await _prompt_delivery_mode(update, context, [package_id])

    # Fluxo rápido de INSUCESSO via deep link: entrega_fail_<id> (normalizado para fail_<id>)
    if arg.startswith("fail_"):
        package_id_str = arg.split("fail_", 1)[1]
        try:
            package_id = int(package_id_str)
        except ValueError as err:
            raise DeliveryLinkError("❌ *ID Inválido*\n\nO ID do pacote precisa ser numérico.", 'Markdown') from err
        # Inicia conversa pedindo foto
        context.user_data.clear()
        context.user_data["fail_package_id"] = package_id
        if update.message:
            await update.message.reply_text(
                "❌ *Insucesso na Entrega*\n\nEnvie uma *foto* do pacote/local para registrar o insucesso.",
                parse_mode='Markdown'
            )
        return FAIL_PHOTO

    return None


# Comandos
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start - Cadastro inicial e boas-vindas OU inicia entrega via deep link"""
    init_db()
    u = update.effective_user
    user = register_manager_if_first(u.id, u.full_name)

    arg = _extract_command_argument(update, context)
    if arg:
        try:
            result = await _process_delivery_argument(update, context, arg)
        except DeliveryLinkError as err:
            if update.message:
                await update.message.reply_text(err.message, parse_mode=err.parse_mode)
            return ConversationHandler.END
        if result is not None:
            return result

    if not update.message:
        return ConversationHandler.END

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
    arg = _extract_command_argument(update, context)
    if not arg:
        if update.message:
            await update.message.reply_text(
                "⚠️ Comando inválido.\n\nUse o botão 'Entregar' no mapa interativo para iniciar uma entrega.",
                parse_mode='Markdown'
            )
        return ConversationHandler.END

    try:
        result = await _process_delivery_argument(update, context, arg)
    except DeliveryLinkError as err:
        if update.message:
            await update.message.reply_text(err.message, parse_mode=err.parse_mode)
        return ConversationHandler.END

    if result is not None:
        return result

    if update.message:
        await update.message.reply_text(
            "⚠️ Comando inválido.\n\nUse o botão 'Entregar' no mapa interativo para iniciar uma entrega.",
            parse_mode='Markdown'
        )
    return ConversationHandler.END


async def cmd_entrega(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /entrega - Inicia fluxo de entrega (grupos ou único pacote)"""
    arg = _extract_command_argument(update, context)
    if not arg:
        if update.message:
            await update.message.reply_text(
                "⚠️ *Comando Incorreto*\n\nUse o botão *'Entregar'* no mapa interativo para iniciar uma entrega.\n\n💡 Este comando é usado automaticamente quando você clica nos botões de entrega.",
                parse_mode='Markdown'
            )
        return ConversationHandler.END

    try:
        result = await _process_delivery_argument(update, context, arg)
    except DeliveryLinkError as err:
        if update.message:
            await update.message.reply_text(err.message, parse_mode=err.parse_mode)
        return ConversationHandler.END

    if result is not None:
        return result

    if update.message:
        await update.message.reply_text(
            "⚠️ *Comando Incorreto*\n\nUse o botão *'Entregar'* no mapa interativo para iniciar uma entrega.\n\n💡 Este comando é usado automaticamente quando você clica nos botões de entrega.",
            parse_mode='Markdown'
        )
    return ConversationHandler.END


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando de ajuda interativo com botões por categoria"""
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
            # Menu principal para GERENTE
            keyboard = [
                [InlineKeyboardButton("📦 Gestão de Rotas", callback_data="help_manager_routes")],
                [InlineKeyboardButton("👥 Gestão de Equipe", callback_data="help_manager_team")],
                [InlineKeyboardButton("💰 Financeiro & IA", callback_data="help_manager_finance")],
                [InlineKeyboardButton("🚀 Workflow & Dicas", callback_data="help_manager_workflow")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "╔══════════════════════════╗\n"
                "║  🎯 *CENTRAL DO GERENTE*  ║\n"
                "╚══════════════════════════╝\n\n"
                
                "👋 Olá, gerente! Selecione uma categoria abaixo para ver os comandos disponíveis:\n\n"
                
                "📦 *Gestão de Rotas*\n"
                "   → Importar, enviar e rastrear rotas\n\n"
                
                "👥 *Gestão de Equipe*\n"
                "   → Cadastrar motoristas e configurar canais\n\n"
                
                "💰 *Financeiro & IA*\n"
                "   → Relatórios, análises e chat inteligente\n\n"
                
                "🚀 *Workflow & Dicas*\n"
                "   → Aprenda o fluxo ideal e dicas avançadas\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 *Clique nos botões para explorar!*",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        else:
            # Menu principal para MOTORISTA
            keyboard = [
                [InlineKeyboardButton("📍 Como Funciona?", callback_data="help_driver_howto")],
                [InlineKeyboardButton("📸 Processo de Entrega", callback_data="help_driver_delivery")],
                [InlineKeyboardButton("🗺️ Usar o Mapa", callback_data="help_driver_map")],
                [InlineKeyboardButton("🔧 Comandos", callback_data="help_driver_commands")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "╔═══════════════════════════╗\n"
                "║  🚚 *CENTRAL DO MOTORISTA*  ║\n"
                "╚═══════════════════════════╝\n\n"
                
                "👋 Olá, motorista! Selecione abaixo o que você quer saber:\n\n"
                
                "📍 *Como Funciona?*\n"
                "   → Entenda o fluxo completo\n\n"
                
                "📸 *Processo de Entrega*\n"
                "   → Passo a passo para registrar\n\n"
                
                "🗺️ *Usar o Mapa*\n"
                "   → Recursos e cores dos pins\n\n"
                
                "🔧 *Comandos*\n"
                "   → Lista de comandos disponíveis\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 *Clique nos botões para explorar!*",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        
    finally:
        db.close()


# ==================== CALLBACKS DO HELP INTERATIVO ====================

async def help_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler para os botões do /help interativo"""
    query = update.callback_query
    await query.answer()
    
    action = query.data
    
    # ========== MANAGER - GESTÃO DE ROTAS ==========
    if action == "help_manager_routes":
        keyboard = [[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="help_back_manager")]]
        await query.edit_message_text(
            "📦 *GESTÃO DE ROTAS*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            "*🆕 /importar*\n"
            "Importa planilha Excel ou CSV com endereços de entrega.\n"
            "• Suporta múltiplos formatos\n"
            "• Geocodificação automática\n"
            "• Você escolhe o nome da rota\n\n"
            
            "*🚚 /enviarrota*\n"
            "Atribui uma rota para um motorista.\n"
            "• Otimização automática de percurso\n"
            "• Gera link de rastreamento\n"
            "• Notifica motorista no Telegram\n\n"
            
            "*🗺️ Rastrear:* abra /rotas e toque em '🗺️ Rastrear'\n"
            "Acompanha rotas ativas em tempo real.\n"
            "• GPS ao vivo do motorista\n"
            "• Atualização a cada 30 segundos\n"
            "• Status detalhado de cada entrega\n\n"
            
            "*🏁 Finalizar Rota*\n"
            "Após entregas concluídas, finalize a rota.\n"
            "• Registra KM rodados\n"
            "• Adiciona despesas/receitas extras\n"
            "• Salva tudo automaticamente no banco\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 *Fluxo:* Importar → Enviar → Rastrear → Finalizar",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ========== MANAGER - GESTÃO DE EQUIPE ==========
    elif action == "help_manager_team":
        keyboard = [[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="help_back_manager")]]
        await query.edit_message_text(
            "👥 *GESTÃO DE EQUIPE*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            "*➕ /cadastrardriver*\n"
            "Adiciona um novo motorista ao sistema.\n"
            "• Pede Telegram ID e nome completo\n"
            "• Acesso imediato aos comandos\n"
            "• Motorista pode começar a trabalhar\n\n"
            
            "*📋 /drivers*\n"
            "Lista todos os motoristas cadastrados.\n"
            "• 🟢 Em rota / ⚪ Disponível\n"
            "• Botões: 🗺️ Rastrear | 🗑️ Remover\n"
            "• Informações de contato\n\n"
            
            "*🏠 /configurarcasa*\n"
            "Define o ponto de partida do motorista.\n"
            "• Motorista envia localização GPS\n"
            "• Rotas otimizadas a partir da casa dele\n"
            "• Economia de combustível e tempo\n\n"
            
            "*📢 /configurarcanal*\n"
            "Canal de provas por motorista.\n"
            "• Fotos de entregas organizadas\n"
            "• Um canal dedicado por motorista\n"
            "• Histórico de provas centralizado\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 *Dica:* Configure canais separados para melhor organização!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ========== MANAGER - FINANCEIRO & IA ==========
    elif action == "help_manager_finance":
        keyboard = [[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="help_back_manager")]]
        await query.edit_message_text(
            "💰 *FINANCEIRO & IA*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            "*📋 /meus_registros*\n"
            "Visualiza todos os registros financeiros.\n"
            "• Ver/editar/deletar dias\n"
            "• Balanço de lucro por dia\n"
            "• Integrado com despesas e receitas\n\n"
            
            "*🤖 /relatorio*\n"
            "Relatório inteligente com IA (Groq).\n"
            "• Análise POR ROTA com margem\n"
            "• Comparação mês anterior\n"
            "• Recomendações prescritivas\n"
            "• Enviado automaticamente ao canal\n\n"
            
            "*💬 /chat_ia*\n"
            "Converse com seus dados!\n"
            "• Perguntas em linguagem natural\n"
            "• Contexto de métricas preservado\n"
            "• Análise profunda e personalizada\n\n"
            
            "*📢 /configurar_canal_análise*\n"
            "Canal dedicado para relatórios automáticos.\n"
            "• Organiza análises em um lugar\n"
            "• Histórico centralizado\n"
            "• Mantém chat privado limpo\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 *Automação:* Finanças são registradas ao finalizar rotas!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ========== MANAGER - WORKFLOW ==========
    elif action == "help_manager_workflow":
        keyboard = [[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="help_back_manager")]]
        await query.edit_message_text(
            "🚀 *WORKFLOW RECOMENDADO*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            "*FLUXO DIÁRIO:*\n\n"
            
            "1️⃣ *Importar Planilha*\n"
            "   → Use /importar com Excel/CSV\n\n"
            
            "2️⃣ *Enviar Rota*\n"
            "   → Use /enviarrota para atribuir\n\n"
            
            "3️⃣ *Rastrear Progresso*\n"
            "   → Rastreie via /rotas (botão '🗺️ Rastrear')\n\n"
            
            "4️⃣ *Receber Notificações*\n"
            "   → Automático a cada entrega\n\n"
            
            "5️⃣ *Finalizar Rota*\n"
            "   → Registra KM, despesas e receitas\n\n"
            
            "6️⃣ *Explorar com IA (Opcional)*\n"
            "   → Use /chat_ia para insights\n\n"
            
            "7️⃣ *Analisar Relatórios*\n"
            "   → Use /relatorio ao fim do dia/mês\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "*💡 DICAS PRO:*\n\n"
            
            "✅ Nomeie rotas (ex: Zona Sul, Centro)\n"
            "✅ Configure canais separados por motorista\n"
            "✅ Peça motoristas para usar /configurarcasa\n"
            "✅ Configure /configurar_canal_análise\n"
            "✅ Finalize rotas para registros automáticos\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "*🎯 RECURSOS AVANÇADOS:*\n\n"
            
            "🔹 Otimização automática de rotas\n"
            "🔹 Rastreamento GPS em tempo real\n"
            "🔹 Notificações push automáticas\n"
            "🔹 Análise de IA com comparações\n"
            "🔹 Automação 100% de finanças\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 *Outros Comandos:*\n"
            "/meu_id - Seu Telegram ID\n"
            "/cancelar - Cancela operação atual",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ========== DRIVER - COMO FUNCIONA ==========
    elif action == "help_driver_howto":
        keyboard = [[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="help_back_driver")]]
        await query.edit_message_text(
            "📍 *COMO FUNCIONA?*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            "*PASSO A PASSO:*\n\n"
            
            "1️⃣ *Receba a Rota*\n"
            "Gerente atribui uma rota para você via Telegram.\n\n"
            
            "2️⃣ *Abra o Mapa*\n"
            "Você recebe um link com o mapa interativo 🗺️\n\n"
            
            "3️⃣ *Veja os Pacotes*\n"
            "Mapa mostra todos os pacotes numerados e otimizados.\n\n"
            
            "4️⃣ *Navegue até o Local*\n"
            "Clique no pin e use o botão '🧭 Navegar' para abrir Google Maps.\n\n"
            
            "5️⃣ *Registre a Entrega*\n"
            "Ao chegar, clique em '✓ Entregar' no mapa ou use /entregar.\n\n"
            
            "6️⃣ *Envie Comprovantes*\n"
            "No Telegram: foto do pacote + foto do local + dados do recebedor.\n\n"
            
            "7️⃣ *Continue a Rota*\n"
            "Repita para todos os pacotes até finalizar!\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 *Dica:* O mapa atualiza sua localização a cada 30 segundos!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ========== DRIVER - PROCESSO DE ENTREGA ==========
    elif action == "help_driver_delivery":
        keyboard = [[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="help_back_driver")]]
        await query.edit_message_text(
            "📸 *PROCESSO DE ENTREGA*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            "*O QUE VOCÊ PRECISA FAZER:*\n\n"
            
            "*1️⃣ Foto do Pacote*\n"
            "📦 Tire uma foto mostrando a etiqueta do pacote de forma clara.\n\n"
            
            "*2️⃣ Foto do Local*\n"
            "🏠 Tire uma foto da porta, fachada ou da pessoa que recebeu.\n\n"
            
            "*3️⃣ Nome do Recebedor*\n"
            "👤 Digite o nome completo de quem assinou/recebeu.\n\n"
            
            "*4️⃣ Documento (CPF/RG)*\n"
            "🆔 Digite CPF ou RG do recebedor.\n"
            "   → Se não tiver, digite: *sem documento*\n\n"
            
            "*5️⃣ Observações (Opcional)*\n"
            "📝 Adicione informações extras se necessário.\n"
            "   → Exemplos: 'Porteiro recebeu', 'Deixado na portaria'\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "*⚠️ IMPORTANTE:*\n\n"
            
            "✅ Fotos sempre claras e nítidas\n"
            "✅ Evite fotos borradas ou escuras\n"
            "✅ Mostre a etiqueta completa\n"
            "✅ Documento é obrigatório (ou 'sem documento')\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 *Dica:* Fotos de qualidade evitam problemas futuros!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ========== DRIVER - USAR O MAPA ==========
    elif action == "help_driver_map":
        keyboard = [[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="help_back_driver")]]
        await query.edit_message_text(
            "🗺️ *RECURSOS DO MAPA*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            "*FUNCIONALIDADES:*\n\n"
            
            "⏱️ *Atualização Automática*\n"
            "Mapa se atualiza a cada 30 segundos com sua localização.\n\n"
            
            "📍 *Sua Localização*\n"
            "Você aparece como um marcador azul em tempo real.\n\n"
            
            "📊 *Contador de Entregas*\n"
            "Veja quantos pacotes faltam e quantos foram entregues.\n\n"
            
            "🧭 *Navegação Integrada*\n"
            "Clique em 'Navegar' para abrir Google Maps e traçar rota.\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "*CORES DOS PINS:*\n\n"
            
            "🔵 *Azul* → Pacote Pendente\n"
            "   (Ainda não foi entregue)\n\n"
            
            "🟢 *Verde* → Entregue com Sucesso ✅\n"
            "   (Confirmado com comprovante)\n\n"
            
            "🔴 *Vermelho* → Falha na Entrega ❌\n"
            "   (Cliente ausente, endereço errado, etc)\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "*💡 DICAS:*\n\n"
            
            "✅ Mapa funciona offline após carregar\n"
            "✅ Siga a ordem numérica otimizada\n"
            "✅ Clique nos pins para ver detalhes\n"
            "✅ Use zoom para melhor visualização\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 *Dica:* Mantenha a localização ativada!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ========== DRIVER - COMANDOS ==========
    elif action == "help_driver_commands":
        keyboard = [[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="help_back_driver")]]
        await query.edit_message_text(
            "🔧 *COMANDOS DISPONÍVEIS*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            "*PRINCIPAIS:*\n\n"
            
            "*📦 /entregar*\n"
            "Registra a entrega de um pacote.\n"
            "• Envia fotos e dados do recebedor\n"
            "• Gera comprovante automático\n\n"
            
            "*🏠 /configurarcasa*\n"
            "Define seu endereço de partida.\n"
            "• Envia sua localização GPS\n"
            "• Rotas otimizadas a partir da sua casa\n"
            "• Economia de combustível\n\n"
            
            "*🆔 /meu_id*\n"
            "Mostra seu Telegram ID.\n"
            "• Útil para cadastro com o gerente\n\n"
            
            "*❓ /help*\n"
            "Exibe este menu de ajuda.\n\n"
            
            "*🚫 /cancelar*\n"
            "Cancela a operação atual.\n"
            "• Use se estiver no meio de um processo\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "*📱 NOTIFICAÇÕES AUTOMÁTICAS:*\n\n"
            
            "Você receberá mensagens quando:\n"
            "• Nova rota for atribuída 🎯\n"
            "• Entrega for confirmada ✅\n"
            "• Houver algum problema ⚠️\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "*💡 DICAS:*\n\n"
            
            "✅ Configure /configurarcasa primeiro\n"
            "✅ Use o mapa interativo sempre que possível\n"
            "✅ Mantenha notificações ativadas\n"
            "✅ Tire fotos claras e nítidas\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 *Dúvidas?* Fale com seu gerente!",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ========== VOLTAR AO MENU ==========
    elif action == "help_back_manager":
        keyboard = [
            [InlineKeyboardButton("📦 Gestão de Rotas", callback_data="help_manager_routes")],
            [InlineKeyboardButton("👥 Gestão de Equipe", callback_data="help_manager_team")],
            [InlineKeyboardButton("💰 Financeiro & IA", callback_data="help_manager_finance")],
            [InlineKeyboardButton("🚀 Workflow & Dicas", callback_data="help_manager_workflow")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "╔══════════════════════════╗\n"
            "║  🎯 *CENTRAL DO GERENTE*  ║\n"
            "╚══════════════════════════╝\n\n"
            
            "👋 Olá, gerente! Selecione uma categoria abaixo para ver os comandos disponíveis:\n\n"
            
            "📦 *Gestão de Rotas*\n"
            "   → Importar, enviar e rastrear rotas\n\n"
            
            "👥 *Gestão de Equipe*\n"
            "   → Cadastrar motoristas e configurar canais\n\n"
            
            "💰 *Financeiro & IA*\n"
            "   → Relatórios, análises e chat inteligente\n\n"
            
            "🚀 *Workflow & Dicas*\n"
            "   → Aprenda o fluxo ideal e dicas avançadas\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 *Clique nos botões para explorar!*",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    elif action == "help_back_driver":
        keyboard = [
            [InlineKeyboardButton("📍 Como Funciona?", callback_data="help_driver_howto")],
            [InlineKeyboardButton("📸 Processo de Entrega", callback_data="help_driver_delivery")],
            [InlineKeyboardButton("🗺️ Usar o Mapa", callback_data="help_driver_map")],
            [InlineKeyboardButton("🔧 Comandos", callback_data="help_driver_commands")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "╔═══════════════════════════╗\n"
            "║  🚚 *CENTRAL DO MOTORISTA*  ║\n"
            "╚═══════════════════════════╝\n\n"
            
            "👋 Olá, motorista! Selecione abaixo o que você quer saber:\n\n"
            
            "📍 *Como Funciona?*\n"
            "   → Entenda o fluxo completo\n\n"
            
            "📸 *Processo de Entrega*\n"
            "   → Passo a passo para registrar\n\n"
            
            "🗺️ *Usar o Mapa*\n"
            "   → Recursos e cores dos pins\n\n"
            
            "🔧 *Comandos*\n"
            "   → Lista de comandos disponíveis\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 *Clique nos botões para explorar!*",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )




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
                "   └ Escolha o nome da rota\n"
                "   └ Sistema geocodifica endereços\n"
                "   └ Suporta múltiplos formatos\n\n"
                
                "🚚 */enviarrota*\n"
                "   └ Atribui rota ao motorista\n"
                "   └ Otimização automática ⚡\n"
                "   └ Link de rastreamento gerado\n"
                "   └ Notifica motorista no Telegram\n\n"
                
                "🗺️ *Rastrear via /rotas*\n"
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
                
                " */meus_registros*\n"
                "   └ Visualiza todos os registros\n"
                "   └ ✨ NOVO: Ver/editar/deletar dias\n"
                "   └ Balance de lucro por dia\n"
                "   └ Integrado com receitas e despesas\n\n"
                
                "🤖 */relatorio*\n"
                "   └ Relatório inteligente com IA\n"
                "   └ ✨ NOVO: Análise por ROTA\n"
                "   └ Margem de lucro por rota\n"
                "   └ Recomendações prescritivas\n"
                "   └ ✨ NOVO: Enviado para canal\n\n"
                
                "💬 */chat_ia* ✨ NOVO\n"
                "   └ Conversa interativa com IA\n"
                "   └ Histórico de perguntas mantido\n"
                "   └ Contexto de dados preservado\n"
                "   └ Análise profunda de métricas\n\n"
                
                "📢 */configurar_canal_análise* ✨ NOVO\n"
                "   └ Canal dedicado para relatórios\n"
                "   └ Organiza análises em um lugar\n"
                "   └ Histórico centralizado\n"
                "   └ Manter chat privado limpo\n\n"
                
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
                
                "🆕 *NOVO: Melhorias IA & Análise* ✨\n"
                "   • /chat_ia: Converse com seus dados!\n"
                "   • /configurar_canal_análise: Organize relatórios\n"
                "   • /meus_registros: Edite/delete dias\n"
                "   • /relatorio com análise POR ROTA\n"
                "   • Finanças automáticas na finalização\n\n"
                
                "1️⃣ *Nomeie rotas* (ex: Zona Sul, Centro)\n"
                "   → Facilita identificação\n\n"
                
                "2️⃣ *Configure canais separados*\n"
                "   → Organiza provas por motorista\n\n"
                
                "3️⃣ *Peça aos motoristas* para usar /configurarcasa\n"
                "   → Otimização personalizada\n\n"
                
                "4️⃣ *Rastreie via /rotas* (botão '🗺️ Rastrear')\n"
                "   → Acompanhe progresso real\n\n"
                
                "5️⃣ *Configure /configurar_canal_análise*\n"
                "   → Relatórios organizados\n\n"
                
                "6️⃣ *Use /chat_ia* para explorar dados\n"
                "   → Respostas profundas com contexto\n\n"
                
                "7️⃣ *Finalize rotas* para registrar finanças\n"
                "   → Dados automáticos com precisão\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "🚀 *WORKFLOW RECOMENDADO*\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                "📥 *1. Importar* planilha com /importar\n"
                "↓\n"
                "🚚 *2. Enviar* rota com /enviarrota\n"
                "↓\n"
                "👀 *3. Rastrear* em /rotas (botão '🗺️ Rastrear')\n"
                "↓\n"
                "✅ *4. Receber* notificações automáticas\n"
                "↓\n"
                "🏁 *5. Finalizar* rota (registra finanças)\n"
                "↓\n"
                "💬 *6. Explorar* com /chat_ia (opcional)\n"
                "↓\n"
                "🤖 *7. Analisar* com /relatorio ← VÊ POR ROTA\n"
                "↓\n"
                "📢 *8. Receber* no /configurar_canal_análise ← AUTOMATIZADO\n\n"
                
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "🌟 *Sistema completo de gestão*\n"
                "🌟 *Rastreamento em tempo real*\n"
                "🌟 *Otimização inteligente*\n"
                "🌟 *Relatórios com IA avançada*\n"
                "🌟 *Análise por ROTA (NOVO)*\n"
                "🌟 *Chat com dados (NOVO)*\n\n"
                
                "💬 *Dúvidas?* Teste os comandos!\n"
                "⚡ *Comece agora* com /importar\n"
                "📚 *Documentação*: Veja arquivos MELHORIAS_*.md"
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
        
        # Envia mensagem de processamento inicial
        processing_msg = await update.message.reply_text(
            "📊 *Gerando Relatório*\n\n"
            "🔄 [▓░░░░░░░░░] 10% - Iniciando...",
            parse_mode='Markdown'
        )
        
        # Coleta dados do mês atual
        now = datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Verifica cache primeiro
        cached_stats = _get_cached_monthly_stats(now.month, now.year)
        
        if cached_stats:
            # Usa dados do cache (MUITO mais rápido)
            await processing_msg.edit_text(
                "📊 *Gerando Relatório*\n\n"
                "🔄 [▓▓▓░░░░░░░] 30% - Usando dados em cache...",
                parse_mode='Markdown'
            )
            (total_packages, delivered_packages, failed_packages, total_routes, 
             active_drivers, total_income, total_expenses, total_mileage,
             total_revenue, total_spent, total_km) = cached_stats
        else:
            # ETAPA 1: Coleta todos os dados em UMA ÚNICA QUERY otimizada (20%)
            await processing_msg.edit_text(
                "📊 *Gerando Relatório*\n\n"
                "🔄 [▓▓░░░░░░░░] 20% - Coletando dados (query otimizada)...",
                parse_mode='Markdown'
            )
        
        # Query única com CTE (Common Table Expression) - MUITO mais rápido que 7 queries
        monthly_stats = db.execute(text("""
            WITH package_stats AS (
                SELECT 
                    COUNT(*) as total_packages,
                    SUM(CASE WHEN p.status = 'delivered' THEN 1 ELSE 0 END) as delivered_packages,
                    SUM(CASE WHEN p.status = 'failed' THEN 1 ELSE 0 END) as failed_packages
                FROM package p
                JOIN route r ON p.route_id = r.id
                WHERE r.created_at >= :month_start
            ),
            route_stats AS (
                SELECT 
                    COUNT(*) as total_routes,
                    (SELECT COUNT(*) FROM "user" WHERE role = 'driver') as active_drivers
                FROM route
                WHERE created_at >= :month_start
            ),
            finance_stats AS (
                SELECT 
                    (SELECT COUNT(*) FROM income WHERE date >= :month_date) as total_income_records,
                    (SELECT COUNT(*) FROM expense WHERE date >= :month_date) as total_expense_records,
                    (SELECT COUNT(*) FROM mileage WHERE date >= :month_date) as total_mileage_records,
                    (SELECT COALESCE(SUM(amount), 0) FROM income WHERE date >= :month_date) as total_revenue,
                    (SELECT COALESCE(SUM(amount), 0) FROM expense WHERE date >= :month_date) as total_spent,
                    (SELECT COALESCE(SUM(km_total), 0) FROM mileage WHERE date >= :month_date) as total_km
            )
            SELECT 
                ps.total_packages,
                ps.delivered_packages,
                ps.failed_packages,
                rs.total_routes,
                rs.active_drivers,
                fs.total_income_records,
                fs.total_expense_records,
                fs.total_mileage_records,
                fs.total_revenue,
                fs.total_spent,
                fs.total_km
            FROM package_stats ps, route_stats rs, finance_stats fs
        """), {
            "month_start": month_start,
            "month_date": month_start.date()
        }).first()
        
        # Extrai valores da query única
        total_packages = monthly_stats[0] or 0
        delivered_packages = monthly_stats[1] or 0
        failed_packages = monthly_stats[2] or 0
        total_routes = monthly_stats[3] or 0
        active_drivers = monthly_stats[4] or 0
        total_income = monthly_stats[5] or 0
        total_expenses = monthly_stats[6] or 0
        total_mileage = monthly_stats[7] or 0
        total_revenue = float(monthly_stats[8] or 0)
        total_spent = float(monthly_stats[9] or 0)
        total_km = float(monthly_stats[10] or 0)
        
        # Salva no cache para próximas chamadas
        _set_cached_monthly_stats(now.month, now.year, (
            total_packages, delivered_packages, failed_packages, total_routes,
            active_drivers, total_income, total_expenses, total_mileage,
            total_revenue, total_spent, total_km
        ))
        
        # ETAPA 2: Calcula métricas derivadas (35%)
        await processing_msg.edit_text(
            "📊 *Gerando Relatório*\n\n"
            "🔄 [▓▓▓▓░░░░░░] 35% - Calculando métricas...",
            parse_mode='Markdown'
        )
        
        net_profit = total_revenue - total_spent
        profit_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else 0
        
        # ✅ FASE 6: Busca dados do mês anterior para comparação (40%)
        await processing_msg.edit_text(
            "📊 *Gerando Relatório*\n\n"
            "🔄 [▓▓▓▓▓░░░░░] 40% - Comparando com mês anterior...",
            parse_mode='Markdown'
        )
        
        # Calcula início do mês anterior
        if now.month == 1:
            prev_month_start = now.replace(year=now.year-1, month=12, day=1, hour=0, minute=0, second=0, microsecond=0)
            prev_month_end = month_start
        else:
            prev_month_start = now.replace(month=now.month-1, day=1, hour=0, minute=0, second=0, microsecond=0)
            prev_month_end = month_start
        
        # Query para mês anterior (mesma estrutura)
        prev_stats = db.execute(text("""
            WITH package_stats AS (
                SELECT 
                    COUNT(*) as total_packages,
                    SUM(CASE WHEN p.status = 'delivered' THEN 1 ELSE 0 END) as delivered_packages
                FROM package p
                JOIN route r ON p.route_id = r.id
                WHERE r.created_at >= :prev_start AND r.created_at < :prev_end
            ),
            route_stats AS (
                SELECT COUNT(*) as total_routes
                FROM route
                WHERE created_at >= :prev_start AND created_at < :prev_end
            ),
            finance_stats AS (
                SELECT 
                    (SELECT COALESCE(SUM(amount), 0) FROM income WHERE date >= :prev_date_start AND date < :prev_date_end) as total_revenue,
                    (SELECT COALESCE(SUM(amount), 0) FROM expense WHERE date >= :prev_date_start AND date < :prev_date_end) as total_spent
            )
            SELECT 
                ps.total_packages,
                ps.delivered_packages,
                rs.total_routes,
                fs.total_revenue,
                fs.total_spent
            FROM package_stats ps, route_stats rs, finance_stats fs
        """), {
            "prev_start": prev_month_start,
            "prev_end": prev_month_end,
            "prev_date_start": prev_month_start.date(),
            "prev_date_end": prev_month_end.date()
        }).first()
        
        # Extrai dados do mês anterior
        prev_packages = prev_stats[0] or 0
        prev_delivered = prev_stats[1] or 0
        prev_routes = prev_stats[2] or 0
        prev_revenue = float(prev_stats[3] or 0)
        prev_spent = float(prev_stats[4] or 0)
        prev_profit = prev_revenue - prev_spent
        
        # Calcula variações percentuais
        def calc_variation(current, previous):
            if previous == 0:
                return "+100%" if current > 0 else "0%"
            variation = ((current - previous) / previous) * 100
            return f"{variation:+.1f}%"
        
        variation_packages = calc_variation(total_packages, prev_packages)
        variation_revenue = calc_variation(total_revenue, prev_revenue)
        variation_profit = calc_variation(net_profit, prev_profit)
        variation_routes = calc_variation(total_routes, prev_routes)
        
        # Monta texto de comparação
        comparison_text = f"""
📊 COMPARAÇÃO COM MÊS ANTERIOR:
• Pacotes: {total_packages} vs {prev_packages} ({variation_packages})
• Rotas: {total_routes} vs {prev_routes} ({variation_routes})
• Receita: R$ {total_revenue:,.2f} vs R$ {prev_revenue:,.2f} ({variation_revenue})
• Lucro: R$ {net_profit:,.2f} vs R$ {prev_profit:,.2f} ({variation_profit})
"""
        
        # ETAPA 4: Calcula dados por motorista (65%)
        await processing_msg.edit_text(
            "📊 *Gerando Relatório*\n\n"
            "🔄 [▓▓▓▓▓▓▓░░░] 65% - Analisando performance individual...",
            parse_mode='Markdown'
        )
        
        # Calcula dados por motorista
        drivers = db.query(User).filter(User.role == "driver").all()
        drivers_data = []
        for driver in drivers:
            driver_routes = db.query(Route).filter(Route.assigned_to_id == driver.id, Route.created_at >= month_start).count()
            driver_packages = db.query(Package).join(Route).filter(
                Route.assigned_to_id == driver.id,
                Route.created_at >= month_start
            ).count()
            driver_delivered = db.query(Package).join(Route).filter(
                Route.assigned_to_id == driver.id,
                Route.created_at >= month_start,
                Package.status == "delivered"
            ).count()
            
            drivers_data.append({
                'name': driver.full_name or f"Motorista {driver.id}",
                'routes': driver_routes,
                'packages': driver_packages,
                'delivered': driver_delivered,
                'success_rate': (driver_delivered / driver_packages * 100) if driver_packages > 0 else 0
            })
        
        # ETAPA 5: Prepara prompt para IA (75%)
        await processing_msg.edit_text(
            "📊 *Gerando Relatório*\n\n"
            "🔄 [▓▓▓▓▓▓▓▓░░] 75% - Preparando análise inteligente...",
            parse_mode='Markdown'
        )
        
        # Monta prompt profissional para a IA
        prompt = f"""Você é um analista financeiro senior especializado em logística e entregas. 
GERE UM RELATÓRIO EXECUTIVO PROFISSIONAL E BEM ESTRUTURADO.

═══════════════════════════════════════════════════════════════
DADOS OPERACIONAIS - {now.strftime('%B de %Y')}
═══════════════════════════════════════════════════════════════

📦 PERFORMANCE DE ENTREGAS:
• Total de pacotes processados: {total_packages}
• Pacotes entregues com sucesso: {delivered_packages}
• Falhas na entrega: {failed_packages}
• Taxa de sucesso: {(delivered_packages/total_packages*100 if total_packages > 0 else 0):.1f}%

🚚 OPERAÇÕES LOGÍSTICAS:
• Rotas criadas no período: {total_routes}
• Motoristas ativos: {active_drivers}
• Média de pacotes por rota: {(total_packages/total_routes if total_routes > 0 else 0):.1f}
• Quilometragem registrada: {total_km:.1f} km

💰 ANÁLISE FINANCEIRA:
• RECEITA TOTAL: R$ {total_revenue:,.2f}
• DESPESAS TOTAIS: R$ {total_spent:,.2f}
• LUCRO LÍQUIDO: R$ {net_profit:,.2f}
• MARGEM DE LUCRO: {profit_margin:.1f}%

{comparison_text}

📊 DETALHAMENTO POR MOTORISTA:
{chr(10).join([f"  {d['name']}: {d['routes']} rota(s), {d['delivered']}/{d['packages']} entregas ({d['success_rate']:.1f}% sucesso)" for d in drivers_data])}

═══════════════════════════════════════════════════════════════
INSTRUÇÕES CRÍTICAS PARA O RELATÓRIO:
═══════════════════════════════════════════════════════════════

✅ OBRIGATORIAMENTE incluir:
1. SUMÁRIO EXECUTIVO: 1-2 parágrafos, linguagem clara, sem jargão
2. ANÁLISE FINANCEIRA COM NÚMEROS: Quanto faturou? Quanto gastou? Lucro real?
3. **COMPARAÇÃO TEMPORAL**: Analise as variações vs mês anterior - crescimento ou queda?
4. ANÁLISE POR MOTORISTA: Performance, eficiência, ROI (retorno do investimento)
5. VIABILIDADE ECONÔMICA: Vale expandir? Contratar mais motoristas? Com base em números reais
6. COMBUSTÍVEL & CUSTOS OPERACIONAIS: Consumo, projeção, economy per delivery
7. RECOMENDAÇÕES CONCRETAS: 3-5 ações específicas com números

✅ FORMATAÇÃO:
• Use títulos com emojis mas SEM exagero
• Parágrafos curtos e diretos (máximo 2-3 linhas)
• Dados sempre em negrito quando monetários
• Estrutura visual com separadores (───)
• Conclusão clara e executiva

✅ LINGUAGEM:
• Profissional mas acessível
• Evite: "pode ser considerado", "sugerindo que", "indica uma"
• Use: números concretos, afirmações diretas, análise crítica
• Foco em RESULTADOS e DECISÕES

✅ ANÁLISE DE VIABILIDADE:
• Se lucro/receita < 30%: "Margem apertada, necessário revisar custos"
• Se múltiplos motoristas: "Comparar performance, avaliar realocação"
• Projetar: "Se expandir para X motoristas, lucro seria..."

Gere o RELATÓRIO EXECUTIVO PROFISSIONAL agora:"""

        # ETAPA 6: Processamento com IA (85%)
        await processing_msg.edit_text(
            "📊 *Gerando Relatório*\n\n"
            "� [▓▓▓▓▓▓▓▓▓░] 85% - Processando com IA Groq...",
            parse_mode='Markdown'
        )
        
        # Tenta gerar relatório com Groq IA (se disponível)
        ai_report_generated = False
        if groq_client:
            try:
                # Chama API Groq
                response = groq_client.chat.completions.create(
                    model=ai_model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": "Você é um analista financeiro especializado em logística e entregas. Forneça análises profissionais, objetivas e acionáveis em português do Brasil."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    temperature=0.7,
                    max_tokens=2000
                )
                
                ai_analysis = response.choices[0].message.content
                
                # Salva no banco (AIReport usa month/year como chave única)
                try:
                    # Tenta encontrar relatório existente do mês
                    existing_report = db.query(AIReport).filter(
                        AIReport.month == now.month,
                        AIReport.year == now.year
                    ).first()
                    
                    if existing_report:
                        # UPDATE: atualiza relatório existente
                        existing_report.report_text = ai_analysis
                        existing_report.total_income = total_income
                        existing_report.total_expenses = total_expenses
                        existing_report.total_km = total_mileage
                        existing_report.created_by = me.telegram_user_id
                    else:
                        # INSERT: cria novo relatório
                        report = AIReport(
                            month=now.month,
                            year=now.year,
                            report_text=ai_analysis,
                            total_income=total_income,
                            total_expenses=total_expenses,
                            total_km=total_mileage,
                            created_by=me.telegram_user_id
                        )
                        db.add(report)
                    
                    db.commit()
                except Exception as save_err:
                    # Se falhar ao salvar, apenas mostra o relatório
                    print(f"Aviso ao salvar relatório: {save_err}")
                    db.rollback()
                
                # ETAPA 7: Finalização (100%)
                await processing_msg.edit_text(
                    "📊 *Gerando Relatório*\n\n"
                    "🔄 [▓▓▓▓▓▓▓▓▓▓] 100% - Finalizando...",
                    parse_mode='Markdown'
                )
                
                # Define destino preferido: canal/grupo de análise, se configurado
                preferred_chat_id = me.channel_id if me.channel_id else update.effective_chat.id
                # Divide relatório em mensagens (limite Telegram: 4096 chars)
                max_length = 4000
                if len(ai_analysis) <= max_length:
                    msg_text = f"📊 *Relatório Financeiro - {now.strftime('%B/%Y')}*\n\n{ai_analysis}"
                    # Envia para o destino preferido
                    try:
                        await context.bot.send_message(chat_id=preferred_chat_id, text=msg_text, parse_mode='Markdown')
                    except Exception as ch_err:
                        print(f"Aviso: Não consegui enviar para o destino preferido: {ch_err}")
                        await processing_msg.edit_text(msg_text, parse_mode='Markdown')
                    else:
                        # Confirmação breve no privado, se necessário
                        if preferred_chat_id != update.effective_chat.id:
                            await processing_msg.edit_text("✅ Relatório enviado ao grupo de análise.")
                else:
                    # Envia em partes
                    await processing_msg.delete()
                    parts = [ai_analysis[i:i+max_length] for i in range(0, len(ai_analysis), max_length)]
                    first_msg = f"📊 *Relatório Financeiro - {now.strftime('%B/%Y')}*\n\n{parts[0]}"
                    try:
                        await context.bot.send_message(chat_id=preferred_chat_id, text=first_msg, parse_mode='Markdown')
                        for part in parts[1:]:
                            await context.bot.send_message(chat_id=preferred_chat_id, text=part, parse_mode='Markdown')
                    except Exception as ch_err:
                        print(f"Aviso: Não consegui enviar partes ao destino preferido: {ch_err}")
                        msg1 = await update.message.reply_text(first_msg, parse_mode='Markdown')
                        for part in parts[1:]:
                            await update.message.reply_text(part, parse_mode='Markdown')
                
                # Mensagem final
                if preferred_chat_id == update.effective_chat.id:
                    await update.message.reply_text(
                        f"✅ *Relatório salvo!*\n\n"
                        f"🤖 Gerado por IA Groq (Llama 3.1)\n"
                        f"📅 {now.strftime('%d/%m/%Y %H:%M')}\n"
                        f"_Use /relatorio novamente para atualizar._",
                        parse_mode='Markdown'
                    )
                else:
                    await update.message.reply_text("✅ Relatório enviado ao grupo de análise.")
                ai_report_generated = True
                
            except Exception as e:
                # Falha na IA - vai gerar relatório simples abaixo
                error_msg = str(e)
                print(f"Erro no Groq: {error_msg}")  # Log para debug
        
        # Se IA falhou ou não está disponível, gera relatório simples
        if not ai_report_generated:
            await processing_msg.edit_text(
                f"📊 *Relatório Financeiro - {now.strftime('%B/%Y')}*\n\n"
                f"⚠️ _Relatório básico (IA indisponível)_\n\n"
                f"📦 *ENTREGAS*\n"
                f"• Total: {total_packages} pacotes\n"
                f"• Entregues: {delivered_packages} ({(delivered_packages/total_packages*100 if total_packages > 0 else 0):.1f}%)\n"
                f"• Falhas: {failed_packages}\n\n"
                f"🚚 *OPERAÇÕES*\n"
                f"• Rotas criadas: {total_routes}\n"
                f"• Motoristas ativos: {active_drivers}\n"
                f"• Média: {(total_packages/total_routes if total_routes > 0 else 0):.1f} pacotes/rota\n\n"
                f"💰 *REGISTROS FINANCEIROS*\n"
                f"• Receitas: {total_income} registros\n"
                f"• Despesas: {total_expenses} registros\n"
                f"• Quilometragem: {total_mileage} registros\n\n"
                f"📅 {now.strftime('%d/%m/%Y %H:%M')}\n\n"
                f"_Configure GROQ_API_KEY para análise com IA_",
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


async def cmd_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando de debug para diagnosticar problemas - APENAS GERENTE"""
    db = SessionLocal()
    try:
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            await update.message.reply_text("⛔ Comando disponível apenas para gerentes.")
            return
        
        # Coleta informações de debug
        debug_info = []
        
        # 1. Informações do banco de dados
        try:
            routes_count = db.query(Route).count()
            packages_count = db.query(Package).count()
            drivers_count = db.query(User).filter(User.role == "driver").count()
            debug_info.append(f"✅ **Banco de Dados OK**")
            debug_info.append(f"   • Rotas: {routes_count}")
            debug_info.append(f"   • Pacotes: {packages_count}")
            debug_info.append(f"   • Motoristas: {drivers_count}")
        except Exception as e:
            debug_info.append(f"❌ **Erro no Banco:** `{str(e)[:100]}`")
        
        # 2. Última rota criada
        try:
            last_route = db.query(Route).order_by(Route.created_at.desc()).first()
            if last_route:
                debug_info.append(f"\n📦 **Última Rota:**")
                debug_info.append(f"   • ID: {last_route.id}")
                debug_info.append(f"   • Nome: {last_route.name or 'Sem nome'}")
                debug_info.append(f"   • Status: {last_route.status}")
                debug_info.append(f"   • Pacotes: {len(last_route.packages)}")
                
                # Verifica se tem os campos novos (migration)
                if hasattr(last_route, 'revenue'):
                    debug_info.append(f"   • Revenue: R$ {last_route.revenue:.2f}")
                else:
                    debug_info.append(f"   • ⚠️ **FALTA MIGRATION!** Coluna 'revenue' não existe")
        except Exception as e:
            debug_info.append(f"\n❌ **Erro ao buscar rota:** `{str(e)[:100]}`")
        
        # 3. Configuração do usuário
        try:
            debug_info.append(f"\n👤 **Suas Configurações:**")
            debug_info.append(f"   • Role: {me.role}")
            debug_info.append(f"   • TID: {me.telegram_user_id}")
            debug_info.append(f"   • Canal: {me.channel_id or 'Não configurado'}")
            if me.home_latitude and me.home_longitude:
                debug_info.append(f"   • Casa: ✅ Configurada")
            else:
                debug_info.append(f"   • Casa: ❌ Não configurada")
        except Exception as e:
            debug_info.append(f"\n❌ **Erro nas configs:** `{str(e)[:50]}`")
        
        # 4. Variáveis de ambiente
        try:
            debug_info.append(f"\n⚙️ **Ambiente:**")
            debug_info.append(f"   • Bot Token: {'✅ OK' if os.getenv('TELEGRAM_BOT_TOKEN') else '❌ FALTA'}")
            debug_info.append(f"   • Database: {'✅ OK' if os.getenv('DATABASE_URL') else '❌ FALTA'}")
            debug_info.append(f"   • Groq API: {'✅ OK' if os.getenv('GROQ_API_KEY') else '❌ FALTA'}")
        except Exception as e:
            debug_info.append(f"\n❌ **Erro env vars:** `{str(e)[:50]}`")
        
        # 5. Estrutura da tabela Route (verifica migration)
        try:
            from sqlalchemy import inspect
            inspector = inspect(db.bind)
            columns = inspector.get_columns('route')
            column_names = [col['name'] for col in columns]
            
            debug_info.append(f"\n🗄️ **Colunas da Tabela 'route':**")
            
            # Colunas necessárias (da migration)
            required_cols = ['revenue', 'driver_salary', 'status', 'completed_at', 
                           'finalized_at', 'extra_expenses', 'extra_income', 'calculated_km']
            
            missing_cols = [col for col in required_cols if col not in column_names]
            
            if missing_cols:
                debug_info.append(f"   ⚠️ **FALTAM {len(missing_cols)} COLUNAS:**")
                for col in missing_cols:
                    debug_info.append(f"      • `{col}`")
                debug_info.append(f"\n   💡 **SOLUÇÃO:** Execute a migration!")
                debug_info.append(f"   `python delivery_system/apply_route_automation.py`")
            else:
                debug_info.append(f"   ✅ Todas as colunas OK ({len(column_names)} total)")
        except Exception as e:
            debug_info.append(f"\n❌ **Erro ao verificar tabela:** `{str(e)[:100]}`")
        
        # Monta mensagem final
        message = "🔧 **DEBUG SYSTEM**\n\n" + "\n".join(debug_info)
        
        # Adiciona instruções
        message += "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        message += "📋 **Como usar este relatório:**\n"
        message += "1. Tire print desta mensagem\n"
        message += "2. Mande para o desenvolvedor\n"
        message += "3. Copie a parte com ❌ se houver\n\n"
        message += "💡 **Comandos úteis:**\n"
        message += "• `/meu_id` - Ver seu ID\n"
        message += "• `/drivers` - Listar motoristas\n"
        message += "• `/relatorio` - Testar relatório"
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Erro no Debug:**\n\n"
            f"`{str(e)}`\n\n"
            f"Mande este erro para o desenvolvedor!",
            parse_mode='Markdown'
        )
    finally:
        db.close()


async def cmd_configurar_canal_analise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Configura canal dedicado para receber análises e relatórios"""
    db = SessionLocal()
    try:
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            await update.message.reply_text(
                "⛔ Acesso Negado\n\n"
                "Apenas gerentes podem configurar canais."
            )
            return
        
        # Pega o canal_id do usuário se já tem
        if me.channel_id:
            text = (
                "📢 Canal Configurado\n\n"
                f"ID atual: `{me.channel_id}`\n\n"
                "📝 Para mudar, responda com o novo ID do canal\n"
                "Ex: `-1003024500289`\n\n"
                "💡 Dica: Use `/meu_id` dentro do canal para pegar o ID"
            )
            try:
                await update.message.reply_text(text, parse_mode='Markdown')
            except Exception:
                await update.message.reply_text(text)
        else:
            text = (
                "📢 Nenhum Canal Configurado\n\n"
                "📝 Responda com o ID do seu canal de análise\n"
                "Ex: `-1003024500289`\n\n"
                "💡 Dica: Use `/meu_id` dentro do canal para pegar o ID"
            )
            try:
                await update.message.reply_text(text, parse_mode='Markdown')
            except Exception:
                await update.message.reply_text(text)
        
        # Armazena o estado na conversa
        context.user_data['waiting_for_channel_id'] = True
        
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {str(e)}")
    finally:
        db.close()


async def handle_channel_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processa o ID do canal quando o usuário responde ao /configurar_canal_análise"""
    if not context.user_data.get('waiting_for_channel_id'):
        return  # Não está esperando por um ID de canal
    
    db = SessionLocal()
    try:
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            return
        
        channel_id = update.message.text.strip()
        
        # Valida se é um número negativo (formato de canal Telegram)
        if not channel_id.startswith('-') or not channel_id[1:].isdigit():
            text = (
                "❌ Formato Inválido\n\n"
                "O ID do canal deve ser um número negativo\n"
                "Ex: `-1003024500289`\n\n"
                "Tente novamente ou /cancelar"
            )
            try:
                await update.message.reply_text(text, parse_mode='Markdown')
            except Exception:
                await update.message.reply_text(text)
            return
        
        # Salva o ID do canal no banco
        me.channel_id = channel_id
        db.add(me)
        db.commit()
        
        # Limpa o estado
        context.user_data.pop('waiting_for_channel_id', None)
        
        text = (
            "✅ Canal Configurado com Sucesso!\n\n"
            f"ID: `{channel_id}`\n\n"
            "🎉 Agora seus relatórios serão enviados neste canal quando você usar /relatorio"
        )
        try:
            await update.message.reply_text(text, parse_mode='Markdown')
        except Exception:
            await update.message.reply_text(text)
        
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {str(e)}")
    finally:
        db.close()


async def cmd_rotas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gerencia todas as rotas: visualiza status, rastreia ativas e deleta se necessário"""
    db = SessionLocal()
    try:
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            await update.message.reply_text(
                "⛔ *Acesso Negado*\n\n"
                "Apenas gerentes podem gerenciar rotas.",
                parse_mode='Markdown'
            )
            return
        
        # Busca todas as rotas com informações
        routes = db.query(Route).order_by(Route.created_at.desc()).all()
        
        if not routes:
            await update.message.reply_text(
                "📭 *Nenhuma Rota Cadastrada*\n\n"
                "Use /importar para criar uma nova rota primeiro!",
                parse_mode='Markdown'
            )
            return
        
        # Cria keyboard com rotas e status
        keyboard = []
        for route in routes[:30]:  # Limita a 30 rotas
            route_name = route.name or f"Rota {route.id}"
            
            # Determina status
            total_packages = db.query(Package).filter(Package.route_id == route.id).count()
            delivered_packages = db.query(Package).filter(
                Package.route_id == route.id,
                Package.status == "delivered"
            ).count()
            
            if route.assigned_to_id:
                if total_packages > 0 and delivered_packages == total_packages:
                    status_emoji = "✅"  # Concluída
                    status_text = "Concluída"
                else:
                    status_emoji = "🔴"  # Em rota
                    status_text = "Em Rota"
            else:
                status_emoji = "⚪"  # Pendente
                status_text = "Pendente"
            
            driver_name = ""
            if route.assigned_to:
                driver_name = f" - {route.assigned_to.full_name or f'ID {route.assigned_to.telegram_user_id}'}"
            
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{status_emoji} {route_name}{driver_name} ({delivered_packages}/{total_packages})",
                    callback_data=f"view_route:{route.id}"
                )
            ])
        
        await update.message.reply_text(
            "📋 *Gerenciamento de Rotas*\n\n"
            "Status:\n"
            "• ⚪ Pendente (sem motorista)\n"
            "• 🔴 Em Rota (ativo)\n"
            "• ✅ Concluída (100% entregue)\n\n"
            "Clique em uma rota para ver detalhes e opções:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        
    finally:
        db.close()


async def on_view_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para visualizar detalhes de uma rota e opções"""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    if not data.startswith("view_route:"):
        return
    
    route_id = int(data.split(":", 1)[1])
    context.user_data["view_route_id"] = route_id
    
    db = SessionLocal()
    try:
        route = db.get(Route, route_id)
        if not route:
            await query.answer("❌ Rota não encontrada!", show_alert=True)
            return
        
        route_name = route.name or f"Rota {route.id}"
        
        # Calcula informações
        total_packages = db.query(Package).filter(Package.route_id == route.id).count()
        delivered_packages = db.query(Package).filter(
            Package.route_id == route.id,
            Package.status == "delivered"
        ).count()
        failed_packages = db.query(Package).filter(
            Package.route_id == route.id,
            Package.status == "failed"
        ).count()
        pending_packages = total_packages - delivered_packages - failed_packages
        
        # Determina status
        if route.assigned_to_id:
            if total_packages > 0 and delivered_packages == total_packages:
                status = "✅ *CONCLUÍDA*"
            else:
                status = "🔴 *EM ROTA*"
        else:
            status = "⚪ *PENDENTE*"
        
        # Informações do motorista
        driver_info = ""
        if route.assigned_to:
            driver = route.assigned_to
            driver_name = driver.full_name or f"ID {driver.telegram_user_id}"
            driver_info = f"\n👤 *Motorista:* {driver_name}"
        
        # Monta mensagem
        info_text = (
            f"📦 *{route_name}*\n\n"
            f"Status: {status}\n"
            f"{driver_info}\n\n"
            f"📊 *Pacotes:*\n"
            f"• Total: {total_packages}\n"
            f"• Entregues: {delivered_packages}\n"
            f"• Falhados: {failed_packages}\n"
            f"• Pendentes: {pending_packages}\n\n"
            f"📅 Criada em: {route.created_at.strftime('%d/%m/%Y %H:%M')}"
        )
        
        # Cria keyboard com opções
        keyboard = []
        
        # ✅ FASE 4.3: Botão de finalização para rotas completed
        if route.status == "completed":
            keyboard.append([
                InlineKeyboardButton(text="✅ Finalizar Rota", callback_data=f"finalize_route:{route.id}")
            ])
        
        # Opção de rastreamento (apenas se tem motorista e não está concluída)
        if route.assigned_to_id and route.status not in ["completed", "finalized"]:
            keyboard.append([
                InlineKeyboardButton(text="🗺️ Rastrear", callback_data=f"track_view_route:{route.id}")
            ])
        
        # Opção de deletar
        keyboard.append([
            InlineKeyboardButton(text="🗑️ Excluir Rota", callback_data=f"delete_view_route:{route.id}")
        ])
        
        # Botão de voltar
        keyboard.append([
            InlineKeyboardButton(text="⬅️ Voltar", callback_data="back_to_routes")
        ])
        
        await query.edit_message_text(
            info_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        
    finally:
        db.close()


async def on_track_view_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para rastrear uma rota ativa"""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    if not data.startswith("track_view_route:"):
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
        
        track_text = (
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
            f"_Clique no link acima para abrir o mapa!_"
        )
        
        keyboard = [[InlineKeyboardButton(text="⬅️ Voltar", callback_data=f"view_route:{route.id}")]]
        
        await query.edit_message_text(
            track_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        
    finally:
        db.close()


# ✅ FASE 4.3: CALLBACKS PARA FINALIZAÇÃO DE ROTA
async def on_finalize_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para iniciar finalização de rota"""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    if not data.startswith("finalize_route:"):
        return
    
    route_id = int(data.split(":", 1)[1])
    
    db = SessionLocal()
    try:
        route = db.get(Route, route_id)
        if not route or route.status != "completed":
            await query.answer("❌ Rota não pode ser finalizada!", show_alert=True)
            return
        
        # Busca informações
        route_name = route.name or f"Rota {route.id}"
        driver = db.get(User, route.assigned_to_id) if route.assigned_to_id else None
        driver_name = driver.full_name if driver else "N/A"
        
        total_packages = db.query(Package).filter(Package.route_id == route_id).count()
        
        # Monta resumo
        summary = (
            f"📊 *Finalizar Rota*\n\n"
            f"📛 {route_name}\n"
            f"👤 Motorista: {driver_name}\n"
            f"📦 Pacotes Entregues: {total_packages}\n\n"
            f"💰 *Financeiro:*\n"
            f"✅ Receita: R$ {route.revenue:.2f}\n"
            f"💼 Salário: R$ {route.driver_salary:.2f}\n"
            f"📊 Lucro Bruto: R$ {route.revenue - route.driver_salary:.2f}\n\n"
            f"💡 Teve despesas extras nesta rota?\n"
            f"(combustível, pedágio, manutenção, etc)"
        )
        
        keyboard = [
            [InlineKeyboardButton("✅ Não, continuar", callback_data=f"finalize_no_expenses:{route_id}")],
            [InlineKeyboardButton("💸 Sim, adicionar despesas", callback_data=f"finalize_add_expenses:{route_id}")],
            [InlineKeyboardButton("📝 Adicionar receita extra", callback_data=f"finalize_add_income:{route_id}")],
            [InlineKeyboardButton("❌ Cancelar", callback_data=f"view_route:{route_id}")]
        ]
        
        await query.edit_message_text(
            summary,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        
    finally:
        db.close()


async def on_finalize_no_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback quando usuário não tem despesas extras - pede KM"""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    if not data.startswith("finalize_no_expenses:"):
        return
    
    route_id = int(data.split(":", 1)[1])
    
    # Salva route_id no contexto
    context.user_data['finalize_route_id'] = route_id
    context.user_data['finalize_extra_expenses'] = 0.0
    context.user_data['finalize_extra_income'] = 0.0
    
    await query.edit_message_text(
        "🚗 *Quantos KM você rodou hoje?*\n\n"
        "_(Considere apenas o deslocamento Ilha ↔ Rocinha)_\n\n"
        "Digite a kilometragem (ex: 45):",
        parse_mode='Markdown'
    )
    
    return FINALIZE_KM


async def on_finalize_add_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para adicionar despesas extras na finalização"""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    if not data.startswith("finalize_add_expenses:"):
        return
    
    route_id = int(data.split(":", 1)[1])
    
    # Salva route_id e inicializa lista de despesas
    context.user_data['finalize_route_id'] = route_id
    if 'finalize_expenses_list' not in context.user_data:
        context.user_data['finalize_expenses_list'] = []
    
    keyboard = [
        ['⛽ Combustível', '🅿️ Estacionamento'],
        ['🛣️ Pedágio', '🔧 Manutenção'],
        ['🚗 Outro'],
        ['✅ Finalizar (sem mais despesas)']
    ]
    
    await query.edit_message_text(
        "� *Adicionar Despesa Extra*\n\n"
        "Selecione o tipo de despesa:",
        parse_mode='Markdown'
    )
    
    # Envia teclado como mensagem nova (callbacks não suportam ReplyKeyboardMarkup)
    await update.effective_chat.send_message(
        "Escolha uma opção:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    
    return FINALIZE_EXTRA_EXPENSE_TYPE


async def on_finalize_add_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para adicionar receita extra na finalização"""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    if not data.startswith("finalize_add_income:"):
        return
    
    route_id = int(data.split(":", 1)[1])
    
    # Salva route_id
    context.user_data['finalize_route_id'] = route_id
    if 'finalize_income_list' not in context.user_data:
        context.user_data['finalize_income_list'] = []
    
    keyboard = [
        ['💵 Gorjeta', '📦 Taxa Adicional'],
        ['💰 Outro'],
        ['✅ Finalizar (sem receitas extras)']
    ]
    
    await query.edit_message_text(
        "� *Adicionar Receita Extra*\n\n"
        "Selecione o tipo de receita:",
        parse_mode='Markdown'
    )
    
    # Envia teclado como mensagem nova
    await update.effective_chat.send_message(
        "Escolha uma opção:",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    
    return FINALIZE_EXTRA_INCOME_TYPE


async def finalize_expense_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o tipo de despesa extra"""
    expense_type = update.message.text.strip()
    
    # Se usuário escolheu finalizar sem despesas
    if '✅' in expense_type or 'finalizar' in expense_type.lower():
        # Calcula total de despesas adicionadas
        expenses_list = context.user_data.get('finalize_expenses_list', [])
        total_expenses = sum(exp['amount'] for exp in expenses_list)
        context.user_data['finalize_extra_expenses'] = total_expenses
        
        # Pede KM
        await update.message.reply_text(
            "🚗 *Quantos KM você rodou hoje?*\n\n"
            "_(Considere apenas o deslocamento Ilha ↔ Rocinha)_\n\n"
            "Digite a kilometragem (ex: 45):",
            parse_mode='Markdown'
        )
        return FINALIZE_KM
    
    # Mapeia emojis para tipos
    type_map = {
        '⛽': 'combustivel',
        '🅿️': 'estacionamento',
        '🛣️': 'pedagio',
        '🔧': 'manutencao',
        '🚗': 'outro'
    }
    
    # Encontra o tipo
    expense_db_type = None
    for emoji, db_type in type_map.items():
        if emoji in expense_type:
            expense_db_type = db_type
            break
    
    if not expense_db_type:
        expense_db_type = 'outro'
    
    context.user_data['finalize_current_expense_type'] = expense_db_type
    context.user_data['finalize_current_expense_name'] = expense_type
    
    await update.message.reply_text(
        f"💸 *Despesa: {expense_type}*\n\n"
        "Qual foi o valor? (R$)\n\n"
        "_(Digite apenas números, ex: 15.50)_",
        parse_mode='Markdown'
    )
    return FINALIZE_EXTRA_EXPENSE_VALUE


async def finalize_expense_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o valor da despesa extra"""
    try:
        amount = float(update.message.text.replace(',', '.').replace('R$', '').strip())
        if amount <= 0:
            raise ValueError
        
        expense_type = context.user_data.get('finalize_current_expense_type', 'outro')
        expense_name = context.user_data.get('finalize_current_expense_name', 'Outro')
        
        # Adiciona à lista
        if 'finalize_expenses_list' not in context.user_data:
            context.user_data['finalize_expenses_list'] = []
        
        context.user_data['finalize_expenses_list'].append({
            'type': expense_type,
            'name': expense_name,
            'amount': amount
        })
        
        # Mostra resumo
        expenses_list = context.user_data['finalize_expenses_list']
        total = sum(exp['amount'] for exp in expenses_list)
        
        summary = "\n".join([f"• {exp['name']}: R$ {exp['amount']:.2f}" for exp in expenses_list])
        
        keyboard = [
            ['➕ Adicionar Mais', '✅ Continuar']
        ]
        
        await update.message.reply_text(
            f"✅ *Despesa Registrada!*\n\n"
            f"*Despesas adicionadas:*\n{summary}\n\n"
            f"💰 *Total:* R$ {total:.2f}\n\n"
            f"Deseja adicionar mais alguma despesa?",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
            parse_mode='Markdown'
        )
        return FINALIZE_EXTRA_EXPENSE_MORE
        
    except ValueError:
        await update.message.reply_text(
            "❌ Valor inválido. Digite apenas números (ex: 15.50):"
        )
        return FINALIZE_EXTRA_EXPENSE_VALUE


async def finalize_expense_more(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pergunta se há mais despesas extras"""
    resp = update.message.text.strip().lower()
    
    if 'mais' in resp or 'adicionar' in resp:
        # Volta para escolher tipo
        keyboard = [
            ['⛽ Combustível', '🅿️ Estacionamento'],
            ['🛣️ Pedágio', '🔧 Manutenção'],
            ['🚗 Outro'],
            ['✅ Finalizar (sem mais despesas)']
        ]
        
        await update.message.reply_text(
            "💸 *Adicionar Outra Despesa*\n\n"
            "Selecione o tipo:",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
            parse_mode='Markdown'
        )
        return FINALIZE_EXTRA_EXPENSE_TYPE
    else:
        # Finaliza despesas e pede KM
        expenses_list = context.user_data.get('finalize_expenses_list', [])
        total_expenses = sum(exp['amount'] for exp in expenses_list)
        context.user_data['finalize_extra_expenses'] = total_expenses
        
        await update.message.reply_text(
            "🚗 *Quantos KM você rodou hoje?*\n\n"
            "_(Considere apenas o deslocamento Ilha ↔ Rocinha)_\n\n"
            "Digite a kilometragem (ex: 45):",
            parse_mode='Markdown'
        )
        return FINALIZE_KM


async def finalize_income_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o tipo de receita extra"""
    income_type = update.message.text.strip()
    
    # Se usuário escolheu finalizar sem receitas
    if '✅' in income_type or 'finalizar' in income_type.lower():
        # Calcula total de receitas
        income_list = context.user_data.get('finalize_income_list', [])
        total_income = sum(inc['amount'] for inc in income_list)
        context.user_data['finalize_extra_income'] = total_income
        
        # Pede KM
        await update.message.reply_text(
            "🚗 *Quantos KM você rodou hoje?*\n\n"
            "_(Considere apenas o deslocamento Ilha ↔ Rocinha)_\n\n"
            "Digite a kilometragem (ex: 45):",
            parse_mode='Markdown'
        )
        return FINALIZE_KM
    
    context.user_data['finalize_current_income_name'] = income_type
    
    await update.message.reply_text(
        f"💵 *Receita: {income_type}*\n\n"
        "Qual foi o valor? (R$)\n\n"
        "_(Digite apenas números, ex: 20.00)_",
        parse_mode='Markdown'
    )
    return FINALIZE_EXTRA_INCOME_VALUE


async def finalize_income_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o valor da receita extra"""
    try:
        amount = float(update.message.text.replace(',', '.').replace('R$', '').strip())
        if amount <= 0:
            raise ValueError
        
        income_name = context.user_data.get('finalize_current_income_name', 'Receita Extra')
        
        # Adiciona à lista
        if 'finalize_income_list' not in context.user_data:
            context.user_data['finalize_income_list'] = []
        
        context.user_data['finalize_income_list'].append({
            'name': income_name,
            'amount': amount
        })
        
        # Calcula total e pede KM
        income_list = context.user_data['finalize_income_list']
        total_income = sum(inc['amount'] for inc in income_list)
        context.user_data['finalize_extra_income'] = total_income
        
        summary = "\n".join([f"• {inc['name']}: R$ {inc['amount']:.2f}" for inc in income_list])
        
        await update.message.reply_text(
            f"✅ *Receita Extra Registrada!*\n\n"
            f"*Receitas:*\n{summary}\n\n"
            f"💰 *Total:* R$ {total_income:.2f}\n\n"
            f"─────────────────\n\n"
            f"🚗 *Agora, quantos KM você rodou hoje?*\n\n"
            f"_(Considere apenas o deslocamento Ilha ↔ Rocinha)_\n\n"
            f"Digite a kilometragem (ex: 45):",
            parse_mode='Markdown'
        )
        return FINALIZE_KM
        
    except ValueError:
        await update.message.reply_text(
            "❌ Valor inválido. Digite apenas números (ex: 20.00):"
        )
        return FINALIZE_EXTRA_INCOME_VALUE


async def finalize_km_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe a kilometragem informada e finaliza a rota"""
    try:
        km = float(update.message.text.replace(',', '.').strip())
        if km < 0:
            raise ValueError
        
        route_id = context.user_data.get('finalize_route_id')
        extra_expenses = context.user_data.get('finalize_extra_expenses', 0.0)
        extra_income = context.user_data.get('finalize_extra_income', 0.0)
        
        if not route_id:
            await update.message.reply_text("❌ Erro: rota não encontrada. Use /rotas para tentar novamente.")
            return ConversationHandler.END
        
        db = SessionLocal()
        try:
            route = db.get(Route, route_id)
            if not route or route.status != "completed":
                await update.message.reply_text("❌ Rota não pode ser finalizada!")
                return ConversationHandler.END
            
            # Definir route_name antes de usar em descrições
            route_name = route.name or f"Rota {route_id}"

            # ✅ Salva KM informado
            route.calculated_km = km
            route.extra_expenses = extra_expenses
            route.extra_income = extra_income
            
            # ✅ FASE 5: Salva despesas extras no banco
            expenses_list = context.user_data.get('finalize_expenses_list', [])
            for exp in expenses_list:
                expense = Expense(
                    date=datetime.now().date(),
                    type=exp['type'],
                    description=f"{exp['name']} - Rota {route_name}",
                    amount=exp['amount'],
                    route_id=route_id,
                    confirmed=1,  # 1 = True (INTEGER)
                    created_by=update.effective_user.id
                )
                db.add(expense)
            
            # ✅ FASE 5: Salva receitas extras no banco
            income_list = context.user_data.get('finalize_income_list', [])
            for inc in income_list:
                income = Income(
                    date=datetime.now().date(),
                    description=f"{inc['name']} - Rota {route_name}",
                    amount=inc['amount'],
                    route_id=route_id,
                    created_by=update.effective_user.id
                )
                db.add(income)
            
            # ✅ Confirma a despesa de salário
            expenses = db.query(Expense).filter(
                Expense.route_id == route_id,
                Expense.confirmed == 0  # 0 = False (INTEGER)
            ).all()
            
            for expense in expenses:
                expense.confirmed = 1  # 1 = True (INTEGER)
            
            # ✅ Marca rota como finalizada
            route.status = "finalized"
            route.finalized_at = datetime.now()
            db.commit()
            
            # Busca informações para mensagem final (route_name já definido)
            driver = db.get(User, route.assigned_to_id) if route.assigned_to_id else None
            driver_name = driver.full_name if driver else "N/A"
            
            success_text = (
                f"✅ *Rota Finalizada!*\n\n"
                f"📛 {route_name}\n"
                f"👤 Motorista: {driver_name}\n"
                f"🚗 KM Rodados: {km:.1f} km\n\n"
                f"💰 *Resumo Final:*\n"
                f"✅ Receita: R$ {route.revenue:.2f}\n"
                f"💼 Salário: R$ {route.driver_salary:.2f}\n"
                f"💸 Despesas Extras: R$ {extra_expenses:.2f}\n"
                f"💵 Receitas Extras: R$ {extra_income:.2f}\n\n"
                f"📊 *Lucro Líquido:* R$ {route.revenue + extra_income - route.driver_salary - extra_expenses:.2f}\n\n"
                f"✅ Todos os registros financeiros foram confirmados!\n\n"
                f"💡 Use /relatorio para ver o resumo mensal completo."
            )
            try:
                await update.message.reply_text(success_text, parse_mode='Markdown')
            except Exception:
                await update.message.reply_text(success_text)
            
            # Limpa contexto
            context.user_data.pop('finalize_route_id', None)
            context.user_data.pop('finalize_extra_expenses', None)
            context.user_data.pop('finalize_extra_income', None)
            context.user_data.pop('finalize_expenses_list', None)
            context.user_data.pop('finalize_income_list', None)
            context.user_data.pop('finalize_current_expense_type', None)
            context.user_data.pop('finalize_current_expense_name', None)
            context.user_data.pop('finalize_current_income_name', None)
            
        finally:
            db.close()
            
    except ValueError:
        await update.message.reply_text(
            "❌ Valor inválido. Digite apenas números (ex: 45 ou 52.5):"
        )
        return FINALIZE_KM
    
    return ConversationHandler.END


async def on_finalize_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para confirmar finalização sem despesas extras"""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    if not data.startswith("finalize_confirm:"):
        return
    
    route_id = int(data.split(":", 1)[1])
    
    db = SessionLocal()
    try:
        route = db.get(Route, route_id)
        if not route or route.status != "completed":
            await query.answer("❌ Rota não pode ser finalizada!", show_alert=True)
            return
        
        # ✅ Confirma a despesa de salário
        expenses = db.query(Expense).filter(
            Expense.route_id == route_id,
            Expense.confirmed == 0  # 0 = False (INTEGER)
        ).all()
        
        for expense in expenses:
            expense.confirmed = 1  # 1 = True (INTEGER)
        
        # ✅ Marca rota como finalizada
        route.status = "finalized"
        route.finalized_at = datetime.now()
        db.commit()
        
        # Busca informações para mensagem final
        route_name = route.name or f"Rota {route_id}"
        driver = db.get(User, route.assigned_to_id) if route.assigned_to_id else None
        driver_name = driver.full_name if driver else "N/A"
        
        success_text = (
            f"✅ *Rota Finalizada!*\n\n"
            f"📛 {route_name}\n"
            f"👤 Motorista: {driver_name}\n\n"
            f"💰 *Resumo Final:*\n"
            f"✅ Receita: R$ {route.revenue:.2f}\n"
            f"💼 Salário: R$ {route.driver_salary:.2f}\n"
            f"💸 Despesas Extras: R$ {route.extra_expenses:.2f}\n"
            f"💵 Receitas Extras: R$ {route.extra_income:.2f}\n\n"
            f"📊 *Lucro Líquido:* R$ {route.revenue + route.extra_income - route.driver_salary - route.extra_expenses:.2f}\n\n"
            f"✅ Todos os registros financeiros foram confirmados!\n\n"
            f"💡 Use /relatorio para ver o resumo mensal completo."
        )
        
        keyboard = [[InlineKeyboardButton("⬅️ Voltar para Rotas", callback_data="back_to_routes")]]
        
        await query.edit_message_text(
            success_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        
    finally:
        db.close()


async def on_delete_view_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para deletar uma rota"""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    if not data.startswith("delete_view_route:"):
        return
    
    route_id = int(data.split(":", 1)[1])
    
    db = SessionLocal()
    try:
        route = db.get(Route, route_id)
        if not route:
            await query.answer("❌ Rota não encontrada!", show_alert=True)
            return
        
        route_name = route.name or f"Rota {route.id}"
        
        # Conta pacotes
        package_count = db.query(Package).filter(Package.route_id == route_id).count()
        delivered_count = db.query(Package).filter(
            Package.route_id == route_id,
            Package.status == "delivered"
        ).count()
        
        # Deleta comprovantes associados
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
        
        delete_text = (
            f"✅ *Rota Excluída!*\n\n"
            f"📦 {route_name}\n"
            f"🗑️ Foram removidos:\n"
            f"• {package_count} pacote(s)\n"
            f"• {delivered_count} entregue(s)\n\n"
            f"Use /rotas para voltar à lista de rotas."
        )
        
        keyboard = [[InlineKeyboardButton(text="📋 Ver Todas as Rotas", callback_data="back_to_routes")]]
        
        await query.edit_message_text(
            delete_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await query.answer(f"❌ Erro ao excluir: {str(e)}", show_alert=True)
    finally:
        db.close()


async def on_back_to_routes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para voltar à lista de rotas"""
    query = update.callback_query
    await query.answer()
    
    # Executa cmd_rotas diretamente passando a query
    db = SessionLocal()
    try:
        me = get_user_by_tid(db, update.effective_user.id)
        if not me or me.role != "manager":
            await query.answer("⛔ Acesso negado!", show_alert=True)
            return
        
        routes = db.query(Route).order_by(Route.created_at.desc()).all()
        
        if not routes:
            await query.edit_message_text(
                "📭 *Nenhuma Rota Cadastrada*\n\n"
                "Use /importar para criar uma nova rota!",
                parse_mode='Markdown'
            )
            return
        
        keyboard = []
        for route in routes[:30]:
            route_name = route.name or f"Rota {route.id}"
            
            total_packages = db.query(Package).filter(Package.route_id == route.id).count()
            delivered_packages = db.query(Package).filter(
                Package.route_id == route.id,
                Package.status == "delivered"
            ).count()
            
            if route.assigned_to_id:
                if total_packages > 0 and delivered_packages == total_packages:
                    status_emoji = "✅"
                    status_text = "Concluída"
                else:
                    status_emoji = "🔴"
                    status_text = "Em Rota"
            else:
                status_emoji = "⚪"
                status_text = "Pendente"
            
            driver_name = ""
            if route.assigned_to:
                driver_name = f" - {route.assigned_to.full_name or f'ID {route.assigned_to.telegram_user_id}'}"
            
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{status_emoji} {route_name}{driver_name} ({delivered_packages}/{total_packages})",
                    callback_data=f"view_route:{route.id}"
                )
            ])
        
        await query.edit_message_text(
            "📋 *Gerenciamento de Rotas*\n\n"
            "Status:\n"
            "• ⚪ Pendente (sem motorista)\n"
            "• 🔴 Em Rota (ativo)\n"
            "• ✅ Concluída (100% entregue)\n\n"
            "Clique em uma rota para ver detalhes e opções:",
            reply_markup=InlineKeyboardMarkup(keyboard),
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
            except Exception as e:
                logger.error(
                    f"Falha ao enviar mensagem para motorista {driver_tid}",
                    exc_info=True,
                    extra={
                        "driver_telegram_id": driver_tid,
                        "route_id": route.id,
                        "route_name": route_name,
                        "error": str(e)
                    }
                )
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
    
    # Criar keyboard com botões de seleção
    keyboard = []
    for r in routes[:25]:
        route_name = r.name or 'Rota'
        keyboard.append([
            InlineKeyboardButton(text=f"📦 {route_name} (ID {r.id})", callback_data=f"sel_route:{r.id}")
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
        
        # ✅ FASE 4.1: Calcula salário automaticamente (100 ou 150)
        today = datetime.now().date()
        routes_today = db.query(Route).filter(
            Route.assigned_to_id == driver.id,
            func.date(Route.created_at) == today,
            Route.status.in_(["in_progress", "completed", "finalized"])
        ).count()
        
        # Primeira rota = 100, segunda+ = 50
        driver_salary = 100.0 if routes_today == 0 else 50.0
        
        # Atualiza rota
        route.assigned_to_id = driver.id
        route.driver_salary = driver_salary
        route.status = "in_progress"
        
        # ✅ FASE 4.1: Cria Expense do salário (pendente de confirmação)
        me = get_user_by_tid(db, update.effective_user.id)
        expense = Expense(
            date=today,
            type="salario",
            description=f"Salário - {driver.full_name or f'ID {driver_tid}'} - {route.name or f'Rota {route.id}'}",
            amount=driver_salary,
            employee_name=driver.full_name or f"ID {driver_tid}",
            route_id=route.id,
            confirmed=0,  # ✅ Só confirma quando finalizar a rota (0 = False, 1 = True)
            created_by=me.telegram_user_id if me else update.effective_user.id
        )
        db.add(expense)
        
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
            f"📊 *Pacotes:* {count}\n"
            f"💼 *Salário:* R$ {driver_salary:.2f} ({'1ª rota do dia' if driver_salary == 100 else '2ª+ rota'})\n\n"
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
                f"� *Financeiro:*\n"
                f"💵 Receita: R$ {route.revenue:.2f}\n"
                f"💼 Salário: R$ {driver_salary:.2f}\n"
                f"📊 Lucro Bruto: R$ {route.revenue - driver_salary:.2f}\n\n"
                f"�🗺️ *Link de Rastreamento:*\n"
                f"{link}\n\n"
                f"💡 _Use este link para acompanhar em tempo real!_",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(
                f"Falha ao enviar rota {route.id} para motorista {driver_tid}",
                exc_info=True,
                extra={
                    "route_id": route.id,
                    "driver_telegram_id": driver_tid,
                    "route_name": route_name,
                    "error": str(e)
                }
            )
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
        "📥 *Importar Nova Rota*\n\n"
        "📂 *Envie o arquivo da planilha*\n\n"
        "Formatos aceitos: Excel (.xlsx) ou CSV (.csv)\n\n"
        "*Colunas necessárias:*\n"
        "• AT ID (nome da rota - obrigatório)\n"
        "• Código de Rastreio (obrigatório)\n"
        "• Endereço (obrigatório)\n"
        "• Latitude (opcional)\n"
        "• Longitude (opcional)\n"
        "• Bairro (opcional)\n\n"
        "💡 _O sistema reconhece automaticamente os nomes das colunas._",
        parse_mode='Markdown'
    )
    return IMPORT_WAITING_FILE


# ✅ FUNÇÃO REMOVIDA: Nome da rota agora é detectado automaticamente da coluna AT ID
# async def handle_route_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """[DEPRECATED] Recebe o nome da rota e pede o arquivo"""
#     # Essa função não é mais necessária pois o nome é detectado da coluna AT ID da planilha


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

    # ✅ FASE 3.2: FEEDBACK IMEDIATO
    await update.message.chat.send_action(action=ChatAction.UPLOAD_DOCUMENT)
    processing_msg = await update.message.reply_text(
        "⏳ *Processando arquivo...*\n\n"
        "📥 Baixando e analisando dados...",
        parse_mode='Markdown'
    )
    
    file = await doc.get_file()
    local_path = IMPORTS_DIR / filename
    await file.download_to_drive(local_path)

    # ✅ FASE 3.2: PARSE COM RELATÓRIO (robusto)
    try:
        if suffix == ".xlsx":
            df = pd.read_excel(local_path)
        else:
            # CSV: tenta UTF-8 e fallback latin-1
            try:
                df = pd.read_csv(local_path)
            except Exception:
                df = pd.read_csv(local_path, encoding="latin-1", sep=",")
    except Exception as read_err:
        try:
            await processing_msg.edit_text(
                "❌ *Erro ao Ler Arquivo*\n\n"
                "Não consegui abrir a planilha. Verifique o formato/codificação e tente novamente.\n\n"
                f"Detalhes: `{str(read_err)[:200]}`",
                parse_mode='Markdown'
            )
        except Exception:
            await processing_msg.edit_text(
                "Erro ao ler arquivo. Detalhes: " + str(read_err)[:200]
            )
        return ConversationHandler.END
    items, report = parse_import_dataframe(df)
    
    if not items:
        await processing_msg.edit_text(
            "❌ *Erro ao Processar*\n\n"
            "Não encontrei dados válidos no arquivo.\n\n"
            "Verifique se o arquivo possui:\n"
            "• Pelo menos uma coluna com códigos de rastreio\n"
            "• Dados nas linhas (não apenas cabeçalhos)",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    # ✅ FASE 3.2: PREVIEW COM ESTATÍSTICAS
    # Calcula estatísticas
    with_coords = sum(1 for i in items if i.get('latitude') and i.get('longitude'))
    with_address = sum(1 for i in items if i.get('address'))
    with_neighborhood = sum(1 for i in items if i.get('neighborhood'))
    
    # Monta mensagem de preview
    route_name = report.get('route_name', 'Nome não detectado')
    preview_text = (
        f"📊 *Análise da Planilha*\n\n"
        f"📁 Arquivo: `{filename}`\n"
        f"📛 Rota: `{route_name}`\n\n"
        f"*Colunas Detectadas:*\n"
    )
    
    # Mostra colunas encontradas com emojis
    emoji_map = {
        'route_id': '🆔',
        'tracking': '📦',
        'address': '🏠',
        'neighborhood': '🗺️',
        'latitude': '📍',
        'longitude': '📍'
    }
    
    for field, col_name in report['columns_found'].items():
        emoji = emoji_map.get(field, '•')
        preview_text += f"{emoji} {field}: `{col_name}`\n"
    
    if report['columns_missing']:
        preview_text += f"\n⚠️ *Não Encontradas:* `{', '.join(report['columns_missing'])}`\n"
    
    preview_text += (
        f"\n📊 *Estatísticas:*\n"
        f"📦 Total de Pacotes: *{len(items)}*\n"
        f"✅ Válidos: {report['rows_valid']}\n"
    )
    
    if report['rows_skipped'] > 0:
        preview_text += f"❌ Ignorados: {report['rows_skipped']}\n"
    
    # Estatísticas de dados
    coord_percent = (with_coords / len(items) * 100) if items else 0
    addr_percent = (with_address / len(items) * 100) if items else 0
    
    preview_text += (
        f"\n*Qualidade dos Dados:*\n"
        f"📍 Com Coordenadas: {with_coords} ({coord_percent:.0f}%)\n"
        f"🏠 Com Endereço: {with_address} ({addr_percent:.0f}%)\n"
        f"🗺️ Com Bairro: {with_neighborhood} ({with_neighborhood/len(items)*100:.0f}%)\n"
    )
    
    # ✅ FASE 3.3: AVISOS SOBRE QUALIDADE
    if coord_percent < 50:
        preview_text += (
            f"\n⚠️ *Atenção:* Menos de 50% dos pacotes têm coordenadas.\n"
            f"Isso dificultará a otimização da rota.\n"
        )
    
    if addr_percent < 80:
        preview_text += (
            f"\n⚠️ *Atenção:* {100-addr_percent:.0f}% dos pacotes não têm endereço completo.\n"
        )
    
    # Mostra primeiros pacotes como exemplo
    preview_text += f"\n🔍 *Primeiros Pacotes (exemplo):*\n"
    for i, item in enumerate(items[:3], 1):
        has_coord = "✅" if (item.get('latitude') and item.get('longitude')) else "❌"
        addr_text = item.get('address', '❌ Sem endereço')
        if addr_text is None:
            addr_text = '❌ Sem endereço'
        preview_text += (
            f"\n{i}. `{item['tracking_code']}`\n"
            f"   🏠 `{addr_text[:30]}...`\n"
            f"   📍 Coordenadas: {has_coord}\n"
        )
    
    if len(report['warnings']) > 0:
        preview_text += f"\n⚠️ {len(report['warnings'])} avisos detectados\n"
        if len(report['warnings']) <= 5:
            preview_text += "\n*Avisos:*\n"
            for warning in report['warnings'][:5]:
                preview_text += f"• `{warning}`\n"
        else:
            preview_text += f"_(Mostrando primeiros 5 de {len(report['warnings'])})_\n"
            for warning in report['warnings'][:5]:
                preview_text += f"• `{warning}`\n"
    
    preview_text += f"\n💡 Deseja importar esses {len(items)} pacotes?"
    
    # ✅ FASE 3.2: BOTÕES DE CONFIRMAÇÃO
    keyboard = [
        [
            InlineKeyboardButton("✅ Sim, Importar", callback_data=f"import_confirm"),
            InlineKeyboardButton("❌ Cancelar", callback_data="import_cancel")
        ]
    ]
    
    try:
        await processing_msg.edit_text(
            preview_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    except Exception as e:
        # Fallback caso alguma entidade quebre o Markdown
        safe_text = preview_text.replace("*", "").replace("_", "").replace("`", "")
        await processing_msg.edit_text(
            safe_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # Salva dados no context para usar no callback
    context.user_data['pending_import'] = {
        'items': items,
        'report': report,
        'filename': filename
    }
    
    return IMPORT_CONFIRMING  # Novo estado


# ✅ FASE 3.2: CALLBACKS PARA CONFIRMAÇÃO DE IMPORTAÇÃO
async def on_import_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para confirmar importação após preview"""
    query = update.callback_query
    await query.answer()
    
    # Recupera dados do context
    pending = context.user_data.get('pending_import')
    if not pending:
        await query.edit_message_text(
            "❌ *Sessão Expirada*\n\n"
            "Os dados da importação não estão mais disponíveis.\n"
            "Use /importar novamente.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    
    items = pending['items']
    report = pending['report']
    
    # Atualiza mensagem para mostrar progresso
    await query.edit_message_text(
        "⏳ *Importando Pacotes...*\n\n"
        f"📦 Salvando {len(items)} pacotes no banco de dados...",
        parse_mode='Markdown'
    )
    
    db = SessionLocal()
    try:
        # ✅ Pega o nome da rota detectado automaticamente da planilha (AT ID)
        route_name = report.get('route_name') or f"Rota {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        
        # ✅ FASE 4.1: Cria rota com receita padrão e status pending
        route = Route(
            name=route_name,
            revenue=260.0,
            status="pending"
        )
        db.add(route)
        db.flush()
        
        # ✅ FASE 4.1: Cria Income automaticamente
        me = get_user_by_tid(db, update.effective_user.id)
        income = Income(
            date=datetime.now().date(),
            amount=260.0,
            route_id=route.id,
            description=f"Receita da rota: {route_name}",
            created_by=me.telegram_user_id if me else update.effective_user.id
        )
        db.add(income)
        
        # Adiciona pacotes em batch para melhor performance
        packages = []
        for it in items:
            packages.append(
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
        
        db.add_all(packages)
        db.commit()
        
        # ✅ FASE 4.1: MENSAGEM FINAL COM RECEITA AUTOMÁTICA
        success_text = (
            f"✅ Pacotes Importados com Sucesso!\n\n"
            f"ID da Rota: {route.id}\n"
            f"Nome: {route_name}\n"
            f"Total de Pacotes: {len(items)}\n"
            f"Receita: R$ {route.revenue:.2f} (registrada automaticamente)\n\n"
        )
        
        # Adiciona estatísticas de qualidade
        with_coords = sum(1 for i in items if i.get('latitude') and i.get('longitude'))
        with_address = sum(1 for i in items if i.get('address'))
        
        success_text += (
            f"*Qualidade dos Dados:*\n"
            f"📍 Com Coordenadas: {with_coords}/{len(items)} ({with_coords/len(items)*100:.0f}%)\n"
            f"🏠 Com Endereço: {with_address}/{len(items)} ({with_address/len(items)*100:.0f}%)\n\n"
        )
        
        if report['rows_skipped'] > 0:
            success_text += f"⚠️ {report['rows_skipped']} linha(s) foram ignoradas\n\n"
        
        success_text += (
            f"💡 *Próximos Passos:*\n"
            f"1. Use /enviarrota para atribuir a um motorista\n"
            f"2. A rota será otimizada automaticamente\n"
            f"3. O motorista receberá o mapa interativo"
        )
        
        try:
            await query.edit_message_text(
                success_text,
                parse_mode='Markdown'
            )
        except Exception:
            await query.edit_message_text(success_text)
        
        # Limpa dados do context
        context.user_data.pop('pending_import', None)
        context.user_data.pop('route_name', None)
        
        return ConversationHandler.END
        
    except Exception as e:
        db.rollback()
        logger.error(f"Erro ao importar pacotes: {str(e)}", exc_info=True)
        try:
            await query.edit_message_text(
                f"❌ Erro ao Importar\n\n"
                f"Detalhes: {str(e)}\n\n"
                f"Tente novamente com /importar"
            )
        except Exception:
            await query.edit_message_text("Erro ao importar. Tente novamente com /importar")
        return ConversationHandler.END
    finally:
        db.close()


async def on_import_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback para cancelar importação"""
    query = update.callback_query
    await query.answer()
    
    # Limpa dados do context
    context.user_data.pop('pending_import', None)
    
    await query.edit_message_text(
        "❌ *Importação Cancelada*\n\n"
        "Nenhum pacote foi importado.\n\n"
        "💡 Use /importar para tentar novamente.",
        parse_mode='Markdown'
    )
    
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


# ==================== FLUXO RÁPIDO: INSUCESSO NA ENTREGA ====================
async def fail_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text(
            "⚠️ *Foto Necessária*\n\nEnvie uma foto do pacote/local para registrar o insucesso.",
            parse_mode='Markdown'
        )
        return FAIL_PHOTO
    photo = update.message.photo[-1]
    context.user_data["fail_photo_id"] = photo.file_id
    await update.message.reply_text(
        "📝 *Observação*\n\nDescreva brevemente o motivo do insucesso (ex.: destinatário ausente, endereço incorreto).",
        parse_mode='Markdown'
    )
    return FAIL_NOTES


async def fail_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notes = (update.message.text or "").strip()
    context.user_data["fail_notes"] = notes or "Insucesso - sem observação"

    pkg_id = context.user_data.get("fail_package_id")
    if not pkg_id:
        await update.message.reply_text(
            "❌ *Erro Interno*\n\nNão foi possível identificar o pacote.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    db = SessionLocal()
    try:
        package = db.get(Package, int(pkg_id))
        if not package:
            await update.message.reply_text("❌ Pacote não encontrado.")
            return ConversationHandler.END

        driver = get_user_by_tid(db, update.effective_user.id)
        proof = DeliveryProof(
            package_id=package.id,
            driver_id=driver.id if driver else None,
            receiver_name="INSUCESSO",
            receiver_document="-",
            notes=context.user_data.get("fail_notes"),
            photo1_path=context.user_data.get("fail_photo_id"),
            photo2_path=None,
        )
        db.add(proof)
        package.status = "failed"
        db.commit()

        # Atualiza status da rota se não houver mais pendentes
        route_id = package.route_id
        total = db.query(Package).filter(Package.route_id == route_id).count()
        delivered = db.query(Package).filter(Package.route_id == route_id, Package.status == "delivered").count()
        failed = db.query(Package).filter(Package.route_id == route_id, Package.status == "failed").count()
        remaining = max(0, total - delivered - failed)
        if total > 0 and remaining == 0:
            r = db.query(Route).filter(Route.id == route_id).first()
            if r:
                r.status = "completed"
                r.completed_at = datetime.now()
                db.commit()

        driver_name = driver.full_name or f"ID {driver.telegram_user_id}" if driver else "N/A"
        await update.message.reply_text(
            "❌ *Insucesso registrado!*\n\nO pacote foi marcado como *falha na entrega*.",
            parse_mode='Markdown'
        )

        # Notifica canal do motorista, se existir
        if driver and driver.channel_id:
            try:
                await context.bot.send_message(
                    chat_id=driver.channel_id,
                    text=(
                        f"❌ Insucesso de Entrega\n\n"
                        f"Motorista: {driver_name}\n"
                        f"Pacote: {package.tracking_code}\n"
                        f"Endereço: {package.address or '-'}\n"
                        f"Bairro: {package.neighborhood or '-'}\n"
                        f"Motivo: {context.user_data.get('fail_notes')}\n"
                        f"Data/Hora: {datetime.now().strftime('%d/%m/%Y às %H:%M')}"
                    )
                )
                if context.user_data.get("fail_photo_id"):
                    try:
                        await context.bot.send_photo(chat_id=driver.channel_id, photo=context.user_data["fail_photo_id"], caption="Insucesso - Foto")
                    except Exception:
                        pass
            except Exception:
                pass

        # Opcional: notificar gerentes
        try:
            await notify_managers(
                f"❌ Insucesso registrado para pacote {package.tracking_code} (rota {route_id}). Motivo: {context.user_data.get('fail_notes')}",
                context
            )
        except Exception:
            pass

    finally:
        db.close()
        # Limpa dados do fluxo de falha
        context.user_data.pop("fail_package_id", None)
        context.user_data.pop("fail_photo_id", None)
        context.user_data.pop("fail_notes", None)

    return ConversationHandler.END


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
    
    # ✅ FASE 2.1: CONFIRMAÇÃO INSTANTÂNEA
    # Confirma recebimento dos dados IMEDIATAMENTE (< 500ms)
    await update.message.reply_text(
        "✅ *Dados Recebidos!*\n\n"
        "📦 Processando entrega...\n"
        "⏳ _Isso pode levar alguns segundos_",
        parse_mode='Markdown',
        reply_markup=ReplyKeyboardRemove()
    )
    
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

    # ✅ FASE 2.2: UMA ÚNICA CONEXÃO AO BANCO
    db = SessionLocal()
    try:
        # ✅ FASE 2.2: MOSTRA PREVIEW DOS DADOS ANTES DE SALVAR
        driver = get_user_by_tid(db, update.effective_user.id)
        
        # Extrai dados do context
        receiver_name_val = context.user_data.get("receiver_name", "Não informado")
        receiver_document_val = context.user_data.get("receiver_document", "Não informado")
        notes_val = context.user_data.get("notes", "Nenhuma")
        mass_list = context.user_data.get("mass_photos") or []
        
        # Preview com resumo
        if pkg_ids:
            packages = db.query(Package).filter(Package.id.in_(pkg_ids)).all()
            num_packages = len(packages) if packages else 0
            preview_text = (
                f"📋 *Resumo da Entrega em Grupo*\n\n"
                f"📦 Pacotes: {num_packages}\n"
                f"👤 Recebedor: {receiver_name_val}\n"
                f"📄 Documento: {receiver_document_val}\n"
                f"📸 Fotos: {len(mass_list) if mass_list else '2 fotos'}\n"
                f"💬 Observações: {notes_val}\n\n"
                f"⏳ Salvando no banco de dados..."
            )
        else:
            package = db.get(Package, int(pkg_id))
            tracking = package.tracking_code if package and hasattr(package, 'tracking_code') else f"ID {pkg_id}"
            preview_text = (
                f"📋 *Resumo da Entrega*\n\n"
                f"📦 Pacote: {tracking}\n"
                f"👤 Recebedor: {receiver_name_val}\n"
                f"📄 Documento: {receiver_document_val}\n"
                f"💬 Observações: {notes_val}\n\n"
                f"⏳ Salvando no banco de dados..."
            )
        
        preview_msg = await update.message.reply_text(
            preview_text,
            parse_mode='Markdown'
        )
        
        # Persistimos ao menos a primeira foto de pacote (unitário ou em massa) + foto do local
        p1_for_db = context.user_data.get("photo1_file_id")
        if not p1_for_db and mass_list:
            p1_for_db = mass_list[0]

        route_id = None
        delivered_ids: list[int] = []
        delivered_codes: list[str] = []
        primary_addr: str | None = None
        primary_neighborhood: str | None = None

        if pkg_ids:
            # Entrega em grupo
            packages = db.query(Package).filter(Package.id.in_(pkg_ids)).all()
            if not packages:
                await preview_msg.edit_text(
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
                await preview_msg.edit_text(
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
            except AttributeError as e:
                logger.error(
                    f"Pacote {package.id} não tem tracking_code",
                    exc_info=True,
                    extra={"package_id": package.id}
                )
                delivered_codes = []
            db.commit()
        
        # ✅ FASE 2.2: CALCULA PROGRESSO NA MESMA CONEXÃO (não abre db_progress separado)
        # Calcula progresso da rota na mesma transação
        route_name = None
        total_packages = 0
        delivered_packages = 0
        remaining_packages = 0
        
        if route_id is not None:
            try:
                route_obj = db.query(Route).filter(Route.id == route_id).first()
                route_name = route_obj.name if route_obj and route_obj.name else f"Rota {route_id}"
                
                total_packages = db.query(Package).filter(Package.route_id == route_id).count()
                delivered_packages = db.query(Package).filter(
                    Package.route_id == route_id,
                    Package.status == "delivered"
                ).count()
                failed_packages = db.query(Package).filter(
                    Package.route_id == route_id,
                    Package.status == "failed"
                ).count()
                remaining_packages = max(0, total_packages - delivered_packages - failed_packages)
                
                # ✅ FASE 4.2: DETECÇÃO AUTOMÁTICA DE ROTA COMPLETA (sem pendências)
                if total_packages > 0 and remaining_packages == 0:
                    # Todos os pacotes estão concluídos (entregues ou insucesso)
                    route_obj.status = "completed"
                    route_obj.completed_at = datetime.now()
                    db.commit()
                    
                    logger.info(
                        f"Rota {route_id} automaticamente marcada como completa",
                        extra={
                            "route_id": route_id,
                            "route_name": route_name,
                            "total_packages": total_packages,
                            "driver_id": driver.id if driver else None
                        }
                    )
                
            except Exception:
                route_name = f"Rota {route_id}"
        
        # ✅ FASE 2.2: PREPARA DADOS PARA NOTIFICAÇÃO (antes de fechar conexão)
        receiver_name = receiver_name_val or '-'
        receiver_doc = receiver_document_val or '-'
        notes = notes_val or '-'
        driver_name = driver.full_name or f"ID {driver.telegram_user_id}"
        route_name = route_name or (f"Rota {route_id}" if route_id is not None else "Rota")

    except Exception as e:
        # ✅ FASE 2.3: FEEDBACK DE ERRO DETALHADO
        await preview_msg.edit_text(
            f"❌ *Erro ao Finalizar*\n\n"
            f"Detalhes: {str(e)}\n\n"
            f"💡 Use /entregar novamente",
            parse_mode='Markdown'
        )
        logger.error(f"Erro em finalize_delivery: {str(e)}", exc_info=True)
        return ConversationHandler.END
    finally:
        db.close()
    
    # ✅ FASE 4.2: NOTIFICA GERENTES SE ROTA FOI COMPLETADA
    if route_id and remaining_packages == 0 and total_packages > 0:
        # Abre nova sessão para buscar dados atualizados da rota
        db_notify = SessionLocal()
        try:
            route_complete = db_notify.get(Route, route_id)
            if route_complete and route_complete.status == "completed":
                notify_text = (
                    f"🎉 *Rota Completa!*\n\n"
                    f"📛 {route_complete.name or f'Rota {route_id}'}\n"
                    f"👤 Motorista: {driver_name}\n"
                    f"📦 {total_packages} pacotes entregues\n\n"
                    f"💰 *Resumo Financeiro:*\n"
                    f"💵 Receita: R$ {route_complete.revenue:.2f}\n"
                    f"💼 Salário: R$ {route_complete.driver_salary:.2f}\n"
                    f"📊 Lucro Bruto: R$ {route_complete.revenue - route_complete.driver_salary:.2f}\n\n"
                    f"💡 Use /rotas para finalizar e adicionar despesas extras."
                )
                await notify_managers(notify_text, context)
        finally:
            db_notify.close()
    
    # ✅ FASE 2.3: NOTIFICAÇÃO COM DADOS CONSOLIDADOS
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
                
                # ✅ FASE 2.2: REUTILIZA MESMA CONEXÃO PARA PROGRESSO
                # Envia progresso após as fotos para os managers
                for m in managers:
                    try:
                        await context.bot.send_message(
                            chat_id=m.telegram_user_id,
                            text=progress_message
                        )
                    except Exception:
                        pass

    # ✅ FASE 2.3: MENSAGEM FINAL DETALHADA COM SUCESSO
    # Atualiza mensagem de preview para sucesso final
    await preview_msg.edit_text(
        f"✅ *Entrega Finalizada!*\n\n"
        f"📦 Pacote{'s' if pkg_ids else ''}: {', '.join(delivered_codes[:3]) if delivered_codes else '-'}\n"
        f"👤 Recebedor: {receiver_name}\n"
        f"📍 Local: {primary_addr or '-'}\n"
        f"⏰ Horário: {datetime.now().strftime('%H:%M')}\n\n"
        f"✉️ Gerentes notificados com sucesso!",
        parse_mode='Markdown'
    )
    
    # Monta link do mapa interativo para continuar a rota
    map_url = None
    try:
        if route_id is not None and driver and getattr(driver, "telegram_user_id", None):
            map_url = f"{BASE_URL}/map/{route_id}/{driver.telegram_user_id}"
    except Exception:
        map_url = None

    # ✅ FASE 2.3: BOTÃO PARA CONTINUAR (não repetir mensagem)
    # Botão rápido (opcional) para abrir o mapa
    if map_url:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="🗺️ *Próxima Entrega*\n\n"
                     f"📊 Progresso: {delivered_packages}/{total_packages} ({(delivered_packages/total_packages*100 if total_packages > 0 else 0):.0f}%)\n\n"
                     "Abra o mapa para continuar:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗺️ Abrir Mapa", url=map_url)]
                ]),
                parse_mode='Markdown'
            )
        except Exception:
            pass
    
    context.user_data.clear()
    return ConversationHandler.END


# ===== FINANCIAL SYSTEM (MANAGERS ONLY) =====

# ❌ REMOVIDO: Funções do fluxo /registrardia (obsoleto após 100% automação)
# Total: ~600 linhas comentadas
# Funções removidas: fin_start, fin_km, fin_fuel_yn, fin_fuel_type, fin_fuel_liters,
# fin_fuel_amount, fin_income, fin_salary_yn, fin_salary_name, fin_salary_amount,
# fin_salary_more, fin_expenses, fin_expense_category, fin_expense_amount,
# fin_expense_more, fin_notes
# Motivo: 100% automação via finalização de rotas torna registro manual desnecessário


# ==================== GERENCIAR REGISTROS FINANCEIROS ====================

async def cmd_meus_registros(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lista todos os registros financeiros do manager com opções de editar/excluir"""
    db = SessionLocal()
    try:
        user = get_user_by_tid(db, update.effective_user.id)
        if not user or user.role != "manager":
            await update.message.reply_text(
                "⛔ *Acesso Negado*\n\n"
                "Apenas gerentes podem gerenciar registros.",
                parse_mode='Markdown'
            )
            return
        
        # Busca TODAS as datas que têm registros financeiros (Mileage, Expense, Income)
        now = datetime.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Busca datas em Mileage, Expense e Income
        mileage_dates = db.query(Mileage.date).filter(
            Mileage.date >= month_start.date(),
            Mileage.created_by == (user.telegram_user_id if user else update.effective_user.id)
        ).all()
        
        expense_dates = db.query(Expense.date).filter(
            Expense.date >= month_start.date(),
            Expense.created_by == (user.telegram_user_id if user else update.effective_user.id)
        ).all()
        
        income_dates = db.query(Income.date).filter(
            Income.date >= month_start.date(),
            Income.created_by == (user.telegram_user_id if user else update.effective_user.id)
        ).all()
        
        # Combina todas as datas únicas
        all_dates = set()
        for date_tuple in mileage_dates + expense_dates + income_dates:
            all_dates.add(date_tuple[0])
        
        if not all_dates:
            await update.message.reply_text(
                "📭 *Nenhum Registro Encontrado*\n\n"
                "Você não tem registros financeiros neste mês.\n\n"
                "Finalize rotas para criar registros automáticos!",
                parse_mode='Markdown'
            )
            return
        
        # Ordena datas em ordem decrescente
        sorted_dates = sorted(all_dates, reverse=True)
        
        # Cria keyboard com datas dos registros
        keyboard = []
        for record_date in sorted_dates[:30]:  # Limita a 30
            date_str = record_date.strftime("%d/%m/%Y")
            
            # Busca dados associados a essa data
            mileage_day = db.query(Mileage).filter(
                Mileage.date == record_date,
                Mileage.created_by == user.id
            ).first()
            
            expenses_day = db.query(Expense).filter(
                Expense.date == record_date,
                Expense.created_by == user.id
            ).all()
            
            income_day = db.query(Income).filter(
                Income.date == record_date,
                Income.created_by == user.id
            ).all()
            
            total_income = sum(inc.amount for inc in income_day)
            total_expenses = sum(exp.amount for exp in expenses_day)
            balance = total_income - total_expenses
            
            # Determina emoji baseado no balance
            emoji = "💚" if balance >= 0 else "❌"
            
            # Se tem Mileage, usa o ID dele; senão, cria um ID virtual com a data
            if mileage_day:
                callback_id = f"view_fin_record:{mileage_day.id}"
            else:
                # Cria ID virtual: "date_YYYYMMDD"
                callback_id = f"view_fin_record_by_date:{record_date.strftime('%Y%m%d')}"
            
            keyboard.append([
                InlineKeyboardButton(
                    text=f"{emoji} {date_str} - R$ {balance:,.2f}",
                    callback_data=callback_id
                )
            ])
        
        await update.message.reply_text(
            "📋 *Meus Registros Financeiros*\n\n"
            "Selecione um dia para visualizar, editar ou excluir:\n\n"
            "💚 = Lucro | ❌ = Prejuízo",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        
    finally:
        db.close()


async def on_view_fin_record(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Visualiza detalhes de um registro financeiro com opções"""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    
    # Suporta dois formatos: por ID de Mileage ou por data
    if data.startswith("view_fin_record:"):
        mileage_id = int(data.split(":", 1)[1])
        db = SessionLocal()
        try:
            mileage = db.get(Mileage, mileage_id)
            if not mileage:
                await query.answer("❌ Registro não encontrado!", show_alert=True)
                return
            record_date = mileage.date
            user_id = mileage.created_by
        finally:
            db.close()
    elif data.startswith("view_fin_record_by_date:"):
        date_str = data.split(":", 1)[1]
        record_date = datetime.strptime(date_str, "%Y%m%d").date()
        # Usa o Telegram ID do usuário atual para filtrar registros do próprio gerente
        user_id = update.effective_user.id
    else:
        return
    
    db = SessionLocal()
    try:
        # Busca dados do dia
        expenses_day = db.query(Expense).filter(
            Expense.date == record_date,
            Expense.created_by == user_id
        ).all()
        
        income_day = db.query(Income).filter(
            Income.date == record_date,
            Income.created_by == user_id
        ).all()
        
        mileage_day = db.query(Mileage).filter(
            Mileage.date == record_date,
            Mileage.created_by == user_id
        ).first()
        
        total_income = sum(inc.amount for inc in income_day)
        total_expenses = sum(exp.amount for exp in expenses_day)
        balance = total_income - total_expenses
        
        # Monta detalhes
        details = f"📊 *Registro - {record_date.strftime('%d/%m/%Y')}*\n\n"
        
        if mileage_day:
            details += f"🚗 *KM Rodados:* {mileage_day.km_total} km\n\n"
        else:
            details += f"🚗 *KM Rodados:* Não registrado\n\n"
        
        # Combustível
        fuel_expenses = [e for e in expenses_day if e.type == 'combustivel']
        if fuel_expenses:
            details += f"⛽ *Combustível:*\n"
            for exp in fuel_expenses:
                details += f"  • {exp.description}: R$ {exp.amount:.2f}\n"
            details += "\n"
        
        # Renda
        if income_day:
            details += f"💰 *Ganhos:*\n"
            for inc in income_day:
                details += f"  • {inc.description}: R$ {inc.amount:.2f}\n"
            details += f"  *Subtotal:* R$ {total_income:.2f}\n\n"
        else:
            details += f"💰 *Ganhos:* R$ 0.00\n\n"
        
        # Salários
        salary_expenses = [e for e in expenses_day if e.type == 'salario']
        if salary_expenses:
            details += f"👤 *Salários:*\n"
            for exp in salary_expenses:
                details += f"  • {exp.employee_name}: R$ {exp.amount:.2f}\n"
        
        # Outras despesas
        other_expenses = [e for e in expenses_day if e.type not in ['combustivel', 'salario']]
        if other_expenses:
            details += f"🛠️ *Outras Despesas:*\n"
            for exp in other_expenses:
                details += f"  • {exp.description}: R$ {exp.amount:.2f}\n"
        
        details += f"\n💸 *Total Despesas:* R$ {total_expenses:.2f}\n"
        details += f"📈 *Saldo:* R$ {balance:.2f}"
        if balance < 0:
            details += " ⚠️"
        
        if mileage_day and mileage_day.notes:
            details += f"\n\n📝 *Observações:* {mileage_day.notes}"
        
        # Keyboard com opções
        if mileage_day:
            mileage_id = mileage_day.id
            edit_callback = f"edit_fin_record:{mileage_id}"
            delete_callback = f"delete_fin_record:{mileage_id}"
        else:
            # Para registros sem Mileage, usa a data
            date_str = record_date.strftime("%Y%m%d")
            edit_callback = f"edit_fin_record_date:{date_str}"
            delete_callback = f"delete_fin_record_date:{date_str}"
        
        keyboard = [
            [InlineKeyboardButton(text="✏️ Editar", callback_data=edit_callback)],
            [InlineKeyboardButton(text="🗑️ Excluir", callback_data=delete_callback)],
            [InlineKeyboardButton(text="⬅️ Voltar", callback_data="back_to_fin_records")]
        ]
        
        await query.edit_message_text(
            details,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        
    finally:
        db.close()


async def on_edit_fin_record(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia edição de um registro - mostra opções do que editar"""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    if not data.startswith("edit_fin_record:"):
        return
    
    mileage_id = int(data.split(":", 1)[1])
    context.user_data['edit_fin_record_id'] = mileage_id
    
    keyboard = [
        [InlineKeyboardButton(text="🚗 KM Rodados", callback_data=f"edit_fin_km:{mileage_id}")],
        [InlineKeyboardButton(text="⛽ Combustível", callback_data=f"edit_fin_fuel:{mileage_id}")],
        [InlineKeyboardButton(text="💰 Ganhos", callback_data=f"edit_fin_income:{mileage_id}")],
        [InlineKeyboardButton(text="👤 Salários", callback_data=f"edit_fin_salary:{mileage_id}")],
        [InlineKeyboardButton(text="🛠️ Despesas", callback_data=f"edit_fin_expenses:{mileage_id}")],
        [InlineKeyboardButton(text="📝 Observações", callback_data=f"edit_fin_notes:{mileage_id}")],
        [InlineKeyboardButton(text="⬅️ Voltar", callback_data=f"view_fin_record:{mileage_id}")]
    ]
    
    await query.edit_message_text(
        "✏️ *Editar Registro*\n\n"
        "O que você deseja alterar?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def on_delete_fin_record(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deleta um registro financeiro com confirmação"""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    
    # Suporta dois formatos
    if data.startswith("delete_fin_record:"):
        mileage_id = int(data.split(":", 1)[1])
        db = SessionLocal()
        try:
            mileage = db.get(Mileage, mileage_id)
            if not mileage:
                await query.answer("❌ Registro não encontrado!", show_alert=True)
                return
            record_date = mileage.date
            callback_confirm = f"confirm_delete_fin:{mileage_id}"
            callback_cancel = f"view_fin_record:{mileage_id}"
        finally:
            db.close()
    elif data.startswith("delete_fin_record_date:"):
        date_str = data.split(":", 1)[1]
        record_date = datetime.strptime(date_str, "%Y%m%d").date()
        callback_confirm = f"confirm_delete_fin_date:{date_str}"
        callback_cancel = f"view_fin_record_by_date:{date_str}"
    else:
        return
    
    # Confirma exclusão
    keyboard = [
        [
            InlineKeyboardButton(text="⚠️ SIM, Excluir", callback_data=callback_confirm),
            InlineKeyboardButton(text="❌ Cancelar", callback_data=callback_cancel)
        ]
    ]
    
    await query.edit_message_text(
        f"🗑️ *EXCLUIR REGISTRO*\n\n"
        f"Data: {record_date.strftime('%d/%m/%Y')}\n\n"
        f"⚠️ *Isso vai apagar:*\n"
        f"  • Quilometragem registrada\n"
        f"  • Todos os ganhos do dia\n"
        f"  • Todos os salários pagos\n"
        f"  • Todas as despesas\n"
        f"  • Observações\n\n"
        f"*Esta ação NÃO pode ser desfeita!*\n\n"
        f"Tem certeza?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def on_confirm_delete_fin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirma e executa a exclusão do registro"""
    query = update.callback_query
    await query.answer()
    
    data = query.data or ""
    
    # Suporta dois formatos
    if data.startswith("confirm_delete_fin:"):
        mileage_id = int(data.split(":", 1)[1])
        db = SessionLocal()
        try:
            mileage = db.get(Mileage, mileage_id)
            if not mileage:
                await query.answer("❌ Registro não encontrado!", show_alert=True)
                return
            
            record_date = mileage.date
            user_id = mileage.created_by
            
            # Deleta todos os dados do dia
            db.query(Expense).filter(
                Expense.date == record_date,
                Expense.created_by == user_id
            ).delete()
            
            db.query(Income).filter(
                Income.date == record_date,
                Income.created_by == user_id
            ).delete()
            
            db.delete(mileage)
            db.commit()
            
            await query.edit_message_text(
                f"✅ *Registro Excluído!*\n\n"
                f"O registro de {record_date.strftime('%d/%m/%Y')} foi removido do sistema.\n\n"
                f"Use /meus_registros para voltar à lista.",
                parse_mode='Markdown'
            )
        except Exception as e:
            await query.answer(f"❌ Erro ao excluir: {str(e)}", show_alert=True)
        finally:
            db.close()
    
    elif data.startswith("confirm_delete_fin_date:"):
        date_str = data.split(":", 1)[1]
        record_date = datetime.strptime(date_str, "%Y%m%d").date()
        user_id = update.effective_user.id
        
        db = SessionLocal()
        try:
            # Deleta todos os dados do dia
            db.query(Expense).filter(
                Expense.date == record_date,
                Expense.created_by == user_id
            ).delete()
            
            db.query(Income).filter(
                Income.date == record_date,
                Income.created_by == user_id
            ).delete()
            
            db.query(Mileage).filter(
                Mileage.date == record_date,
                Mileage.created_by == user_id
            ).delete()
            
            db.commit()
            
            await query.edit_message_text(
                f"✅ *Registro Excluído!*\n\n"
                f"O registro de {record_date.strftime('%d/%m/%Y')} foi removido do sistema.\n\n"
                f"Use /meus_registros para voltar à lista.",
                parse_mode='Markdown'
            )
        except Exception as e:
            await query.answer(f"❌ Erro ao excluir: {str(e)}", show_alert=True)
        finally:
            db.close()


async def on_back_to_fin_records(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Volta à lista de registros"""
    query = update.callback_query
    await query.answer()
    
    # Executa cmd_meus_registros
    await cmd_meus_registros(update, context)


# ==================== COMANDOS UTILITÁRIOS PENDENTES ====================


async def cmd_chat_ia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perguntas rápidas para IA Groq com contexto básico. Se GROQ_API_KEY faltar, avisa."""
    question = _extract_command_argument(update, context)
    if not question:
        await update.message.reply_text(
            "💬 *Chat IA*\n\nEnvie a pergunta junto do comando. Exemplo:\n/chat_ia Quantos pacotes entregues este mês?",
            parse_mode='Markdown'
        )
        return

    if not groq_client or not ai_model_name:
        await update.message.reply_text(
            "⚠️ IA indisponível. Configure GROQ_API_KEY para usar /chat_ia.",
            parse_mode='Markdown'
        )
        return

    try:
        # Descobre destino preferido: grupo/canal de análise, se configurado
        db = SessionLocal()
        try:
            me = get_user_by_tid(db, update.effective_user.id)
        finally:
            db.close()

        target_chat_id = update.effective_chat.id
        redirect_notice = False
        if me and me.role == "manager" and getattr(me, 'channel_id', None):
            target_chat_id = me.channel_id  # Pode ser grupo ou canal (IDs negativos)
            # Se perguntou em privado e vamos mandar ao grupo/canal, avisar
            if update.effective_chat.id != target_chat_id:
                redirect_notice = True

        resp = groq_client.chat.completions.create(
            model=ai_model_name,
            messages=[
                {"role": "system", "content": "Você é um assistente de operações de logística. Responda em pt-BR de forma objetiva."},
                {"role": "user", "content": question},
            ],
            temperature=0.3,
            max_tokens=600,
        )
        answer = resp.choices[0].message.content.strip()
        header = f"💬 Pergunta de {update.effective_user.first_name or update.effective_user.id}:\n{question}"
        try:
            await context.bot.send_message(chat_id=target_chat_id, text=header)
            await context.bot.send_message(chat_id=target_chat_id, text=f"🤖 {answer}")
        except Exception as send_err:
            # Fallback: responde no chat atual
            await update.message.reply_text(f"🤖 {answer}")
        else:
            if redirect_notice:
                try:
                    await update.message.reply_text("✅ Resposta enviada no grupo de análise.")
                except Exception:
                    pass
    except Exception as e:
        await update.message.reply_text(f"❌ Erro na IA: {str(e)[:200]}")


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
    app.add_handler(CallbackQueryHandler(help_callback_handler, pattern=r"^help_"))
    app.add_handler(CommandHandler("meu_id", cmd_meu_id))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(CommandHandler("rotas", cmd_rotas))
    app.add_handler(CallbackQueryHandler(on_view_route, pattern=r"^view_route:\d+$"))
    app.add_handler(CallbackQueryHandler(on_track_view_route, pattern=r"^track_view_route:\d+$"))
    app.add_handler(CallbackQueryHandler(on_delete_view_route, pattern=r"^delete_view_route:\d+$"))
    app.add_handler(CallbackQueryHandler(on_back_to_routes, pattern=r"^back_to_routes$"))
    # ✅ FASE 4.3: Handlers para finalização de rota
    app.add_handler(CallbackQueryHandler(on_finalize_route, pattern=r"^finalize_route:\d+$"))
    app.add_handler(CallbackQueryHandler(on_finalize_confirm, pattern=r"^finalize_confirm:\d+$"))
    app.add_handler(CommandHandler("relatorio", cmd_relatorio))
    app.add_handler(CommandHandler("configurar_canal_analise", cmd_configurar_canal_analise))
    app.add_handler(CommandHandler("meus_registros", cmd_meus_registros))
    # /rastrear removido (rastreio via /rotas -> botão "🗺️ Rastrear")
    app.add_handler(CommandHandler("chat_ia", cmd_chat_ia))
    app.add_handler(CommandHandler("chatia", cmd_chat_ia))
    app.add_handler(CallbackQueryHandler(on_view_fin_record, pattern=r"^view_fin_record:"))
    app.add_handler(CallbackQueryHandler(on_view_fin_record, pattern=r"^view_fin_record_by_date:"))
    app.add_handler(CallbackQueryHandler(on_edit_fin_record, pattern=r"^edit_fin_record:"))
    app.add_handler(CallbackQueryHandler(on_delete_fin_record, pattern=r"^delete_fin_record:"))
    app.add_handler(CallbackQueryHandler(on_delete_fin_record, pattern=r"^delete_fin_record_date:"))
    app.add_handler(CallbackQueryHandler(on_confirm_delete_fin, pattern=r"^confirm_delete_fin:"))
    app.add_handler(CallbackQueryHandler(on_confirm_delete_fin, pattern=r"^confirm_delete_fin_date:"))
    app.add_handler(CallbackQueryHandler(on_back_to_fin_records, pattern=r"^back_to_fin_records$"))
    app.add_handler(CommandHandler("cancelar", cmd_cancelar))

    import_conv = ConversationHandler(
        entry_points=[
            CommandHandler("importar", cmd_importar),
            # Alias para erro comum de digitação
            CommandHandler("imporar", cmd_importar),
        ],
        states={
            IMPORT_WAITING_FILE: [MessageHandler(filters.Document.ALL, handle_import_file)],
            IMPORT_CONFIRMING: [
                CallbackQueryHandler(on_import_confirm, pattern="^import_confirm$"),
                CallbackQueryHandler(on_import_cancel, pattern="^import_cancel$")
            ],
        },
        fallbacks=[CommandHandler("cancelar", cmd_cancelar)],
        name="import_conv",
        persistent=False,
    )
    app.add_handler(import_conv)

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
    
    # ✅ FASE 5: Conversation handler para finalização de rota (completo)
    finalize_route_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(on_finalize_no_expenses, pattern=r"^finalize_no_expenses:\d+$"),
            CallbackQueryHandler(on_finalize_add_expenses, pattern=r"^finalize_add_expenses:\d+$"),
            CallbackQueryHandler(on_finalize_add_income, pattern=r"^finalize_add_income:\d+$"),
        ],
        states={
            FINALIZE_EXTRA_EXPENSE_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalize_expense_type)],
            FINALIZE_EXTRA_EXPENSE_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalize_expense_value)],
            FINALIZE_EXTRA_EXPENSE_MORE: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalize_expense_more)],
            FINALIZE_EXTRA_INCOME_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalize_income_type)],
            FINALIZE_EXTRA_INCOME_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalize_income_value)],
            FINALIZE_KM: [MessageHandler(filters.TEXT & ~filters.COMMAND, finalize_km_input)],
        },
        fallbacks=[CommandHandler("cancelar", cmd_cancelar)],
        name="finalize_route_conv",
        persistent=False,
    )
    app.add_handler(finalize_route_conv)
    
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
            FAIL_PHOTO: [MessageHandler(filters.PHOTO, fail_photo), MessageHandler(filters.TEXT & ~filters.COMMAND, fail_photo)],
            FAIL_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, fail_notes)],
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

    # ❌ REMOVIDO: ConversationHandler de /registrardia (obsoleto - substituído por automação)
    # financial_conv = ConversationHandler(...)
    # app.add_handler(financial_conv)

    # Handler para mensagens genéricas (para processar ID do canal quando solicitado)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_channel_id_input))

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


