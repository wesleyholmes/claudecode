"""Affiliate network adapters."""
from .rakuten import RakutenAdapter
from .cj import CJAdapter
from .optimise import OptimiseAdapter

ALL_ADAPTERS = [RakutenAdapter(), CJAdapter(), OptimiseAdapter()]

__all__ = ["RakutenAdapter", "CJAdapter", "OptimiseAdapter", "ALL_ADAPTERS"]
