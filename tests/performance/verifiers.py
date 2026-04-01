"""
Verification functions — check correctness after an agent run.

Three methods:
  1. ObjectCheck   — does the expected object exist in list_objects()?
  2. GeometryCheck — does a FreeCAD script return the expected value?
  3. Screenshot    — SSIM comparison against a saved baseline image
"""

import base64
import os
from pathlib import Path

from tests.performance.scenarios import GeometryCheck, ObjectCheck, TestCase

BASELINES_DIR = Path(__file__).parent.parent / "baselines"
BASELINES_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Object existence
# ---------------------------------------------------------------------------

def verify_object(check: ObjectCheck, objects: list[dict]) -> tuple[bool, str]:
    """Return (passed, detail)."""
    for obj in objects:
        name_ok = check.name_contains.lower() in obj["name"].lower()
        type_ok = (not check.type_contains) or (check.type_contains.lower() in obj["type"].lower())
        if name_ok and type_ok:
            return True, f"Found {obj['name']} [{obj['type']}]"
    return False, f"No object matching name='{check.name_contains}' type='{check.type_contains}'"


# ---------------------------------------------------------------------------
# Geometry properties
# ---------------------------------------------------------------------------

def verify_geometry(check: GeometryCheck, execute_fn) -> tuple[bool, str]:
    """Run a FreeCAD script and compare the printed output to expected."""
    try:
        raw = execute_fn(check.script).strip()
        if raw == "NOT_FOUND":
            return False, "Object not found in document (NOT_FOUND)"
        if isinstance(check.expected, str):
            passed = raw == check.expected
            return passed, f"got={raw!r} expected={check.expected!r}"
        else:
            value = float(raw)
            passed = abs(value - check.expected) <= check.tolerance
            return passed, f"got={value} expected={check.expected} tol={check.tolerance}"
    except Exception as e:
        return False, f"Script error: {e}"


# ---------------------------------------------------------------------------
# Screenshot / visual
# ---------------------------------------------------------------------------

def verify_screenshot(test_id: str, png_b64: str | None) -> tuple[bool, float | None, str]:
    """
    Compare screenshot against baseline using SSIM.
    Returns (passed, ssim_score, detail).
    If no baseline exists, saves this screenshot as the baseline and returns (True, 1.0, "baseline saved").
    """
    if not png_b64:
        return False, None, "No screenshot available"

    baseline_path = BASELINES_DIR / f"{test_id}.png"
    png_bytes = base64.b64decode(png_b64)

    if not baseline_path.exists():
        baseline_path.write_bytes(png_bytes)
        return True, 1.0, "Baseline saved (first run)"

    try:
        import numpy as np
        from skimage.metrics import structural_similarity as ssim
        from PIL import Image
        import io

        def load(data: bytes):
            img = Image.open(io.BytesIO(data)).convert("RGB")
            return np.array(img)

        baseline = load(baseline_path.read_bytes())
        current  = load(png_bytes)

        # Resize current to match baseline if dimensions differ
        if baseline.shape != current.shape:
            current_img = Image.open(io.BytesIO(png_bytes)).convert("RGB").resize(
                (baseline.shape[1], baseline.shape[0])
            )
            current = np.array(current_img)

        score = float(ssim(baseline, current, channel_axis=2, data_range=255))
        passed = score >= 0.80
        return passed, round(score, 4), f"SSIM={score:.4f} (threshold=0.80)"

    except ImportError:
        # scikit-image / Pillow not installed — skip visual check
        return True, None, "Skipped (scikit-image not installed)"
    except Exception as e:
        return False, None, f"SSIM error: {e}"


# ---------------------------------------------------------------------------
# Run all verifications for a test case
# ---------------------------------------------------------------------------

def run_verifications(
    case: TestCase,
    objects: list[dict],
    execute_fn,
    screenshot_b64: str | None,
) -> dict:
    """
    Returns a dict: {check_name: {"passed": bool, "detail": str, ...}}
    """
    results = {}

    for i, check in enumerate(case.verifications):
        key = f"{type(check).__name__}_{i}"
        if isinstance(check, ObjectCheck):
            passed, detail = verify_object(check, objects)
            results[key] = {"type": "object", "passed": passed, "detail": detail,
                            "check": check.name_contains}
        elif isinstance(check, GeometryCheck):
            passed, detail = verify_geometry(check, execute_fn)
            results[key] = {"type": "geometry", "passed": passed, "detail": detail,
                            "expected": check.expected}

    # Screenshot check — skip for tests with no explicit verifications (e.g. ER tests)
    # since the agent intentionally produces no geometry on those.
    if case.verifications:
        vis_passed, ssim_score, vis_detail = verify_screenshot(case.id, screenshot_b64)
        results["screenshot"] = {
            "type": "visual",
            "passed": vis_passed,
            "detail": vis_detail,
            "ssim": ssim_score,
        }

    return results
