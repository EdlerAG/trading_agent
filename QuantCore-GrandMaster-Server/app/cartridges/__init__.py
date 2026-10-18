"""AI Model Cartridges layer: Hot-Swap loader, vectorized float32 feature pipes, V23 Grand-Master & Legacy V7 adapters."""

from app.cartridges.feature_pipe_v23 import (
    compute_v23_features_float32,
    compute_v7_8_features_float32,
    compute_core_market_breadth,
)
from app.cartridges.v23_grand_master_cartridge import V23GrandMasterCartridge
from app.cartridges.legacy_v7_adapter import LegacyV7CartridgeAdapter
from app.cartridges.cartridge_loader import CartridgeLoaderService

__all__ = [
    "compute_v23_features_float32",
    "compute_v7_8_features_float32",
    "compute_core_market_breadth",
    "V23GrandMasterCartridge",
    "LegacyV7CartridgeAdapter",
    "CartridgeLoaderService",
]