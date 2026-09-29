"""FastAPI service for Dynamic Pricing (DP).
Provides a `/price` endpoint that returns a price computed by the Thompson Sampling model.
"""

from fastapi import FastAPI
from .thompson import ThompsonSampler

app = FastAPI()

sampler = ThompsonSampler()

@app.get("/price")
async def get_price(user_id: str):
    """Return a price suggestion for the given user.
    In a real implementation the sampler would use features from the feature store.
    """
    price = sampler.sample(user_id)
    return {"user_id": user_id, "price": price}
