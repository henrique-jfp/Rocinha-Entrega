"""
Script para aplicar migration de automação financeira de rotas.

Adiciona colunas: revenue, driver_salary, status, completed_at, finalized_at,
extra_expenses, extra_income, calculated_km

Uso:
    python apply_route_automation.py
"""

import os
from pathlib import Path
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("❌ Erro: DATABASE_URL não configurada no .env")
    print("Configure a variável DATABASE_URL e tente novamente")
    exit(1)

print(f"🔗 Conectando ao banco de dados...")
print(f"   URL: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'SQLite local'}")

try:
    engine = create_engine(DATABASE_URL)
    
    # Ler o arquivo SQL
    sql_file = Path(__file__).parent / "migrations" / "add_route_automation_fields.sql"
    
    if not sql_file.exists():
        print(f"❌ Erro: Arquivo não encontrado: {sql_file}")
        exit(1)
    
    print(f"📄 Lendo SQL de: {sql_file}")
    
    with open(sql_file, 'r', encoding='utf-8') as f:
        sql_content = f.read()
    
    print(f"\n🚀 Aplicando migration de automação financeira...\n")
    
    with engine.connect() as conn:
        # Verificar se as colunas já existem
        print("🔍 Verificando colunas existentes na tabela 'route'...")
        
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'route'
        """))
        
        existing_columns = {row[0] for row in result.fetchall()}
        print(f"   Colunas existentes: {len(existing_columns)}")
        
        # Colunas que precisam ser adicionadas
        required_columns = {
            'revenue', 'driver_salary', 'status', 'completed_at', 
            'finalized_at', 'extra_expenses', 'extra_income', 'calculated_km'
        }
        
        missing_columns = required_columns - existing_columns
        
        if not missing_columns:
            print("\n✅ Todas as colunas já existem! Nenhuma alteração necessária.")
        else:
            print(f"\n📝 Colunas faltando: {len(missing_columns)}")
            print(f"   {', '.join(sorted(missing_columns))}")
            
            # Executar comandos SQL linha por linha
            commands_executed = 0
            
            for line in sql_content.split('\n'):
                line_stripped = line.strip()
                
                # Ignorar comentários e linhas vazias
                if not line_stripped or line_stripped.startswith('--'):
                    continue
                
                # Executar comandos ALTER TABLE e UPDATE
                if line_stripped.startswith(('ALTER TABLE', 'UPDATE', 'CREATE INDEX')):
                    try:
                        # Extrair informação do comando
                        if 'ADD COLUMN' in line_stripped:
                            col_name = line_stripped.split('ADD COLUMN')[1].split()[0]
                            print(f"   [+] Adicionando coluna: {col_name}...", end=' ')
                        elif 'UPDATE' in line_stripped:
                            print(f"   [↻] Atualizando rotas existentes...", end=' ')
                        elif 'CREATE INDEX' in line_stripped:
                            idx_name = line_stripped.split('idx_')[1].split()[0] if 'idx_' in line_stripped else 'index'
                            print(f"   [#] Criando índice: idx_{idx_name}...", end=' ')
                        else:
                            print(f"   [•] Executando comando...", end=' ')
                        
                        conn.execute(text(line_stripped))
                        conn.commit()
                        print("✅")
                        commands_executed += 1
                        
                    except Exception as e:
                        error_msg = str(e)
                        
                        # Verificar se já existe (não é erro crítico)
                        if 'already exists' in error_msg.lower() or 'duplicate' in error_msg.lower():
                            print("⏭️  (já existe)")
                        else:
                            print(f"❌")
                            print(f"       Erro: {error_msg}")
                            # Não abortar, continuar com próximos comandos
            
            print(f"\n✅ {commands_executed} comandos executados com sucesso!")
        
        # Verificação final
        print(f"\n🔍 Verificando estrutura final da tabela 'route'...\n")
        
        result = conn.execute(text("""
            SELECT 
                column_name,
                data_type,
                column_default,
                is_nullable
            FROM information_schema.columns 
            WHERE table_name = 'route'
            ORDER BY ordinal_position
        """))
        
        columns = result.fetchall()
        
        print("📊 Colunas na tabela 'route':")
        for col_name, data_type, default, nullable in columns:
            default_str = f" DEFAULT {default}" if default else ""
            nullable_str = " NULL" if nullable == 'YES' else " NOT NULL"
            print(f"   • {col_name:<20} {data_type:<15}{default_str}{nullable_str}")
        
        print(f"\n✅ Total de colunas: {len(columns)}")
        
        # Verificar se todas as colunas necessárias estão presentes
        final_columns = {row[0] for row in columns}
        still_missing = required_columns - final_columns
        
        if still_missing:
            print(f"\n⚠️ ATENÇÃO: Ainda faltam colunas: {', '.join(sorted(still_missing))}")
            print("   Execute o script novamente ou aplique manualmente.")
        else:
            print("\n🎉 Migration aplicada com sucesso!")
            print("\n✅ Todas as colunas necessárias estão presentes:")
            for col in sorted(required_columns):
                print(f"   ✓ {col}")
    
    print("\n💡 Próximos passos:")
    print("   1. Reinicie a aplicação (Railway irá reiniciar automaticamente)")
    print("   2. Teste os comandos: /importar, /enviarrota, /rastrear")
    print("   3. Verifique o /relatorio com análise financeira")

except Exception as e:
    print(f"\n❌ Erro ao aplicar migration: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
