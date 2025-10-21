"""
Scheduler para notificações automáticas de salários
Executa duas jobs:
1. Toda quinta-feira às 12:00 - notifica salários pendentes do dia
2. Todo dia às 09:00 - notifica salários atrasados e atualiza status
"""

from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from database import SessionLocal, SalaryPayment, User
from shared.logger import logger
import os


# Bot token do ambiente
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN não configurado no .env")


async def notify_thursday_salaries():
    """
    Job executada toda quinta-feira às 12:00
    Notifica manager sobre salários com vencimento no dia
    """
    db = SessionLocal()
    bot = Bot(token=BOT_TOKEN)
    
    try:
        today = datetime.now().date()
        
        # Busca salários com vencimento hoje e status pending
        payments_today = db.query(SalaryPayment).filter(
            SalaryPayment.due_date == today,
            SalaryPayment.status == 'pending'
        ).all()
        
        if not payments_today:
            logger.info("[SCHEDULER] Nenhum salário vencendo hoje (quinta-feira)")
            return
        
        # Agrupa por motorista
        from collections import defaultdict
        by_driver = defaultdict(list)
        for payment in payments_today:
            by_driver[payment.driver_id].append(payment)
        
        total_amount = sum(p.amount for p in payments_today)
        
        # Monta mensagem
        message = "🔔 *LEMBRETE: QUINTA-FEIRA - DIA DE PAGAMENTO!*\n\n"
        message += f"📅 Vencimento: {today.strftime('%d/%m/%Y')}\n"
        message += f"💰 Total a pagar: R$ {total_amount:.2f}\n\n"
        message += "👥 *Salários do dia:*\n\n"
        
        buttons = []
        
        for driver_id, payments in by_driver.items():
            driver = db.get(User, driver_id)
            driver_name = driver.full_name if driver else "Desconhecido"
            total_driver = sum(p.amount for p in payments)
            
            message += f"👤 *{driver_name}*\n"
            for payment in payments:
                route_info = f"Rota #{payment.route_id}" if payment.route_id else "Avulso"
                message += f"  • {route_info} - R$ {payment.amount:.2f}\n"
                
                # Botão individual
                buttons.append([
                    InlineKeyboardButton(
                        f"✅ Confirmar R$ {payment.amount:.2f} ({driver_name[:15]})",
                        callback_data=f"confirm_salary:{payment.id}"
                    )
                ])
            
            message += f"  💵 Subtotal: R$ {total_driver:.2f}\n\n"
        
        message += "👇 *Confirme os pagamentos:*"
        
        # Botão para confirmar todos
        if len(payments_today) > 1:
            all_ids = ",".join(str(p.id) for p in payments_today)
            buttons.append([
                InlineKeyboardButton(
                    f"✅ CONFIRMAR TODOS (R$ {total_amount:.2f})",
                    callback_data=f"confirm_salary_all:{all_ids}"
                )
            ])
        
        keyboard = InlineKeyboardMarkup(buttons)
        
        # Busca managers para enviar notificação
        managers = db.query(User).filter(User.role.in_(['manager', 'admin'])).all()
        
        for manager in managers:
            try:
                await bot.send_message(
                    chat_id=manager.telegram_user_id,
                    text=message,
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
                logger.info(f"[SCHEDULER] Notificação quinta-feira enviada para {manager.full_name}")
            except Exception as e:
                logger.error(f"[SCHEDULER] Erro ao enviar para {manager.full_name}: {e}")
        
    except Exception as e:
        logger.error(f"[SCHEDULER] Erro em notify_thursday_salaries: {e}")
    finally:
        db.close()


async def notify_overdue_salaries():
    """
    Job executada todo dia às 09:00
    Atualiza status de pendentes para overdue e notifica sobre atrasos
    """
    db = SessionLocal()
    bot = Bot(token=BOT_TOKEN)
    
    try:
        today = datetime.now().date()
        
        # Busca salários vencidos (due_date < hoje) e ainda pending ou overdue
        overdue_payments = db.query(SalaryPayment).filter(
            SalaryPayment.due_date < today,
            SalaryPayment.status.in_(['pending', 'overdue'])
        ).all()
        
        if not overdue_payments:
            logger.info("[SCHEDULER] Nenhum salário atrasado")
            return
        
        # Atualiza status de pending para overdue
        updated_count = 0
        for payment in overdue_payments:
            if payment.status == 'pending':
                payment.status = 'overdue'
                updated_count += 1
        
        if updated_count > 0:
            db.commit()
            logger.info(f"[SCHEDULER] {updated_count} salário(s) marcado(s) como atrasado")
        
        # Agrupa por motorista
        from collections import defaultdict
        by_driver = defaultdict(list)
        for payment in overdue_payments:
            by_driver[payment.driver_id].append(payment)
        
        total_amount = sum(p.amount for p in overdue_payments)
        
        # Monta mensagem de alerta
        message = "⚠️ *ATENÇÃO: SALÁRIOS ATRASADOS!*\n\n"
        message += f"🔴 Total em atraso: R$ {total_amount:.2f}\n"
        message += f"📊 Quantidade: {len(overdue_payments)} pagamento(s)\n\n"
        message += "👥 *Detalhamento:*\n\n"
        
        buttons = []
        
        for driver_id, payments in by_driver.items():
            driver = db.get(User, driver_id)
            driver_name = driver.full_name if driver else "Desconhecido"
            total_driver = sum(p.amount for p in payments)
            
            message += f"👤 *{driver_name}*\n"
            for payment in payments:
                days_overdue = (today - payment.due_date).days
                route_info = f"Rota #{payment.route_id}" if payment.route_id else "Avulso"
                message += f"  • {route_info} - R$ {payment.amount:.2f}\n"
                message += f"     ⏰ Vencimento: {payment.due_date.strftime('%d/%m/%Y')} ({days_overdue} dias de atraso)\n"
                
                # Botão individual
                buttons.append([
                    InlineKeyboardButton(
                        f"✅ Confirmar R$ {payment.amount:.2f} ({driver_name[:15]})",
                        callback_data=f"confirm_salary:{payment.id}"
                    )
                ])
            
            message += f"  💵 Subtotal: R$ {total_driver:.2f}\n\n"
        
        message += "⚡ *Regularize os pagamentos o quanto antes!*\n"
        message += "👇 Confirme os pagamentos:"
        
        # Botão para confirmar todos
        if len(overdue_payments) > 1:
            all_ids = ",".join(str(p.id) for p in overdue_payments)
            buttons.append([
                InlineKeyboardButton(
                    f"✅ CONFIRMAR TODOS (R$ {total_amount:.2f})",
                    callback_data=f"confirm_salary_all:{all_ids}"
                )
            ])
        
        keyboard = InlineKeyboardMarkup(buttons)
        
        # Busca managers para enviar notificação
        managers = db.query(User).filter(User.role.in_(['manager', 'admin'])).all()
        
        for manager in managers:
            try:
                await bot.send_message(
                    chat_id=manager.telegram_user_id,
                    text=message,
                    parse_mode='Markdown',
                    reply_markup=keyboard
                )
                logger.info(f"[SCHEDULER] Notificação de atrasos enviada para {manager.full_name}")
            except Exception as e:
                logger.error(f"[SCHEDULER] Erro ao enviar para {manager.full_name}: {e}")
        
    except Exception as e:
        logger.error(f"[SCHEDULER] Erro em notify_overdue_salaries: {e}")
    finally:
        db.close()


def start_scheduler():
    """
    Inicia o scheduler com as duas jobs configuradas:
    - Quinta-feira 12:00: Notifica salários do dia
    - Todo dia 09:00: Notifica salários atrasados
    """
    scheduler = AsyncIOScheduler(timezone='America/Sao_Paulo')
    
    # Job 1: Quinta-feira às 12:00
    scheduler.add_job(
        notify_thursday_salaries,
        trigger=CronTrigger(day_of_week='thu', hour=12, minute=0),
        id='thursday_salary_notification',
        name='Notificação de Salários - Quinta-feira 12:00',
        replace_existing=True
    )
    logger.info("[SCHEDULER] Job configurada: Quinta-feira 12:00 - Notificação de salários")
    
    # Job 2: Todo dia às 09:00
    scheduler.add_job(
        notify_overdue_salaries,
        trigger=CronTrigger(hour=9, minute=0),
        id='daily_overdue_notification',
        name='Notificação de Salários Atrasados - Diária 09:00',
        replace_existing=True
    )
    logger.info("[SCHEDULER] Job configurada: Todo dia 09:00 - Notificação de atrasos")
    
    scheduler.start()
    logger.info("[SCHEDULER] ✅ Scheduler iniciado com sucesso!")
    
    return scheduler
