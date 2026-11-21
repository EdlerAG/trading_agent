"""AI Model Cartridges layer: Hot-Swap loader and pluggable cartridge interfaces."""

try:
    from app.cartridges.feature_pipe_v58 import (
        ORTHO_FEATURE_NAMES_V58,
        compute_v58_features_float32,
        compute_core_breadth_and_macro,
    )
    from app.cartridges.v58_grand_master_cartridge import V58GrandMasterCartridge
except ImportError:
    ORTHO_FEATURE_NAMES_V58 = ()
    compute_v58_features_float32 = None
    compute_core_breadth_and_macro = None
    V58GrandMasterCartridge = None

from app.cartridges.cartridge_loader import CartridgeLoaderService

__all__ = [
    "ORTHO_FEATURE_NAMES_V58",
    "compute_v58_features_float32",
    "compute_core_breadth_and_macro",
    "V58GrandMasterCartridge",
    "CartridgeLoaderService",
]
