"""Dynamic pricing engine."""

from __future__ import annotations

import os


def main() -> None:
    """Run the pricing API. Console script entry point: `dp`."""
    import uvicorn

    uvicorn.run("dp.api:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    main()
