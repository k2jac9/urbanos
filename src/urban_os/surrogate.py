"""Neural surrogate of the optimizer objective ``J(levers)`` (ADR-0027) — a genuine,
*honestly-scoped* NVIDIA PhysicsNeMo (formerly Modulus) seam.

**The honest fit.** ``optimize()`` does simulation-in-the-loop search: every lever
combo runs a full deterministic kernel (substrate + time loop + four operators). At
*city scale* that grid is intractable, which is exactly where a learned **surrogate
operator** belongs — PhysicsNeMo trains a fast neural approximation of ``J(levers)``
(the transport dynamics on the capacitated substrate is PDE-like), so the search can
rank thousands of combos cheaply and the exact kernel only re-validates a shortlist.

**The honest catch (mirrors cuOpt in ADR-0024).** A surrogate needs a trained
checkpoint (lever→J rollouts) and validation; a learned approximation is a *black
box*, which cuts against the "deterministic simulation, not a lookup" pitch. So we
ship the **seam/interface with the exact kernel as the reference**, NOT a trained
model:

  * The surrogate never decides anything. ``optimize()`` still picks ``best`` by the
    *exact* kernel ``J``; the surrogate's prediction is recorded alongside (for
    transparency / to show accuracy), so an approximate number can never reach the UI.
  * Default OFF (``URBANOS_SURROGATE`` unset) → behaviour byte-identical to grid; the
    golden urban_os numbers and CI are untouched.
  * Enabled but no PhysicsNeMo / no checkpoint → ``load()`` returns False, backend
    stays ``"none"``, still identical to grid. Training a real checkpoint is the
    documented next step (ADR-0027), deliberately not faked here.

``SURROGATE_BACKEND`` records what ran: ``"none"`` (exact kernel only) or
``"physicsnemo"`` (a trained surrogate produced predictions).
"""
from __future__ import annotations

import os

# Which backend produced the last J predictions: "none" (exact kernel only — the
# honest default) or "physicsnemo" (a trained PhysicsNeMo/Modulus surrogate ran).
SURROGATE_BACKEND: str = "none"


def surrogate_enabled() -> bool:
    """Opt-in: ``URBANOS_SURROGATE=1`` on a box with PhysicsNeMo + a trained
    checkpoint (``URBANOS_SURROGATE_CKPT``) present."""
    return os.environ.get("URBANOS_SURROGATE", "").strip().lower() in {"1", "true", "yes"}


def _checkpoint_path() -> str:
    return os.environ.get("URBANOS_SURROGATE_CKPT", "").strip()


class JSurrogate:
    """Loaded PhysicsNeMo surrogate that predicts ``J`` from a lever-param dict.

    The interface is deliberately tiny (``predict(params) -> float``) so the optimizer
    can consult it without knowing anything about the model. The reference
    implementation loads a PhysicsNeMo checkpoint; absent the library or a checkpoint,
    ``load()`` returns None and the optimizer runs the exact kernel for everything.
    """

    def __init__(self, model, lever_names: list[str]) -> None:
        self._model = model
        self._lever_names = lever_names

    @classmethod
    def load(cls, lever_names: list[str]) -> "JSurrogate | None":
        """Try to load a trained PhysicsNeMo surrogate; return None (→ exact kernel
        fallback) if the library or checkpoint is missing. Never raises."""
        if not surrogate_enabled():
            return None
        ckpt = _checkpoint_path()
        if not ckpt:
            return None
        try:  # pragma: no cover - exercised only on a box with PhysicsNeMo installed
            # PhysicsNeMo (formerly NVIDIA Modulus). Import lazily so the dep is never
            # needed in CI / the demo venv.
            import physicsnemo  # type: ignore  # noqa: F401
            import torch  # type: ignore

            model = torch.load(ckpt, map_location="cpu")
            model.eval()
            return cls(model, lever_names)
        except Exception:  # missing lib / bad checkpoint → honest exact-kernel fallback
            return None

    def predict(self, params: dict) -> float:  # pragma: no cover - box-only path
        """Approximate ``J`` for a lever-param dict using the trained surrogate."""
        import torch  # type: ignore

        x = torch.tensor(
            [[float(params.get(name, 0.0)) for name in self._lever_names]],
            dtype=torch.float32,
        )
        with torch.no_grad():
            return float(self._model(x).reshape(-1)[0].item())
