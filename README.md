# DP — Motor de Precios Dinámicos

Motor de precios en tiempo real basado en **Thompson Sampling** por cliente/segmento, orientado a maximizar el **LTV**. Feature store con **Redis** (online) + **DynamoDB** (persistencia/batch), tracking y registro en **MLflow**, reentrenamiento automatizado vía **GitHub Actions** y despliegue continuo en **AWS ECS** (Fargate).

## Arquitectura

```
cliente ──▶ FastAPI /price ──▶ ThompsonSampler ──▶ FeatureStore (Redis)
                                   │                     │
                                   └── eventos ──▶ DynamoDB (offline)
                                   │
                                   └── métricas ──▶ MLflow (runs + registry)
```

## Estructura

```
dp/
├─ src/dp/
│   ├─ __init__.py     # entrypoint (`dp` console script)
│   ├─ api.py          # FastAPI, endpoint /price
│   ├─ thompson.py     # algoritmo Thompson Sampling
│   └─ store.py        # FeatureStore: Redis (online) / DynamoDB (persistencia)
├─ tests/              # pytest
├─ scripts/            # reentrenamiento, bootstrap, migraciones
├─ docker/             # Dockerfile del servicio
├─ infra/              # IaC (ECS, ElastiCache, DynamoDB, ECR)
├─ monitoring/         # dashboards / alertas (Prometheus, Grafana)
├─ .github/workflows/  # CI + reentrenamiento programado
├─ Dockerfile
└─ pyproject.toml      # deps gestionadas con uv
```

## Quickstart

```bash
cd dp
uv sync                 # instala el entorno (.venv) desde uv.lock
uv run pytest -q        # tests
uv run dp               # levanta el servicio (uvicorn en :8000)
```

## Configuración

| Variable | Descripción |
|---|---|
| `REDIS_URL` | endpoint online feature store |
| `DYNAMODB_TABLE` | tabla de eventos/atributos |
| `MLFLOW_TRACKING_URI` | backend de tracking (compartido con `portfolio-infra/mlflow`) |
| `PRICE_MIN` / `PRICE_MAX` | rango de precios por arm |

## Despliegue

`docker build -t dp .` → ECR → ECS Service (Fargate). Ver `infra/` y `.github/workflows/`.

> Referencia de estructura y CI: `../portfolio/uplift-modeling-pipeline`.
