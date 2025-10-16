-- Migração para adicionar endereço de casa ao motorista
-- Execute este SQL no Supabase SQL Editor

-- Adicionar colunas de localização de casa
ALTER TABLE "user" 
ADD COLUMN IF NOT EXISTS home_latitude DOUBLE PRECISION,
ADD COLUMN IF NOT EXISTS home_longitude DOUBLE PRECISION,
ADD COLUMN IF NOT EXISTS home_address VARCHAR(500);

-- Criar índice para melhorar performance de consultas de otimização
CREATE INDEX IF NOT EXISTS idx_user_home_location 
ON "user"(home_latitude, home_longitude) 
WHERE home_latitude IS NOT NULL AND home_longitude IS NOT NULL;

-- Confirmar sucesso
SELECT 'Colunas de endereço de casa adicionadas com sucesso!' AS resultado;
