-- ═══════════════════════════════════════════════════════════
-- MIGRATION: Adicionar Índices de Performance
-- Data: 2024-12-20
-- Descrição: Adiciona índices para otimizar queries frequentes
-- ═══════════════════════════════════════════════════════════

-- Início da transação
BEGIN;

-- ─────────────────────────────────────────────────────────
-- 1. ÍNDICES PARA TABELA PACKAGE
-- ─────────────────────────────────────────────────────────
-- Índice composto para filtrar pacotes por rota e status
CREATE INDEX IF NOT EXISTS idx_package_route_status 
ON package(route_id, status);

-- Índice para order_in_route (usado em ordenação)
CREATE INDEX IF NOT EXISTS idx_package_order_in_route 
ON package(route_id, order_in_route) 
WHERE order_in_route IS NOT NULL;

-- ─────────────────────────────────────────────────────────
-- 2. ÍNDICES PARA TABELA ROUTE
-- ─────────────────────────────────────────────────────────
-- Índice composto para queries de rotas por motorista e data
CREATE INDEX IF NOT EXISTS idx_route_assigned_created 
ON route(assigned_to_id, created_at);

-- Índice parcial para rotas ativas (com motorista atribuído)
CREATE INDEX IF NOT EXISTS idx_route_active 
ON route(created_at, assigned_to_id) 
WHERE assigned_to_id IS NOT NULL;

-- ─────────────────────────────────────────────────────────
-- 3. ÍNDICES PARA TABELA USER
-- ─────────────────────────────────────────────────────────
-- Índice para filtrar por role (manager/driver)
CREATE INDEX IF NOT EXISTS idx_user_role 
ON "user"(role);

-- ─────────────────────────────────────────────────────────
-- 4. ÍNDICES PARA TABELAS FINANCEIRAS
-- ─────────────────────────────────────────────────────────
-- Expense: índice composto para filtrar por data e tipo
CREATE INDEX IF NOT EXISTS idx_expense_date_type 
ON expense(date, type);

-- Expense: índice para filtrar por usuário
CREATE INDEX IF NOT EXISTS idx_expense_created_by 
ON expense(created_by, date);

-- Income: índice para filtrar por data
CREATE INDEX IF NOT EXISTS idx_income_date 
ON income(date);

-- Income: índice para filtrar por rota
CREATE INDEX IF NOT EXISTS idx_income_route 
ON income(route_id) 
WHERE route_id IS NOT NULL;

-- Mileage: índice para filtrar por data
CREATE INDEX IF NOT EXISTS idx_mileage_date 
ON mileage(date);

-- ─────────────────────────────────────────────────────────
-- 5. ÍNDICES PARA DELIVERY_PROOF
-- ─────────────────────────────────────────────────────────
-- Índice para buscar provas por pacote
CREATE INDEX IF NOT EXISTS idx_deliveryproof_package 
ON delivery_proof(package_id);

-- ─────────────────────────────────────────────────────────
-- VERIFICAÇÃO
-- ─────────────────────────────────────────────────────────
-- Listar todos os índices criados
SELECT 
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
AND indexname LIKE 'idx_%'
ORDER BY tablename, indexname;

-- Estatísticas de uso (execute após alguns dias)
-- SELECT 
--     schemaname,
--     tablename,
--     indexname,
--     idx_scan as index_scans,
--     idx_tup_read as tuples_read,
--     idx_tup_fetch as tuples_fetched
-- FROM pg_stat_user_indexes
-- WHERE indexname LIKE 'idx_%'
-- ORDER BY idx_scan DESC;

COMMIT;

-- ═══════════════════════════════════════════════════════════
-- ROLLBACK (se necessário)
-- ═══════════════════════════════════════════════════════════
/*
BEGIN;
DROP INDEX IF EXISTS idx_package_route_status;
DROP INDEX IF EXISTS idx_package_order_in_route;
DROP INDEX IF EXISTS idx_route_assigned_created;
DROP INDEX IF EXISTS idx_route_active;
DROP INDEX IF EXISTS idx_user_role;
DROP INDEX IF EXISTS idx_expense_date_type;
DROP INDEX IF EXISTS idx_expense_created_by;
DROP INDEX IF EXISTS idx_income_date;
DROP INDEX IF EXISTS idx_income_route;
DROP INDEX IF EXISTS idx_mileage_date;
DROP INDEX IF EXISTS idx_deliveryproof_package;
COMMIT;
*/
