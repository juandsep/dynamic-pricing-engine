# PLAN — Motor de Precios Dinámicos (DP)

Objetivo: asignar precio en tiempo real con Thompson Sampling para maximizar LTV, con feature store, reentrenamiento automatizado y despliegue continuo.

## Fases

- [x] **F0 · Fundaciones** — repo git, proyecto `uv`, lock, `pytest`, CI base.
- [ ] **F1 · Feature store** — `store.py`: Redis online (lectura <10 ms) + DynamoDB (persistencia/eventos). Contratos de features y versionado.
- [ ] **F2 · Algoritmo** — `thompson.py`: posterior Beta por *arm* precio y por segmento; reward = margen/LTV observado. Política de exploración y guardas (price floor/ceiling).
- [ ] **F3 · API** — `api.py`: `GET /price`, `POST /reward` (feedback de conversión), healthchecks, batching de features.
- [ ] **F4 · Tracking** — MLflow: logging de parámetros, métricas (LTV, conversión, regret), registro de políticas candidatas.
- [ ] **F5 · Reentrenamiento** — GitHub Actions programado (cron semanal) que recalibra priors y registra en MLflow.
- [ ] **F6 · Despliegue** — Docker → ECR → ECS Fargate; task definition + service + autoscaling (`infra/`).
- [ ] **F7 · Observabilidad** — dashboards (LTV por arm, drift de features, latencia), alertas.

## Métricas de éxito

- LTV incremental vs. baseline (precio fijo) > umbral acordado.
- p95 de latencia `/price` < 50 ms.
- Cero violaciones de price floor/ceiling.

## Referencia

Estructura, CI y convenciones basadas en `../portfolio/uplift-modeling-pipeline`.
