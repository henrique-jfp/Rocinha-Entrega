-- Migration: Adiciona tabela de gestão de salários a pagar
-- Data: 2025-10-21
-- Descrição: Sistema de controle de pagamentos com notificações automáticas

CREATE TABLE IF NOT EXISTS salary_payment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    driver_id INTEGER NOT NULL,
    route_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    week_start DATE NOT NULL,
    week_end DATE NOT NULL,
    due_date DATE NOT NULL,
    paid_date DATETIME,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    notes TEXT,
    created_by BIGINT NOT NULL,
    confirmed_by BIGINT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    
    FOREIGN KEY (driver_id) REFERENCES user(id) ON DELETE CASCADE,
    FOREIGN KEY (route_id) REFERENCES route(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES user(telegram_user_id),
    FOREIGN KEY (confirmed_by) REFERENCES user(telegram_user_id),
    
    CONSTRAINT ck_salary_payment_status CHECK (status IN ('pending', 'overdue', 'paid'))
);

CREATE INDEX IF NOT EXISTS idx_salary_payment_driver ON salary_payment(driver_id);
CREATE INDEX IF NOT EXISTS idx_salary_payment_route ON salary_payment(route_id);
CREATE INDEX IF NOT EXISTS idx_salary_payment_due_date ON salary_payment(due_date);
CREATE INDEX IF NOT EXISTS idx_salary_payment_status ON salary_payment(status);
