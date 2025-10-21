#!/usr/bin/env python3
"""
Script para aplicar migração de CASCADE DELETE em Expense e Income

Este script altera as foreign keys de route_id em Expense e Income
de ON DELETE SET NULL para ON DELETE CASCADE.

Resultado: Quando uma rota é excluída, TODAS as receitas e despesas
vinculadas são automaticamente excluídas também.
"""

import sqlite3
import os
from pathlib import Path

def get_db_path():
    """Retorna caminho do banco de dados"""
    db_url = os.getenv("DATABASE_URL", "sqlite:///./rocinha_entrega.db")
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
        # Remove ./ se existir
        if db_path.startswith("./"):
            db_path = db_path[2:]
        return db_path
    else:
        raise ValueError(f"DATABASE_URL não é SQLite: {db_url}")

def apply_migration():
    """Aplica migração de CASCADE DELETE"""
    
    db_path = get_db_path()
    
    if not os.path.exists(db_path):
        print(f"❌ Banco de dados não encontrado: {db_path}")
        return False
    
    print(f"📊 Banco de dados: {db_path}")
    
    # Backup antes de migrar
    import shutil
    from datetime import datetime
    backup_path = f"{db_path}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(db_path, backup_path)
    print(f"✅ Backup criado: {backup_path}")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Verifica estrutura atual
        print("\n📋 Estrutura atual:")
        cursor.execute("SELECT sql FROM sqlite_master WHERE name='expense'")
        print("Expense:", cursor.fetchone()[0])
        
        cursor.execute("SELECT sql FROM sqlite_master WHERE name='income'")
        print("Income:", cursor.fetchone()[0])
        
        # Desativa foreign keys temporariamente
        cursor.execute("PRAGMA foreign_keys = OFF")
        
        print("\n🔄 Aplicando migração...")
        
        # ========== EXPENSE ==========
        print("  - Migrando tabela expense...")
        
        # Cria tabela nova
        cursor.execute("""
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
            )
        """)
        
        # Copia dados
        cursor.execute("""
            INSERT INTO expense_new 
            SELECT id, date, type, description, amount, fuel_type, fuel_liters, 
                   employee_name, route_id, confirmed, created_by, created_at
            FROM expense
        """)
        
        # Remove e renomeia
        cursor.execute("DROP TABLE expense")
        cursor.execute("ALTER TABLE expense_new RENAME TO expense")
        cursor.execute("CREATE INDEX ix_expense_date ON expense(date)")
        
        print("  ✅ Expense migrada")
        
        # ========== INCOME ==========
        print("  - Migrando tabela income...")
        
        # Cria tabela nova
        cursor.execute("""
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
            )
        """)
        
        # Copia dados
        cursor.execute("""
            INSERT INTO income_new 
            SELECT id, date, route_id, description, amount, created_by, created_at
            FROM income
        """)
        
        # Remove e renomeia
        cursor.execute("DROP TABLE income")
        cursor.execute("ALTER TABLE income_new RENAME TO income")
        cursor.execute("CREATE INDEX ix_income_date ON income(date)")
        
        print("  ✅ Income migrada")
        
        # Reativa foreign keys
        cursor.execute("PRAGMA foreign_keys = ON")
        
        conn.commit()
        
        # Verifica nova estrutura
        print("\n✅ Nova estrutura:")
        cursor.execute("SELECT sql FROM sqlite_master WHERE name='expense'")
        expense_sql = cursor.fetchone()[0]
        print("Expense:", expense_sql)
        
        cursor.execute("SELECT sql FROM sqlite_master WHERE name='income'")
        income_sql = cursor.fetchone()[0]
        print("Income:", income_sql)
        
        # Valida que CASCADE está presente
        if "ON DELETE CASCADE" in expense_sql and "ON DELETE CASCADE" in income_sql:
            print("\n🎉 Migração aplicada com sucesso!")
            print("✅ Agora ao excluir uma rota, receitas e despesas são excluídas automaticamente")
            return True
        else:
            print("\n⚠️ Aviso: CASCADE pode não ter sido aplicado corretamente")
            return False
            
    except Exception as e:
        print(f"\n❌ Erro na migração: {e}")
        conn.rollback()
        print(f"💾 Restaure o backup se necessário: {backup_path}")
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    print("=" * 60)
    print("MIGRAÇÃO: CASCADE DELETE em Expense e Income")
    print("=" * 60)
    
    success = apply_migration()
    
    if success:
        print("\n✅ Tudo pronto! Agora você pode excluir rotas com segurança.")
        print("   - Ao excluir uma rota, TUDO relacionado será excluído:")
        print("     • Pacotes")
        print("     • Provas de entrega")
        print("     • Receitas")
        print("     • Despesas")
        print("     • Salários a pagar")
    else:
        print("\n❌ Migração falhou. Verifique os erros acima.")
