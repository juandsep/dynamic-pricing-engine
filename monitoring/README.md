# Monitoring — Dynamic Pricing Engine

Dashboards and alerts for the pricing service:

| Signal | Why it matters |
|---|---|
| LTV and conversion per price arm | shows which arms are actually winning |
| Feature drift (online vs. training) | a stale feature store silently degrades prices |
| Latency p50/p95 of `/price` | the request path must stay under the 50 ms budget |
| Estimated regret vs. fixed-price baseline | the business case, tracked continuously |
| Posterior uncertainty per arm | arms that never converge indicate a broken reward signal |

Suggested stack: Prometheus + Grafana scraping the service metrics, with panels
mirroring the ones in `uplift-modeling-pipeline/monitoring`.
