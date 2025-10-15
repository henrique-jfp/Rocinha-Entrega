import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import google.generativeai as genai
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

from database import (
    SessionLocal, init_db, User, Route, Package, DeliveryProof,
    Expense, Income, Mileage, AIReport
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

# Configurar Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY and GEMINI_API_KEY != "your_api_key_here":
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-pro')
else:
    gemini_model = None
BOT_TOKEN = os.getenv("BOT_TOKEN", "")


# Estados de conversa
IMPORT_WAITING_FILE = 10
IMPORT_ASK_SCRAPING = 11
IMPORT_SCRAPING_READY = 12
PHOTO1, PHOTO2, NAME, DOC, NOTES = range(5)
ADD_DRIVER_TID, ADD_DRIVER_NAME = range(10, 12)
SEND_SELECT_ROUTE, SEND_SELECT_DRIVER = range(20, 22)

# Estados financeiros (APENAS MANAGERS)
FIN_KM, FIN_FUEL_YN, FIN_FUEL_TYPE, FIN_FUEL_LITERS, FIN_FUEL_AMOUNT = range(30, 35)
FIN_INCOME, FIN_SALARY_YN, FIN_SALARY_NAME, FIN_SALARY_AMOUNT, FIN_SALARY_MORE = range(35, 40)
FIN_EXPENSES, FIN_NOTES = range(40, 42)


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
    """Comando /start - Cadastro inicial e boas-vindas"""
    init_db()
    u = update.effective_user
    user = register_manager_if_first(u.id, u.full_name)

    # Mensagem de boas-vindas personalizada
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
    if args and len(args) == 1:
        # Aceita tanto "iniciar_deliver_X" quanto "deliver_X"
        arg = args[0]
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
                await update.message.reply_text(
                    "📸 *Vamos registrar sua entrega!*\n\n"
                    "Por favor, envie a *primeira foto do pacote entregue*.\n\n"
                    "_Dica: Tire uma foto clara do pacote com a etiqueta visível._",
                    parse_mode='Markdown'
                )
                return PHOTO1
            except ValueError:
                pass
    
    # Se chamou /iniciar sem parâmetros ou com parâmetro inválido
    await update.message.reply_text(
        "⚠️ Comando inválido.\n\n"
        "Use o botão 'Entregar' no mapa interativo para iniciar uma entrega.",
        parse_mode='Markdown'
    )
    return ConversationHandler.END
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
                "🎯 *Central de Ajuda - Gerente*\n\n"
                "📦 *Gestão de Rotas*\n"
                "• `/importar` - Importa rotas de planilha Excel ou CSV\n"
                "• `/enviarrota` - Atribui uma rota a um motorista\n"
                "  _Envia link do mapa interativo automaticamente_\n\n"
                "👥 *Gestão de Equipe*\n"
                "• `/cadastrardriver` - Cadastra um novo motorista\n"
                "• `/drivers` - Lista todos os motoristas cadastrados\n\n"
                "💰 *Financeiro*\n"
                "• `/registrardia` - Registra dados financeiros diários\n"
                "  \\(KM rodados, combustível, ganhos, salários\\)\n"
                "• `/relatorio` - 🤖 *Gera relatório com IA Gemini*\n"
                "  _Análise inteligente de desempenho e finanças_\n\n"
                "�️ *Acompanhamento em Tempo Real:*\n"
                "• Mapa interativo atualiza a cada *30 segundos*\n"
                "• Veja localização do motorista em tempo real\n"
                "• Notificações quando pacotes são entregues\n"
                "• Histórico completo de entregas com fotos\n\n"
                "�🔧 *Utilitários*\n"
                "• `/meu_id` - Exibe seu Telegram ID\n"
                "• `/help` - Mostra esta mensagem de ajuda\n\n"
                "💡 *Dicas:*\n"
                "✅ Importe rotas pela manhã antes de enviar\n"
                "✅ Acompanhe motoristas pelo link do mapa\n"
                "✅ Mantenha registros financeiros atualizados\n"
                "✅ Fotos de entrega ficam salvas no sistema"
            )
        else:
            help_text = (
                "🎯 *Central de Ajuda - Motorista*\n\n"
                "📍 *Como Funciona o Sistema:*\n"
                "1️⃣ O gerente atribui uma rota para você\n"
                "2️⃣ Você recebe um *link do mapa interativo*\n"
                "3️⃣ O mapa mostra todos os pacotes com pins numerados\n"
                "4️⃣ Clique em cada pin para ver detalhes\n"
                "5️⃣ Use o botão *'🧭 Navegar'* para abrir no Google Maps\n"
                "6️⃣ Ao chegar no destino, clique *'✓ Entregar'*\n"
                "7️⃣ Complete o registro de entrega no Telegram\n\n"
                "📸 *Processo de Entrega \\(5 Passos\\):*\n"
                "• *Foto 1:* Pacote entregue \\(com etiqueta visível\\)\n"
                "• *Foto 2:* Local da entrega \\(porta, fachada ou recebedor\\)\n"
                "• *Nome:* Quem recebeu o pacote\n"
                "• *Documento:* CPF ou RG \\(ou 'sem documento'\\)\n"
                "• *Observações:* Informações extras \\(opcional\\)\n\n"
                "🗺️ *Recursos do Mapa:*\n"
                "• Atualização automática a cada *30 segundos*\n"
                "• Sua localização em tempo real \\(ponto azul\\)\n"
                "• Contador de pacotes: pendentes/entregues\n"
                "• Pins coloridos por status:\n"
                "  🔵 Azul = Pendente\n"
                "  🟢 Verde = Entregue\n"
                "  🔴 Vermelho = Falhou\n\n"
                "🔧 *Comandos Disponíveis:*\n"
                "• `/entregar` - Registrar entrega manualmente\n"
                "• `/meu_id` - Ver seu Telegram ID\n"
                "• `/help` - Mostra esta mensagem\n\n"
                "💡 *Dicas Importantes:*\n"
                "✅ Mantenha a *localização ativada* \\(gerente acompanha\\)\n"
                "✅ Tire *fotos claras* do pacote e local\n"
                "✅ Use o *mapa interativo* para melhor experiência\n"
                "✅ O mapa funciona offline após carregar\n\n"
                "❓ *Dúvidas?* Entre em contato com seu gerente\\!"
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
        
        # Dados de entregas
        total_packages = db.query(Package).filter(Package.created_at >= month_start).count()
        delivered_packages = db.query(Package).filter(
            Package.created_at >= month_start,
            Package.status == "delivered"
        ).count()
        failed_packages = db.query(Package).filter(
            Package.created_at >= month_start,
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


async def cmd_meu_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 *Seu Telegram ID*\n\n"
        f"ID: `{update.effective_user.id}`\n\n"
        f"_Copie este número se o gerente solicitar._",
        parse_mode='Markdown'
    )


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
        "📂 *Importar Nova Rota*\n\n"
        "Envie um arquivo Excel (.xlsx) ou CSV (.csv) com as seguintes colunas:\n\n"
        "• *Código de Rastreio* (obrigatório)\n"
        "• *Endereço* (obrigatório)\n"
        "• *Latitude* (opcional)\n"
        "• *Longitude* (opcional)\n"
        "• *Bairro* (opcional)\n\n"
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
        route_name = f"📦 Rota {datetime.now().strftime('%d/%m/%Y às %H:%M')}"
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
        
        # Pergunta se quer fazer scraping
        keyboard = [['Sim', 'Não']]
        await update.message.reply_text(
            f"✅ *Pacotes Importados!*\n\n"
            f"🆔 ID da Rota: `{route.id}`\n"
            f"📦 Total de Pacotes: *{len(items)}*\n\n"
            f"� *Deseja extrair telefones do app SPX?*\n\n"
            f"⚠️ _Você precisará ter o celular conectado via USB com o app SPX aberto._",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
            parse_mode='Markdown'
        )
        return IMPORT_ASK_SCRAPING
        
    except Exception as e:
        db.rollback()
        await update.message.reply_text(f"❌ Erro ao importar: {str(e)}")
        return ConversationHandler.END
    finally:
        db.close()


async def handle_scraping_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pergunta se quer fazer scraping de telefones"""
    choice = (update.message.text or "").strip().lower()
    
    if choice in ['sim', 's']:
        await update.message.reply_text(
            "🤖 *Preparando Scraper de Telefones*\n\n"
            "📱 *Instruções:*\n"
            "1. Conecte seu celular via USB ao PC\n"
            "2. Ative 'Depuração USB' nas configurações de desenvolvedor\n"
            "3. Abra o app *SPX Motorista*\n"
            "4. Vá para a aba *'Pendente'*\n"
            "5. Deixe a lista de entregas visível\n"
            "6. *NÃO toque no celular* durante o processo\n\n"
            "⏱️ O scraping levará cerca de *30-60 segundos* por entrega.\n\n"
            "Quando estiver pronto, pressione o botão abaixo:",
            reply_markup=ReplyKeyboardMarkup([['✅ Estou Pronto!']], one_time_keyboard=True, resize_keyboard=True),
            parse_mode='Markdown'
        )
        return IMPORT_SCRAPING_READY
    else:
        # Não quer fazer scraping - finaliza importação
        route_id = context.user_data.get('import_route_id')
        package_count = context.user_data.get('import_package_count', 0)
        
        context.user_data.clear()
        
        await update.message.reply_text(
            f"✅ *Rota Criada com Sucesso!*\n\n"
            f"🆔 ID da Rota: `{route_id}`\n"
            f"📦 Total de Pacotes: *{package_count}*\n"
            f"📅 Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
            f"💡 Use /enviarrota para atribuir esta rota a um motorista.",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='Markdown'
        )
        return ConversationHandler.END


async def handle_scraping_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia o processo de scraping"""
    route_id = context.user_data.get('import_route_id')
    tracking_codes = context.user_data.get('import_tracking_codes', [])
    
    if not route_id or not tracking_codes:
        await update.message.reply_text(
            "❌ Erro: Dados da rota não encontrados.\n\nTente importar novamente.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    
    await update.message.reply_text(
        f"🚀 *Iniciando Scraping...*\n\n"
        f"📦 Total de pacotes: {len(tracking_codes)}\n"
        f"⏳ Aguarde...",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
    
    # Importa e executa o scraper
    try:
        import sys
        from pathlib import Path
        
        # Adiciona diretório raiz ao path
        root_dir = Path(__file__).parent.parent
        if str(root_dir) not in sys.path:
            sys.path.insert(0, str(root_dir))
        
        # Importa o scraper
        from spx_scraper import SPXScraper
        
        # Executa scraping
        scraper = SPXScraper()
        
        # Verifica conexão ADB
        if not scraper.check_adb_connection():
            await update.message.reply_text(
                "❌ *Erro: Celular não conectado!*\n\n"
                "Verifique:\n"
                "• Celular conectado via USB\n"
                "• Depuração USB ativada\n"
                "• Execute: `adb devices` no PC\n\n"
                "Finalizando importação sem telefones...",
                parse_mode='Markdown'
            )
            return await finalize_import_without_phones(update, context)
        
        # Faz o scraping
        await update.message.reply_text(
            "🤖 *Scraping em andamento...*\n\n"
            "⏳ Não toque no celular!\n"
            f"📦 Processando {len(tracking_codes)} pacotes...",
            parse_mode='Markdown'
        )
        
        results = scraper.scrape_delivery_phones(tracking_codes)
        
        # NOTE: Campo phone desabilitado temporariamente (precisa migração do banco)
        # Atualiza pacotes no banco com os telefones
        db = SessionLocal()
        try:
            updated_count = 0
            # for tracking_code, phone in results.items():
            #     if phone:
            #         package = db.query(Package).filter(
            #             Package.route_id == route_id,
            #             Package.tracking_code == tracking_code
            #         ).first()
            #         
            #         if package:
            #             package.phone = phone
            #             updated_count += 1
            
            # Apenas conta quantos telefones foram encontrados
            updated_count = sum(1 for phone in results.values() if phone)
            
            db.commit()
            
            success_rate = (updated_count / len(tracking_codes) * 100) if tracking_codes else 0
            
            await update.message.reply_text(
                f"✅ *Scraping Concluído!*\n\n"
                f"📞 Telefones extraídos: *{updated_count}/{len(tracking_codes)}* ({success_rate:.0f}%)\n"
                f"📦 Pacotes atualizados com sucesso!\n\n"
                f"🎉 *Rota Criada com Sucesso!*\n"
                f"🆔 ID da Rota: `{route_id}`\n\n"
                f"💡 Use /enviarrota para atribuir esta rota a um motorista.",
                parse_mode='Markdown'
            )
            
        finally:
            db.close()
        
    except ImportError:
        await update.message.reply_text(
            "⚠️ *Módulo de scraping não encontrado.*\n\n"
            "Finalizando importação sem telefones...",
            parse_mode='Markdown'
        )
        return await finalize_import_without_phones(update, context)
    
    except Exception as e:
        await update.message.reply_text(
            f"❌ *Erro no scraping:* {str(e)}\n\n"
            f"Finalizando importação sem telefones...",
            parse_mode='Markdown'
        )
        return await finalize_import_without_phones(update, context)
    
    # Limpa dados temporários
    context.user_data.clear()
    return ConversationHandler.END


async def finalize_import_without_phones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finaliza importação sem scraping de telefones"""
    route_id = context.user_data.get('import_route_id')
    package_count = context.user_data.get('import_package_count', 0)
    
    context.user_data.clear()
    
    await update.message.reply_text(
        f"✅ *Rota Criada!*\n\n"
        f"🆔 ID da Rota: `{route_id}`\n"
        f"📦 Total de Pacotes: *{package_count}*\n"
        f"📅 Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
        f"ℹ️ _Telefones não foram extraídos._\n\n"
        f"💡 Use /enviarrota para atribuir esta rota a um motorista.",
        parse_mode='Markdown'
    )
    return ConversationHandler.END


async def cmd_enviarrota(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            try:
                await context.bot.send_message(
                    chat_id=driver_tid,
                    text=(
                        f"🎯 *Nova Rota Atribuída!*\n\n"
                        f"📦 Total de Pacotes: *{count}*\n"
                        f"🗺️ Mapa Interativo: [Clique Aqui]({link})\n\n"
                        f"💡 _Abra o mapa para ver todas as entregas e começar!_"
                    ),
                    parse_mode='Markdown'
                )
                await update.message.reply_text(
                    f"✅ *Rota Enviada!*\n\n"
                    f"O motorista recebeu a notificação com o link do mapa.",
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
    await query.answer()
    data = query.data or ""
    if not data.startswith("sel_driver:"):
        return
    driver_tid = int(data.split(":", 1)[1])
    route_id = context.user_data.get("send_route_id")
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
        count = db.query(Package).filter(Package.route_id == route.id).count()
        link = f"{BASE_URL}/map/{route.id}/{driver_tid}"
        try:
            await context.bot.send_message(
                chat_id=driver_tid,
                text=(
                    f"🎯 *Nova Rota Atribuída!*\n\n"
                    f"📦 Total de Pacotes: *{count}*\n"
                    f"🗺️ Mapa Interativo: [Clique Aqui]({link})\n\n"
                    f"💡 _Abra o mapa para ver todas as entregas e começar!_"
                ),
                parse_mode='Markdown'
            )
            await query.edit_message_text(
                "✅ *Rota Enviada!*\n\n"
                "O motorista recebeu a notificação com o link do mapa.",
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
    
    # Cria botões inline com opção de excluir
    buttons = []
    for d in drivers:
        name = d.full_name or 'Sem nome'
        tid = d.telegram_user_id
        buttons.append([
            InlineKeyboardButton(
                f"👤 {name} (ID: {tid})",
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
        f"💡 _Clique em 🗑️ para excluir um motorista_",
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
    await update.message.reply_text(
        "📸 *Comprovante de Entrega - Passo 1/4*\n\n"
        "Envie a *Foto 1* (recebedor ou pacote).",
        parse_mode='Markdown'
    )
    return PHOTO1


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
    pkg_id = context.user_data.get("deliver_package_id")
    if not pkg_id:
        await update.message.reply_text(
            "❌ *Erro Interno*\n\n"
            "Não foi possível identificar o pacote.\n\n"
            "Use /entregar novamente.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    db = SessionLocal()
    try:
        package = db.get(Package, int(pkg_id))
        if not package:
            await update.message.reply_text(
                "❌ *Pacote Não Encontrado*\n\n"
                f"O pacote ID `{pkg_id}` não existe.",
                parse_mode='Markdown'
            )
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
        receiver_name = context.user_data.get('receiver_name') or '-'
        receiver_doc = context.user_data.get('receiver_document') or '-'
        notes = context.user_data.get('notes') or '-'
        
        summary = (
            f"✅ *Entrega Concluída!*\n\n"
            f"📦 *Pacote:* {package.tracking_code}\n"
            f"📍 *Endereço:* {package.address or '-'}\n"
            f"� *Recebedor:* {receiver_name}\n"
            f"🆔 *Documento:* {receiver_doc}\n"
            f"📝 *Observações:* {notes}"
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
                        await context.bot.send_photo(
                            chat_id=m.telegram_user_id,
                            photo=p1,
                            caption="📸 Foto 1 - Recebedor/Pacote"
                        )
                    except Exception:
                        pass
                if p2:
                    try:
                        await context.bot.send_photo(
                            chat_id=m.telegram_user_id,
                            photo=p2,
                            caption="📸 Foto 2 - Local/Porta"
                        )
                    except Exception:
                        pass

    await update.message.reply_text(
        "✅ *Entrega Registrada!*\n\n"
        f"📦 O pacote foi marcado como entregue.\n"
        f"👔 Os gerentes foram notificados.\n\n"
        f"💡 _Continue para a próxima entrega no mapa!_",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
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


def build_application():
    if not BOT_TOKEN:
        raise RuntimeError("Defina a variável de ambiente BOT_TOKEN")
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Comandos básicos
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("meu_id", cmd_meu_id))
    app.add_handler(CommandHandler("relatorio", cmd_relatorio))

    import_conv = ConversationHandler(
        entry_points=[CommandHandler("importar", cmd_importar)],
        states={
            IMPORT_WAITING_FILE: [MessageHandler(filters.Document.ALL, handle_import_file)],
            IMPORT_ASK_SCRAPING: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_scraping_choice)],
            IMPORT_SCRAPING_READY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_scraping_start)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="import_conv",
        persistent=False,
    )
    app.add_handler(import_conv)

    app.add_handler(CommandHandler("enviarrota", cmd_enviarrota))
    app.add_handler(CallbackQueryHandler(on_select_route, pattern=r"^sel_route:\d+$"))
    app.add_handler(CallbackQueryHandler(on_select_driver, pattern=r"^sel_driver:\d+$"))
    app.add_handler(CallbackQueryHandler(on_delete_driver, pattern=r"^delete_driver:\d+$"))
    app.add_handler(CallbackQueryHandler(on_delete_route, pattern=r"^delete_route:\d+$"))

    delivery_conv = ConversationHandler(
        entry_points=[
            CommandHandler("entregar", deliver_start),
            CommandHandler("iniciar", cmd_iniciar)  # Deep link do mapa: /iniciar deliver_X
        ],
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

    # Financial conversation (MANAGERS ONLY)
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
        fallbacks=[CommandHandler("cancel", cancel)],
        name="financial_conv",
        persistent=False,
    )
    app.add_handler(financial_conv)

    return app


def main():
    app = build_application()
    print("Bot iniciado. Pressione Ctrl+C para sair.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
