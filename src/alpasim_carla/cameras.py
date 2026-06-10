"""Map AlpaSim CameraSpec intrinsics onto CARLA's pinhole camera.

CARLA's RGB camera is an ideal pinhole: a horizontal-FOV-in-degrees attribute
with the principal point fixed at the image center. v0.1 therefore supports
pinhole specs natively and treats everything else (ftheta, OpenCV fisheye,
distortion coefficients, windshield models, rolling shutter) as an explicit,
opt-in approximation:

  * default: the RPC fails with INVALID_ARGUMENT naming the offending field
    and the supported alternatives (no silent fallback, ever);
  * with --allow-pinhole-approximation: we derive an equivalent horizontal
    FOV (for ftheta, by evaluating the pixel-distance->angle polynomial at
    the image edge; the recorded hyperion 120fov camera evaluates to ~120
    deg, which is the sanity anchor for this path), render an ideal pinhole,
    and record a structured approximation note in the response path logs.

Resolution semantics: requests carry their own resolution_h/w which may
differ from the intrinsics' native resolution (observed in real traffic:
1080x1900 requested vs 1080x1920 native). We treat the request as a CENTER
CROP of the native sensor: the rendered FOV is the angle subtended by the
*requested* width on the native intrinsics. Documented in docs/CONTRACT.md;
flagged in OPEN_QUESTIONS.md because NuRec's exact semantics are unobservable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional


class UnsupportedCameraError(ValueError):
    """Raised when a CameraSpec cannot be honored without approximation.

    The message is written to be surfaced verbatim as a gRPC INVALID_ARGUMENT
    detail: it names the request field and the supported alternatives.
    """


@dataclass
class ResolvedCamera:
    """What the CARLA backend needs to configure a render."""

    width: int
    height: int
    hfov_deg: float
    is_approximate: bool
    approximation_notes: List[str] = field(default_factory=list)
    logical_id: str = ""


def _polyval(coeffs, x: float) -> float:
    """Evaluate sum(c[i] * x**i) - proto polynomials are lowest-order first."""
    acc = 0.0
    for i, c in enumerate(coeffs):
        acc += c * (x**i)
    return acc


def _ftheta_half_angle(param, half_width_px: float) -> float:
    if not param.pixeldist_to_angle_poly:
        raise UnsupportedCameraError(
            "camera_intrinsics.ftheta_param.pixeldist_to_angle_poly is empty; "
            "the pinhole approximation needs the pixeldistance->angle polynomial. "
            "Supported alternatives: opencv_pinhole_param, or an ftheta spec with "
            "pixeldist_to_angle_poly populated."
        )
    theta = _polyval(param.pixeldist_to_angle_poly, half_width_px)
    if param.max_angle:
        theta = min(theta, param.max_angle)
    if not (0.0 < theta < math.pi):
        raise UnsupportedCameraError(
            f"camera_intrinsics.ftheta_param polynomial evaluated to an invalid "
            f"half-angle {theta:.4f} rad at r={half_width_px:.1f}px."
        )
    return theta


def resolve_camera(
    spec,
    request_width: int,
    request_height: int,
    allow_approximation: bool,
    principal_point_tolerance: float = 0.02,
) -> ResolvedCamera:
    """CameraSpec proto + requested resolution -> CARLA pinhole settings.

    Raises UnsupportedCameraError unless the spec is an ideal centered
    pinhole or `allow_approximation` is set.
    """
    notes: List[str] = []
    kind = spec.WhichOneof("camera_param")
    native_w = spec.resolution_w or request_width
    native_h = spec.resolution_h or request_height
    half_req_w = request_width / 2.0

    if kind == "opencv_pinhole_param":
        p = spec.opencv_pinhole_param
        if p.focal_length_x <= 0:
            raise UnsupportedCameraError(
                "camera_intrinsics.opencv_pinhole_param.focal_length_x must be > 0."
            )
        has_distortion = any(p.radial_coeffs) or any(p.tangential_coeffs) or any(
            p.thin_prism_coeffs
        )
        if has_distortion:
            if not allow_approximation:
                raise UnsupportedCameraError(
                    "camera_intrinsics.opencv_pinhole_param has nonzero distortion "
                    "coefficients (radial_coeffs/tangential_coeffs/thin_prism_coeffs). "
                    "CARLA renders ideal pinhole only. Supported alternatives: send "
                    "zero distortion, or opt in with --allow-pinhole-approximation."
                )
            notes.append("ignored opencv_pinhole distortion coefficients")
        cx_offset = abs(p.principal_point_x - native_w / 2.0)
        if cx_offset > principal_point_tolerance * native_w:
            if not allow_approximation:
                raise UnsupportedCameraError(
                    f"camera_intrinsics.opencv_pinhole_param.principal_point_x="
                    f"{p.principal_point_x:.1f} is off-center by {cx_offset:.1f}px "
                    f"(> {principal_point_tolerance:.0%} of width {native_w}); CARLA's "
                    "principal point is fixed at the image center. Supported "
                    "alternatives: centered principal point, or "
                    "--allow-pinhole-approximation."
                )
            notes.append(
                f"principal point off-center by {cx_offset:.1f}px approximated as centered"
            )
        hfov = 2.0 * math.atan2(half_req_w, p.focal_length_x)

    elif kind == "ftheta_param":
        if not allow_approximation:
            raise UnsupportedCameraError(
                "camera_intrinsics.ftheta_param (polynomial fisheye) is not natively "
                "renderable by CARLA's pinhole camera. Supported alternatives: "
                "opencv_pinhole_param with zero distortion, or opt in with "
                "--allow-pinhole-approximation (renders an ideal pinhole whose "
                "horizontal FOV matches the ftheta edge angle)."
            )
        theta = _ftheta_half_angle(spec.ftheta_param, half_req_w)
        if theta >= math.radians(85.0):
            # tan() blows up approaching 90 deg; a pinhole cannot cover it.
            raise UnsupportedCameraError(
                f"camera_intrinsics.ftheta_param spans a half-angle of "
                f"{math.degrees(theta):.1f} deg at the requested width; a pinhole "
                "projection cannot approximate >=170 deg total FOV."
            )
        hfov = 2.0 * theta
        notes.append(
            f"ftheta approximated as pinhole, hfov={math.degrees(hfov):.2f} deg "
            f"from pixeldist_to_angle polynomial at r={half_req_w:.0f}px"
        )

    elif kind == "opencv_fisheye_param":
        p = spec.opencv_fisheye_param
        if not allow_approximation:
            raise UnsupportedCameraError(
                "camera_intrinsics.opencv_fisheye_param is not natively renderable "
                "by CARLA's pinhole camera. Supported alternatives: "
                "opencv_pinhole_param with zero distortion, or "
                "--allow-pinhole-approximation."
            )
        if p.focal_length_x <= 0:
            raise UnsupportedCameraError(
                "camera_intrinsics.opencv_fisheye_param.focal_length_x must be > 0."
            )
        theta = half_req_w / p.focal_length_x  # equidistant model: r = f * theta
        if p.max_angle:
            theta = min(theta, p.max_angle)
        if theta >= math.radians(85.0):
            raise UnsupportedCameraError(
                f"camera_intrinsics.opencv_fisheye_param spans a half-angle of "
                f"{math.degrees(theta):.1f} deg; a pinhole cannot approximate it."
            )
        hfov = 2.0 * theta
        notes.append(f"opencv_fisheye approximated as pinhole, hfov={math.degrees(hfov):.2f} deg")

    elif kind is None:
        raise UnsupportedCameraError(
            "camera_intrinsics.camera_param is unset. Supported: opencv_pinhole_param "
            "(native), ftheta_param / opencv_fisheye_param (with "
            "--allow-pinhole-approximation)."
        )
    else:
        raise UnsupportedCameraError(
            f"camera_intrinsics.{kind} is not supported. Supported: "
            "opencv_pinhole_param (native), ftheta_param / opencv_fisheye_param "
            "(with --allow-pinhole-approximation)."
        )

    if spec.WhichOneof("external_distortion") is not None:
        if not allow_approximation:
            raise UnsupportedCameraError(
                "camera_intrinsics.bivariate_windshield_model_param (external "
                "distortion) is not supported by the CARLA backend. Supported "
                "alternative: omit the windshield model, or opt in with "
                "--allow-pinhole-approximation (model ignored)."
            )
        notes.append("ignored bivariate windshield model")

    # ShutterType: GLOBAL(5) and UNKNOWN(0) render exactly; rolling shutters
    # are rendered as global - an approximation we only allow explicitly.
    if spec.shutter_type not in (0, 5):
        if not allow_approximation:
            raise UnsupportedCameraError(
                f"camera_intrinsics.shutter_type={spec.shutter_type} (rolling "
                "shutter) cannot be reproduced by CARLA's instantaneous capture. "
                "Supported alternatives: GLOBAL/UNKNOWN shutter, or "
                "--allow-pinhole-approximation (rendered as global shutter)."
            )
        notes.append("rolling shutter rendered as global shutter")

    return ResolvedCamera(
        width=request_width,
        height=request_height,
        hfov_deg=math.degrees(hfov),
        is_approximate=bool(notes),
        approximation_notes=notes,
        logical_id=spec.logical_id,
    )


def pinhole_hfov_deg(fx: float, width: int) -> float:
    """Convenience for tests/docs: ideal pinhole horizontal FOV in degrees."""
    return math.degrees(2.0 * math.atan2(width / 2.0, fx))
