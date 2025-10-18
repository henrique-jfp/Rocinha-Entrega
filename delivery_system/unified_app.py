"""
Aplicação unificada: FastAPI (web) + Telegram Bot (webhook)
Roda tudo em um único processo, usando plano FREE do Render
"""
import os
from dotenv import load_dotenv

from fastapi import Request
from telegram import Update
from telegram.ext import Application

# Importa a app FastAPI existente
from app import create_app

# Importa a configuração do bot
from bot import setup_bot_handlers

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BASE_URL = os.getenv("BASE_URL", "")  # Ex: https://entrega-web.onrender.com
WEBHOOK_PATH = f"/telegram-webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"

# Cria a aplicação FastAPI
app = create_app()

# Variável global para o bot
bot_app: Application = None


async def telegram_webhook(request: Request):
    """Recebe updates do Telegram via webhook"""
    json_data = await request.json()
    update = Update.de_json(json_data, bot_app.bot)
    await bot_app.process_update(update)
    return {"ok": True}


@app.on_event("startup")
async def on_startup():
    """Inicializa o bot com webhook quando a API inicia"""
    global bot_app
    
    if not BOT_TOKEN:
        print("⚠️ BOT_TOKEN não configurado, bot não será iniciado")
        return
    
    if not BASE_URL:
        print("⚠️ BASE_URL não configurado, bot não será iniciado")
        return
    
    print(f"🤖 Iniciando bot com webhook...")
    print(f"📡 Webhook URL: {WEBHOOK_URL}")
    
    # Cria a aplicação do bot
    bot_app = Application.builder().token(BOT_TOKEN).build()
    
    # Configura os handlers do bot (importa de bot.py)
    setup_bot_handlers(bot_app)
    
    # Inicializa o bot
    await bot_app.initialize()
    await bot_app.bot.delete_webhook(drop_pending_updates=True)
    await bot_app.bot.set_webhook(
        url=WEBHOOK_URL,
        allowed_updates=Update.ALL_TYPES
    )
    
    print(f"✅ Bot iniciado com webhook: {WEBHOOK_URL}")
    
    # Registra a rota do webhook
    app.add_api_route(
        WEBHOOK_PATH,
        telegram_webhook,
        methods=["POST"],
        include_in_schema=False
    )


@app.on_event("shutdown")
async def on_shutdown():
    """Desliga o bot quando a API para"""
    global bot_app
    if bot_app:
        await bot_app.bot.delete_webhook()
        await bot_app.shutdown()
        print("✅ Bot desligado")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("unified_app:app", host="0.0.0.0", port=port, reload=False)
