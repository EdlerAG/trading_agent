"""AI Model Cartridges layer: Hot-Swap loader, vectorized float32 feature pipes, and V58 Pure SOTA Cartridge."""

from app.cartridges.feature_pipe_v58 import (
    ORTHO_FEATURE_NAMES_V58,
    compute_v58_features_float32,
    compute_core_breadth_and_macro,
)
from app.cartridges.v58_grand_master_cartridge import V58GrandMasterCartridge
from app.cartridges.cartridge_loader import CartridgeLoaderService

__all__ = [
    "ORTHO_FEATURE_NAMES_V58",
    "compute_v58_features_float32",
    "compute_core_breadth_and_macro",
    "V58GrandMasterCartridge",
    "CartridgeLoaderService",
]
