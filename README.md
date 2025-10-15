# Rocinha Entrega

Mini-sistema de gestão de entregas: FastAPI (web/API + Leaflet), Bot do Telegram (python-telegram-bot) e banco relacional (SQLite local ou Postgres/Supabase em produção).

## Estrutura
- `delivery_system/app.py` FastAPI com endpoints e página do mapa
- `delivery_system/bot.py` Bot Telegram (long polling)
- `delivery_system/database.py` Modelos SQLAlchemy 2.0
- `delivery_system/templates/` HTML/Jinja2 (Leaflet)
- `delivery_system/static/` JS/CSS do mapa
- `delivery_system/seed.py` Seed de dados (dev)
- `delivery_system/requirements.txt` Dependências
- `delivery_system/Dockerfile` Build de imagem para web/worker
- `render.yaml` Blueprint para Render (web + worker)

## Execução local (Windows)
1. Crie venv e instale libs:
```powershell
cd "c:\Rocinha Entrega\delivery_system"
python -m venv ..\.venv
..\.venv\Scripts\pip install -r requirements.txt
```
2. Configure `.env` a partir de `.env.example`.
3. Inicie backend e bot:
```powershell
# backend ouvindo na rede local (0.0.0.0:8001)
./start_backend.ps1
# bot
./start_bot.ps1
```

## Deploy em Render (sem dormir)
1. Suba este repo no GitHub.
2. Em Render: New → Blueprint → selecione este repo (usa `render.yaml`).
3. Configure variáveis:
   - Web (entrega-web): `BASE_URL=https://SEUWEB.onrender.com`, `DATABASE_URL`, `BOT_USERNAME`
   - Worker (entrega-bot): `BOT_TOKEN`, `BOT_USERNAME`, `BASE_URL=https://SEUWEB.onrender.com`, `DATABASE_URL`
4. Banco: use Render PostgreSQL ou Supabase (veja abaixo).
5. Teste `GET /health` na web. No Telegram: `/start`, `/importar`, `/enviarrota`.

## Supabase (Plano Free)
- Funciona, mas atenção a limites de recursos e conexões.
- Use a URL de Postgres do Supabase e prefira o pgbouncer na porta 6543 (pool de conexões).
- Exemplo de `DATABASE_URL`:
```
postgresql://postgres:<SENHA>@<HOST>.supabase.co:6543/postgres?sslmode=require
```
- `database.py` já está com `pool_pre_ping=True` e `pool_recycle=300` para evitar conexões mortas.
- Em cargas maiores, considere um Postgres gerenciado com mais recursos.

## Notas importantes
- Em produção, use `DATABASE_URL` (Postgres). Sem isso, cai no SQLite local da imagem (não recomendado).
- O bot usa long polling (worker dedicado). Sem webhooks.
- Fotos de comprovante não são salvas em disco; ficam no Telegram (armazenamos apenas file_id). Você baixa direto pelo app.

## Como criar o repositório e dar push
```powershell
# na raiz c:\Rocinha Entrega
git init
git remote add origin https://github.com/<SEU_USER>/Rocinha-Entrega.git
git add .
git commit -m "Rocinha Entrega - MVP pronto para deploy"
# define branch principal
git branch -M main
# envia
git push -u origin main
```

## Variáveis de ambiente
Veja `delivery_system/.env.example`.
