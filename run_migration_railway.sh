#!/bin/bash
# Script para executar no Railway via Web Terminal ou SSH

echo "======================================"
echo "🔄 Aplicando Migração CASCADE DELETE"
echo "======================================"

cd /app

# Verifica se o script de migração existe
if [ ! -f "delivery_system/apply_cascade_migration.py" ]; then
    echo "❌ Script de migração não encontrado!"
    echo "Faça pull do código mais recente primeiro."
    exit 1
fi

# Executa a migração
python delivery_system/apply_cascade_migration.py

echo ""
echo "======================================"
echo "✅ Migração concluída!"
echo "======================================"
