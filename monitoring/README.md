# Monitoring — Dynamic Pricing Engine

What the service already exposes on `/metrics` (Prometheus text format, per replica):

| Metric | Why it matters |
|---|---|
| `dp_request_seconds{path,status}` | `/price` must stay inside its latency budget; 5xx show up by route |
| `dp_prices_served_total{policy_version}` | which policy is actually serving, and how much |
| `dp_rewards_total{outcome}` | `applied`, `late`, `duplicate`, `unknown_impression`, `failed`: a rising `failed` or `unknown_impression` means the reward signal is broken |
| `dp_price_guard_clamped_total` | arms outside `PRICE_MIN`/`PRICE_MAX`; non-zero means the catalogue and the guard disagree |
| `dp_rejected_total{reason}` | 401, 429 and 413 by cause |

F8 adds drift: PSI on the traffic mix (products requested) and on the served price
distribution, against a `reference_profile.json` registered next to the policy — the
reference project's drift job, applied to prices.

Nothing scrapes these on Azure today: a Prometheus or Managed Grafana instance would be the
first always-on line item. For a demo, `curl $APP_URL/metrics` is the dashboard.
