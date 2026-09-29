# Dynamic Pricing Engine · Motor de Precios Dinámicos con Feature Store

> Precios en tiempo real con **Thompson Sampling** para maximizar el **LTV**, servidos desde una **feature store** (Redis + Cosmos DB) y desplegados en **Azure** con reentrenamiento automatizado y tracking en MLflow.

---

## El problema

Fijar un precio único para todo el catálogo y para todos los clientes deja dinero sobre la mesa:

- A los clientes con alta propensión se les cobra **por debajo** de lo que están dispuestos a pagar.
- A los sensibles al precio se les cobra **por encima** y se pierden.
- El precio óptimo **cambia con el tiempo** (estacionalidad, stock, competencia, señales del cliente) y un modelo estático no lo sigue.

## La solución

Un motor que **asigna precio por cliente en tiempo real** tratando cada nivel de precio como un *arm* de un problema de **multi-armed bandit** y resolviéndolo con **Thompson Sampling**:

1. Muestrea de la posterior (Beta) de cada *arm* de precio para el segmento del cliente.
2. Elige el *arm* con mayor valor esperado y respeta los límites de precio (`floor`/`ceiling`).
3. Observa el resultado (conversión, margen, LTV) y **actualiza la posterior**.
4. Explora de forma natural: los *arms* con incertidumbre siguen recibiendo tráfico, sin apagarlos prematuramente.

El resultado es una política que **aprende sola**, converge al precio óptimo por segmento y sigue el *drift* sin reentrenamientos manuales.

## Arquitectura

```
                        ┌───────────────────────────┐
   cliente ────▶  GET /price ──▶  ThompsonSampler    │
                        │              │             │
                        │              ▼             │
                        │      FeatureStore           │
                        │        ├─ Azure Cache for Redis   (online, <10 ms)
                        │        └─ Cosmos DB               (persistencia / eventos)
                        │              │
                        │              ▼
                        └──────▶ MLflow (runs, métricas, registry)
                                       ▲
                                       │
                     GitHub Actions (cron semanal) ──▶ scripts/retrain.py
```

## Stack

| Capa | Tecnología |
|---|---|
| API | FastAPI + Uvicorn |
| Algoritmo | Thompson Sampling (posterior Beta) sobre NumPy/SciPy |
| Feature store | Azure Cache for Redis (online) · Azure Cosmos DB (offline/eventos) |
| Tracking / registry | MLflow |
| Reentrenamiento | GitHub Actions (cron) |
| Despliegue | Azure Container Apps + Azure Container Registry |
| Secretos | Azure Key Vault (auth OIDC federada en CI) |
| Observabilidad | Application Insights + Log Analytics |
| Gestión de entorno | **uv** (`pyproject.toml` + `uv.lock`) |
| Tests | pytest |

## Estado del proyecto

Roadmap detallado en [`PLAN.md`](./PLAN.md).

- [x] **F0** · Fundaciones: repo, proyecto `uv`, lock, tests, CI base
- [ ] **F1** · Feature store: Redis online + Cosmos DB, contratos y versionado de features
- [ ] **F2** · Algoritmo: posterior Beta por arm/segmento, guardas de precio, reward = margen/LTV
- [ ] **F3** · API: `GET /price`, `POST /reward`, healthchecks
- [ ] **F4** · Tracking MLflow: parámetros, métricas (LTV, conversión, regret), registry
- [ ] **F5** · Reentrenamiento automatizado (GitHub Actions, cron semanal)
- [ ] **F6** · Despliegue en Azure (Container Apps, ACR, Key Vault)
- [ ] **F7** · Observabilidad: dashboards de LTV por arm, drift, latencia, regret

## Estructura

```
dynamic-pricing-engine/
├─ src/dp/
│   ├─ __init__.py     # entrypoint (`dp` console script)
│   ├─ api.py          # FastAPI, endpoint /price
│   ├─ thompson.py     # Thompson Sampling (posterior Beta)
│   └─ store.py        # FeatureStore: Redis (online) / Cosmos DB (persistencia)
├─ tests/              # pytest
├─ scripts/            # retrain.py, bootstrap, migraciones
├─ infra/              # Terraform (azurerm): Container Apps, ACR, Redis, Cosmos, Key Vault
├─ monitoring/         # dashboards y alertas
├─ .github/workflows/  # CI (+ reentrenamiento programado)
├─ Dockerfile
├─ PLAN.md
└─ pyproject.toml      # dependencias gestionadas con uv
```

## Quickstart

```bash
git clone https://github.com/juandsep/dynamic-pricing-engine.git
cd dynamic-pricing-engine

uv sync                # crea .venv desde uv.lock
uv run pytest -q       # tests
uv run dp              # levanta la API en http://localhost:8000
```

Probar el endpoint:

```bash
curl "http://localhost:8000/price?user_id=user-42"
```

## Configuración

| Variable | Descripción |
|---|---|
| `REDIS_URL` | Azure Cache for Redis (feature store online) |
| `COSMOS_ENDPOINT` / `COSMOS_DATABASE` | Cosmos DB (eventos y atributos) |
| `MLFLOW_TRACKING_URI` | backend de tracking / registry |
| `PRICE_MIN` / `PRICE_MAX` | rango permitido de precios |
| `AZURE_KEYVAULT_URL` | origen de secretos en runtime |

## Despliegue

`docker build -t dynamic-pricing-engine .` → push a **Azure Container Registry** → `az containerapp update`.
Terraform e instrucciones en [`infra/`](./infra/README.md); pipeline en `.github/workflows/`.

## Métricas de éxito

- LTV incremental vs. baseline de precio fijo por encima del umbral objetivo.
- Latencia p95 de `/price` < 50 ms.
- Cero violaciones de `PRICE_MIN` / `PRICE_MAX`.

## Referencias

Estructura, CI y convenciones alineadas con el pipeline de referencia `uplift-modeling-pipeline`.

---

**Stack:** Python 3.11 · uv · FastAPI · NumPy/SciPy · Redis · Azure Cosmos DB · MLflow · Azure Container Apps · GitHub Actions
