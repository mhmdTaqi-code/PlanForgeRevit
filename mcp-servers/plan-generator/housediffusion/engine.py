"""
Run HouseDiffusion from a bubble diagram and return a plan_schema dict.

This is the only module that needs PyTorch + the HouseDiffusion source + a
trained checkpoint. It is deliberately import-light at module load: nothing
heavy is imported until you actually call `generate_from_diagram`, so the MCP
server stays fast to start even when this engine is unavailable.

Availability is gated on three things, all overridable by env var / argument:
  * the HouseDiffusion source on sys.path   (HOUSE_DIFFUSION_SRC, default
    <repo>/AIProjects/house_diffusion)
  * a checkpoint .pt file                    (HOUSE_DIFFUSION_CKPT)
  * torch importable

Because the model needs a GPU for sane speed, the intended runner is the Colab
notebook in notebooks/HouseDiffusion_TarkeebAI.ipynb. Locally, `availability()`
reports exactly what is missing so the MCP tool can give an actionable message
instead of a stack trace.
"""

import os
import sys
from pathlib import Path

from . import graph_to_model_input as g2m
from . import model_output_to_plan as out

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_SRC = _REPO_ROOT / "AIProjects" / "house_diffusion"


def _src_dir() -> Path:
    return Path(os.environ.get("HOUSE_DIFFUSION_SRC", _DEFAULT_SRC))


def _ckpt_path():
    return os.environ.get("HOUSE_DIFFUSION_CKPT")


def availability() -> dict:
    """Report whether the engine can run, and what is missing if not."""
    missing = []
    src = _src_dir()
    if not (src / "house_diffusion" / "script_util.py").is_file():
        missing.append(f"HouseDiffusion source not found at {src} (set HOUSE_DIFFUSION_SRC)")
    try:
        import torch  # noqa: F401
    except ImportError:
        missing.append("PyTorch is not installed (pip install torch)")
    ckpt = _ckpt_path()
    if not ckpt:
        missing.append("no checkpoint set (set HOUSE_DIFFUSION_CKPT to a .pt file)")
    elif not Path(ckpt).is_file():
        missing.append(f"checkpoint not found at {ckpt}")
    return {"ready": not missing, "missing": missing}


def _build_model_and_diffusion():
    src = str(_src_dir())
    if src not in sys.path:
        sys.path.insert(0, src)
    import argparse
    import torch
    from house_diffusion.script_util import (
        model_and_diffusion_defaults,
        create_model_and_diffusion,
        args_to_dict,
        update_arg_parser,
    )

    defaults = dict(model_and_diffusion_defaults())
    defaults.update(dataset="rplan", analog_bit=False)
    args = argparse.Namespace(**defaults)
    update_arg_parser(args)

    model, diffusion = create_model_and_diffusion(
        **args_to_dict(args, model_and_diffusion_defaults().keys())
    )
    state = torch.load(_ckpt_path(), map_location="cpu")
    model.load_state_dict(state)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device).eval()
    return model, diffusion, device


def generate_from_diagram(diagram: dict, num_samples: int = 1, sample_index: int = 0,
                          clip_denoised: bool = True) -> dict:
    """Bubble diagram -> plan_schema dict, via a full HouseDiffusion sampling run.

    Raises RuntimeError (with the list of what is missing) if the engine is not
    available locally — callers should surface that and fall back to Colab.
    """
    status = availability()
    if not status["ready"]:
        raise RuntimeError("HouseDiffusion engine unavailable: " + "; ".join(status["missing"]))

    import torch

    data_shape, model_kwargs, norm = g2m.build_model_kwargs(diagram, batch_size=num_samples)
    model, diffusion, device = _build_model_and_diffusion()

    th_kwargs = {k: torch.tensor(v, dtype=torch.float32, device=device)
                 for k, v in model_kwargs.items()}

    sample_fn = diffusion.p_sample_loop
    with torch.no_grad():
        sample = sample_fn(model, data_shape, clip_denoised=clip_denoised,
                           model_kwargs=th_kwargs, analog_bit=False)

    # HouseDiffusion's loop returns the whole trajectory [steps, B, 2, N];
    # the vanilla loop returns just [B, 2, N]. Handle both, take the last step.
    if sample.dim() == 4:
        final = sample[-1].permute(0, 2, 1)      # [B, N, 2]
    else:
        final = sample.permute(0, 2, 1)          # [B, N, 2]

    plot = (diagram.get("meta") or {}).get("plot")
    description = (diagram.get("meta") or {}).get("description", "")
    return out.polys_to_plan(final[sample_index], model_kwargs,
                             batch_index=sample_index, plot=plot,
                             description=description)
