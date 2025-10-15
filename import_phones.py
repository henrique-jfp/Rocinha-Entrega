#!/usr/bin/env python3
"""
Script para importar telefones extraídos do SPX para o banco de dados
Lê o arquivo phones.json gerado pelo spx_scraper.py e atualiza os pacotes
"""

import json
import sys
from pathlib import Path

# Adiciona o diretório delivery_system ao path
sys.path.insert(0, str(Path(__file__).parent / "delivery_system"))

from database import SessionLocal, Package


def import_phones_from_json(json_file: str = "phones.json"):
    """Importa telefones do JSON para o banco"""
    
    # Lê o JSON
    with open(json_file, "r", encoding="utf-8") as f:
        phones_data = json.load(f)
    
    print(f"📂 Lendo {json_file}...")
    print(f"   Total de registros: {len(phones_data)}")
    print()
    
    # Atualiza banco
    db = SessionLocal()
    try:
        updated = 0
        not_found = 0
        
        for tracking_code, phone in phones_data.items():
            if not phone:
                continue
            
            # Busca pacote pelo código de rastreio
            package = db.query(Package).filter(
                Package.tracking_code == tracking_code
            ).first()
            
            if package:
                # Atualiza telefone
                package.phone = phone
                updated += 1
                print(f"✅ {tracking_code}: {phone}")
            else:
                not_found += 1
                print(f"⚠️  {tracking_code}: Pacote não encontrado no banco")
        
        db.commit()
        
        print()
        print("=" * 60)
        print(f"✅ Importação concluída!")
        print(f"   Atualizados: {updated}")
        print(f"   Não encontrados: {not_found}")
        print("=" * 60)
        
    except Exception as e:
        db.rollback()
        print(f"❌ Erro: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Importa telefones do JSON para o banco")
    parser.add_argument(
        "--file",
        default="phones.json",
        help="Arquivo JSON com os telefones (padrão: phones.json)"
    )
    
    args = parser.parse_args()
    
    if not Path(args.file).exists():
        print(f"❌ Arquivo não encontrado: {args.file}")
        print()
        print("Execute primeiro o spx_scraper.py para gerar o phones.json")
        sys.exit(1)
    
    import_phones_from_json(args.file)
