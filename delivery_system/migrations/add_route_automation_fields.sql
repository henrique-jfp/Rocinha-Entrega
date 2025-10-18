-- Migration: Adiciona campos para automação financeira de rotas
-- Data: 18/10/2025
-- Fase 4.1: Automação de Receita e Salário

-- Adiciona novos campos na tabela Route
ALTER TABLE route ADD COLUMN revenue REAL DEFAULT 260.0 NOT NULL;
ALTER TABLE route ADD COLUMN driver_salary REAL;
ALTER TABLE route ADD COLUMN status TEXT DEFAULT 'pending' NOT NULL;
ALTER TABLE route ADD COLUMN completed_at TIMESTAMP;
ALTER TABLE route ADD COLUMN finalized_at TIMESTAMP;
ALTER TABLE route ADD COLUMN extra_expenses REAL DEFAULT 0.0 NOT NULL;
ALTER TABLE route ADD COLUMN extra_income REAL DEFAULT 0.0 NOT NULL;
ALTER TABLE route ADD COLUMN calculated_km REAL;

-- Adiciona novos campos na tabela Expense
ALTER TABLE expense ADD COLUMN route_id INTEGER REFERENCES route(id) ON DELETE SET NULL;
ALTER TABLE expense ADD COLUMN confirmed INTEGER DEFAULT 1 NOT NULL;

-- Atualiza rotas existentes
-- Se já tiver assigned_to_id, considera como in_progress
UPDATE route SET status = 'in_progress' WHERE assigned_to_id IS NOT NULL;

-- Cria índices para melhor performance
CREATE INDEX IF NOT EXISTS idx_route_status ON route(status);
CREATE INDEX IF NOT EXISTS idx_expense_route_id ON expense(route_id);
CREATE INDEX IF NOT EXISTS idx_expense_confirmed ON expense(confirmed);
