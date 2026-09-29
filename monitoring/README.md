# Monitoring — DP

Dashboards y alertas del motor de precios:

- **LTV y conversión por arm de precio** (evolución temporal).
- **Drift de features** (distribución de features online vs. entrenamiento).
- **Latencia** p50/p95 del endpoint `/price`.
- **Regret** estimado de la política vs. baseline de precio fijo.

Stack sugerido: Prometheus + Grafana sobre las métricas expuestas por el servicio;
paneles equivalentes a `../../portfolio/uplift-modeling-pipeline/monitoring`.
