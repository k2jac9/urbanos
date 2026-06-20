"""UrbanOS — turning urban data into real-time insight.

One product, two subpackages over a shared kernel/lens architecture (ADR-0034):

    urbanos.kernel  the simulation kernel + the unified shell/API and its lenses
                    (was the ``urban_os`` package)
    urbanos.risk    the address-level civic-risk engine, surfaced as the Risk lens
                    (was the ``civic_analyst`` package)

The Python packages were unified under ``urbanos`` after the product was renamed
UrbanOS; the public behaviour, golden numbers, and offline guarantees are unchanged.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
