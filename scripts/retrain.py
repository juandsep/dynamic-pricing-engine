"""Reentrenamiento programado del motor de precios.

Ejecutado por GitHub Actions (cron). Recalibra los priors del Thompson Sampler
a partir de los eventos almacenados en DynamoDB y registra la política en MLflow.

Placeholder: implementar la carga de eventos y el cálculo de posteriores.
"""

from __future__ import annotations


def main() -> None:
    # TODO: leer eventos DynamoDB -> calcular posteriores Beta por arm/segmento
    # TODO: mlflow.log_params / log_metrics + registrar política candidata
    print("retrain: noop (placeholder)")


if __name__ == "__main__":
    main()
