# Redis FastAPI Learning Sandbox

FastAPI + PostgreSQL + Redis playground for learning Redis patterns for interviews.

## Stack

- **FastAPI** — web framework
- **PostgreSQL 16** — relational database (async SQLAlchemy 2.0 + asyncpg)
- **Redis 7** — in-memory store (redis-py async)

## Prerequisites

- Docker & Docker Compose
- Python 3.13+

## Setup

```bash
# 1. Start infra (Postgres + Redis only)
docker compose up -d

# 2. Create virtualenv and install deps
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Start the app
.venv/bin/uvicorn app.main:app --reload
```

## Useful URLs

| URL | Description |
|-----|-------------|
| http://localhost:8000/docs | Swagger UI — interactive API docs |
| http://localhost:8000/redoc | ReDoc alternative docs |
| http://localhost:8000/health | Health check — pings Postgres and Redis |

## Project Structure

```
redis-fast-api/
├── docker-compose.yml   # Postgres + Redis services (app runs manually)
├── .env                 # Connection config
├── requirements.txt
└── app/
    ├── config.py        # Settings via pydantic-settings
    ├── database.py      # Async SQLAlchemy engine + Base
    ├── redis_client.py  # Global aioredis client
    └── main.py          # FastAPI app entrypoint
```

## Environment Variables

Configured in `.env`:

```env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=appdb
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
```


Các lệnh Alembic thường dùng:                                                                                                              
                                                                                                                                             
  # Tạo migration (autogenerate từ model)                                                                                                    
  alembic revision --autogenerate -m "add user table"                                                                                        
                                                                                                                                             
  # Tạo migration rỗng (viết tay)                                                                                                            
  alembic revision -m "seed data"                           
                                                                                                                                             
  # Apply tất cả migration chưa chạy                                                                                                         
  alembic upgrade head
                                                                                                                                             
  # Upgrade lên N bước                                                                                                                       
  alembic upgrade +2
                                                                                                                                             
  # Rollback về migration trước đó                                                                                                           
  alembic downgrade -1
                                                                                                                                             
  # Rollback về migration cụ thể (dùng revision ID)         
  alembic downgrade 972064ed5a49
                                                                                                                                             
  # Rollback toàn bộ về trạng thái trống                                                                                                     
  alembic downgrade base                                                                                                                     
                                                                                                                                             
  # Xem lịch sử migration                                   
  alembic history

  # Xem migration hiện tại DB đang ở                                                                                                         
  alembic current
                                                                                                                                             
  # Xem SQL sẽ chạy mà không apply (dry run)                                                                                                 
  alembic upgrade head --sql