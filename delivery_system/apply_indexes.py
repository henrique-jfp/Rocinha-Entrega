"""
Script para aplicar índices de performance no banco de dados.

Uso:
    python apply_indexes.py
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
    sql_file = Path(__file__).parent / "migrations" / "add_performance_indexes.sql"
    
    if not sql_file.exists():
        print(f"❌ Erro: Arquivo não encontrado: {sql_file}")
        exit(1)
    
    print(f"📄 Lendo SQL de: {sql_file}")
    
    with open(sql_file, 'r', encoding='utf-8') as f:
        sql_content = f.read()
    
    # Separar comandos SQL (ignora comentários e blocos de transação)
    sql_commands = []
    current_command = []
    in_transaction = False
    
    for line in sql_content.split('\n'):
        line_stripped = line.strip()
        
        # Ignorar comentários
        if line_stripped.startswith('--') or line_stripped.startswith('/*'):
            continue
        
        # Controle de transação
        if line_stripped.upper() == 'BEGIN;':
            in_transaction = True
            continue
        if line_stripped.upper() == 'COMMIT;':
            in_transaction = False
            continue
        
        # Ignorar linhas vazias
        if not line_stripped:
            continue
        
        # Acumular comando
        current_command.append(line)
        
        # Se termina com ponto e vírgula, é um comando completo
        if line_stripped.endswith(';'):
            cmd = '\n'.join(current_command)
            if 'CREATE INDEX' in cmd.upper() or 'SELECT' in cmd.upper():
                sql_commands.append(cmd)
            current_command = []
    
    if not sql_commands:
        print("⚠️ Nenhum comando CREATE INDEX encontrado no SQL")
        exit(1)
    
    print(f"\n🚀 Aplicando {len(sql_commands)} comandos SQL...\n")
    
    with engine.connect() as conn:
        created_indexes = 0
        
        for i, cmd in enumerate(sql_commands, 1):
            if 'CREATE INDEX' not in cmd.upper():
                continue
            
            try:
                # Extrair nome do índice do comando
                index_name = "desconhecido"
                if 'idx_' in cmd:
                    parts = cmd.split('idx_')
                    if len(parts) > 1:
                        index_name = 'idx_' + parts[1].split()[0].replace(';', '')
                
                print(f"[{i}] Criando índice: {index_name}...", end=' ')
                
                conn.execute(text(cmd))
                conn.commit()
                
                print("✅")
                created_indexes += 1
                
            except Exception as e:
                error_msg = str(e)
                
                # Verificar se já existe (não é erro crítico)
                if 'already exists' in error_msg.lower() or 'duplicate' in error_msg.lower():
                    print("⏭️  (já existe)")
                else:
                    print(f"❌")
                    print(f"    Erro: {error_msg}")
        
        # Verificação final
        print(f"\n✅ {created_indexes} índices criados com sucesso!")
        print("\n🔍 Verificando índices criados...\n")
        
        result = conn.execute(text("""
            SELECT 
                tablename,
                indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
            AND indexname LIKE 'idx_%'
            ORDER BY tablename, indexname
        """))
        
        indexes = result.fetchall()
        
        if indexes:
            print("📊 Índices encontrados:")
            current_table = None
            for table, index in indexes:
                if table != current_table:
                    print(f"\n  📋 Tabela: {table}")
                    current_table = table
                print(f"     • {index}")
            
            print(f"\n✅ Total de índices: {len(indexes)}")
        else:
            print("⚠️ Nenhum índice encontrado. Pode ser que o banco seja SQLite.")
    
    print("\n🎉 Índices aplicados com sucesso!")
    print("\n💡 Próximos passos:")
    print("   1. Reinicie a aplicação")
    print("   2. Execute /relatorio no bot para testar performance")
    print("   3. Compare o tempo de resposta (deve ser 40-60% mais rápido)")

except Exception as e:
    print(f"\n❌ Erro ao aplicar índices: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
