# tests for Dynamic Pricing (dp) – placeholder

import pytest
from dp.thompson import ThompsonSampler

def test_sampler_range():
    sampler = ThompsonSampler((10, 20))
    price = sampler.sample('user123')
    assert 10 <= price <= 20
