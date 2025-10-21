-- ====================================================================
-- MIGRAÇÃO: Mudança de SET NULL para CASCADE em Expense e Income
-- ====================================================================
-- Data: 2024-10-21
-- Objetivo: Garantir que ao excluir uma rota, TODAS as receitas e 
--           despesas vinculadas sejam excluídas automaticamente
-- ====================================================================

-- Passo 1: Remove constraints antigas de Expense
PRAGMA foreign_keys = OFF;

-- Cria tabela temporária para Expense
CREATE TABLE expense_new (
    id INTEGER PRIMARY KEY,
    date DATE NOT NULL,
    type VARCHAR(50) NOT NULL,
    description VARCHAR(500) NOT NULL,
    amount REAL NOT NULL,
    fuel_type VARCHAR(50),
    fuel_liters REAL,
    employee_name VARCHAR(255),
    route_id INTEGER,
    confirmed INTEGER DEFAULT 1 NOT NULL,
    created_by BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (route_id) REFERENCES route(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES user(telegram_user_id),
    CHECK (type IN ('combustivel','salario','manutencao','pedagio','combustivel_outro','outro'))
);

-- Copia dados
INSERT INTO expense_new 
SELECT id, date, type, description, amount, fuel_type, fuel_liters, 
       employee_name, route_id, confirmed, created_by, created_at
FROM expense;

-- Remove tabela antiga e renomeia
DROP TABLE expense;
ALTER TABLE expense_new RENAME TO expense;

-- Recria índices
CREATE INDEX ix_expense_date ON expense(date);

-- ====================================================================

-- Passo 2: Remove constraints antigas de Income
CREATE TABLE income_new (
    id INTEGER PRIMARY KEY,
    date DATE NOT NULL,
    route_id INTEGER,
    description VARCHAR(500) NOT NULL,
    amount REAL NOT NULL,
    created_by BIGINT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (route_id) REFERENCES route(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES user(telegram_user_id)
);

-- Copia dados
INSERT INTO income_new 
SELECT id, date, route_id, description, amount, created_by, created_at
FROM income;

-- Remove tabela antiga e renomeia
DROP TABLE income;
ALTER TABLE income_new RENAME TO income;

-- Recria índices
CREATE INDEX ix_income_date ON income(date);

-- ====================================================================

-- Reativa foreign keys
PRAGMA foreign_keys = ON;

-- ====================================================================
-- TESTE: Verificar se constraints estão corretas
-- ====================================================================
-- Para testar, execute:
-- SELECT sql FROM sqlite_master WHERE name='expense';
-- SELECT sql FROM sqlite_master WHERE name='income';
-- 
-- Deve mostrar: ON DELETE CASCADE nas foreign keys de route_id
-- ====================================================================
