-- Migração para adicionar coluna order_in_route à tabela package
-- Execute este SQL no Supabase SQL Editor

ALTER TABLE package 
ADD COLUMN IF NOT EXISTS order_in_route INTEGER;

-- Criar índice para melhorar performance de consultas
CREATE INDEX IF NOT EXISTS idx_package_order_in_route 
ON package(route_id, order_in_route);

-- Confirmar sucesso
SELECT 'Coluna order_in_route adicionada com sucesso!' AS resultado;
