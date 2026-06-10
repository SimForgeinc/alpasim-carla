"""The SensorsimService gRPC server.

Implements all 8 RPCs of nre.grpc.protos.sensorsim.SensorsimService against a
pluggable RenderBackend:

  * SyntheticBackend - no CARLA required; deterministic placeholder frames.
    Used by gate G0 (contract replay) and for smoke-testing wiring.
  * CarlaBackend (alpasim_carla.world) - the real thing.

Error policy (the library's spine - see docs/CONTRACT.md):
  * unknown scene_id            -> NOT_FOUND, message lists available scenes
  * unsupported camera model    -> INVALID_ARGUMENT naming the field and the
                                   supported alternatives (approximations are
                                   explicit opt-in via --allow-pinhole-approximation)
  * render_lidar on CARLA       -> UNIMPLEMENTED (v0.1 scope fence; the
                                   synthetic backend answers with an empty
                                   point cloud so all 8 RPCs are exercisable)
  * ego-mask requests           -> we publish no ego masks (empty
                                   get_available_ego_masks), so a request with
                                   insert_ego_mask=true is INVALID_ARGUMENT.
"""

from __future__ import annotations

import io
import logging
import threading
from concurrent import futures
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import grpc
from PIL import Image

from alpasim_carla import GRPC_API_VERSION, __version__
from alpasim_carla._proto.alpasim_grpc.v0 import (
    common_pb2,
    sensorsim_pb2,
    sensorsim_pb2_grpc,
)
from alpasim_carla.scenes import SceneManifest, UnknownSceneError

logger = logging.getLogger("alpasim_carla.server")

_FORMAT_TO_PIL = {
    sensorsim_pb2.ImageFormat.PNG: "PNG",
    sensorsim_pb2.ImageFormat.JPEG: "JPEG",
}


def encode_image(image: Image.Image, image_format: int, image_quality: float) -> bytes:
    """Encode a PIL image per the request's ImageFormat/image_quality."""
    if image_format not in _FORMAT_TO_PIL:
        name = sensorsim_pb2.ImageFormat.Name(image_format)
        raise ValueError(
            f"image_format={name} is not supported; AlpaSim currently uses PNG and "
            f"JPEG (proto comment at pinned commit) and so does this bridge."
        )
    buf = io.BytesIO()
    if _FORMAT_TO_PIL[image_format] == "JPEG":
        quality = int(image_quality) if image_quality else 95
        image.convert("RGB").save(buf, "JPEG", quality=max(1, min(100, quality)))
    else:
        image.save(buf, "PNG")
    return buf.getvalue()


class RenderBackend:
    """Interface the servicer renders through."""

    name = "abstract"

    def render_rgb(
        self, request: sensorsim_pb2.RGBRenderRequest, scene: SceneManifest
    ) -> bytes:
        raise NotImplementedError

    def render_lidar(
        self, request: sensorsim_pb2.LidarRenderRequest, scene: SceneManifest
    ) -> sensorsim_pb2.LidarRenderReturn:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SyntheticBackend(RenderBackend):
    """Deterministic placeholder frames; zero simulator dependencies.

    Frames are a flat mid-gray; identical (w, h, format, quality) requests
    reuse a cached encoding, which keeps replaying hundreds of recorded
    requests fast.
    """

    name = "synthetic"

    def __init__(self) -> None:
        self._cache: Dict[Tuple[int, int, int, int], bytes] = {}

    def render_rgb(
        self, request: sensorsim_pb2.RGBRenderRequest, scene: SceneManifest
    ) -> bytes:
        key = (
            request.resolution_w,
            request.resolution_h,
            request.image_format,
            int(request.image_quality or 0),
        )
        cached = self._cache.get(key)
        if cached is None:
            image = Image.new(
                "RGB", (request.resolution_w, request.resolution_h), (118, 118, 118)
            )
            cached = encode_image(image, request.image_format, request.image_quality)
            self._cache[key] = cached
        return cached

    def render_lidar(
        self, request: sensorsim_pb2.LidarRenderRequest, scene: SceneManifest
    ) -> sensorsim_pb2.LidarRenderReturn:
        return sensorsim_pb2.LidarRenderReturn(num_points=0)


@dataclass
class ServerOptions:
    allow_pinhole_approximation: bool = False
    git_hash: str = "unknown"
    extra_scene_wildcard: bool = False  # advertise "*" in addition to manifests


class SensorsimServicer(sensorsim_pb2_grpc.SensorsimServiceServicer):
    def __init__(
        self,
        scenes: Dict[str, SceneManifest],
        backend: RenderBackend,
        options: Optional[ServerOptions] = None,
    ) -> None:
        self._scenes = scenes
        self._backend = backend
        self._options = options or ServerOptions()
        # One CARLA world, one render at a time; synthetic renders are cheap
        # enough that serializing them too costs nothing.
        self._render_lock = threading.Lock()

    # -- helpers ------------------------------------------------------------

    def _resolve_scene(self, scene_id: str, context: grpc.ServicerContext) -> SceneManifest:
        scene = self._scenes.get(scene_id)
        if scene is None:
            err = UnknownSceneError(scene_id, list(self._scenes.keys()))
            context.abort(grpc.StatusCode.NOT_FOUND, str(err))
        return scene

    def _render_rgb_bytes(
        self, request: sensorsim_pb2.RGBRenderRequest, context: grpc.ServicerContext
    ) -> bytes:
        scene = self._resolve_scene(request.scene_id, context)
        if request.insert_ego_mask:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "insert_ego_mask=true but this bridge publishes no ego masks "
                "(get_available_ego_masks returns an empty list in v0.1). "
                "Set insert_ego_mask=false / omit ego_mask_id.",
            )
        if request.resolution_w <= 0 or request.resolution_h <= 0:
            context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"resolution_w/resolution_h must be positive, got "
                f"{request.resolution_w}x{request.resolution_h}.",
            )
        try:
            with self._render_lock:
                return self._backend.render_rgb(request, scene)
        except ValueError as exc:  # UnsupportedCameraError et al.
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        except NotImplementedError as exc:
            context.abort(grpc.StatusCode.UNIMPLEMENTED, str(exc))

    # -- RPCs ----------------------------------------------------------------

    def render_rgb(self, request, context):
        return sensorsim_pb2.RGBRenderReturn(
            image_bytes=self._render_rgb_bytes(request, context)
        )

    def render_aggregated(self, request, context):
        # Faithful to the generated stubs at the pinned commit:
        # AggregatedRenderReturn.rgb_returns is a list of RGBRenderReturn
        # (image_bytes only). The runtime does not exercise this RPC at
        # a1f05bb (use_aggregated_render defaults to False).
        ret = sensorsim_pb2.AggregatedRenderReturn()
        for rgb_request in request.rgb_requests:
            ret.rgb_returns.add(image_bytes=self._render_rgb_bytes(rgb_request, context))
        for lidar_request in request.lidar_requests:
            ret.lidar_returns.append(self._render_lidar(lidar_request, context))
        return ret

    def _render_lidar(self, request, context):
        scene = self._resolve_scene(request.scene_id, context)
        try:
            with self._render_lock:
                return self._backend.render_lidar(request, scene)
        except NotImplementedError:
            context.abort(
                grpc.StatusCode.UNIMPLEMENTED,
                "render_lidar is out of scope for alpasim-carla v0.1 (roadmap). "
                "The CARLA backend renders RGB only.",
            )

    def render_lidar(self, request, context):
        return self._render_lidar(request, context)

    def get_version(self, request, context):
        return common_pb2.VersionId(
            version_id=f"alpasim-carla {__version__} ({self._backend.name})",
            git_hash=self._options.git_hash,
            grpc_api_version=common_pb2.VersionId.APIVersion(
                major=GRPC_API_VERSION[0],
                minor=GRPC_API_VERSION[1],
                patch=GRPC_API_VERSION[2],
            ),
        )

    def get_available_scenes(self, request, context):
        ret = common_pb2.AvailableScenesReturn()
        ret.scene_ids.extend(sorted(self._scenes.keys()))
        if self._options.extra_scene_wildcard:
            ret.scene_ids.append("*")
        return ret

    def get_available_cameras(self, request, context):
        scene = self._resolve_scene(request.scene_id, context)
        return scene.available_cameras_return()

    def get_available_trajectories(self, request, context):
        # Never called by the runtime at the pinned commit; NVIDIA's own
        # replay servicer answers with an empty return, and so do we.
        self._resolve_scene(request.scene_id, context)
        return sensorsim_pb2.AvailableTrajectoriesReturn()

    def get_available_ego_masks(self, request, context):
        # v0.1 publishes no ego masks: the runtime then resolves
        # ego_mask_id=None and sends insert_ego_mask=false (verified in
        # alpasim_runtime.services.sensorsim_service.determine_ego_mask_id).
        return sensorsim_pb2.AvailableEgoMasksReturn()


def build_server(
    scenes: Dict[str, SceneManifest],
    backend: RenderBackend,
    options: Optional[ServerOptions] = None,
    port: int = 50051,
    host: str = "0.0.0.0",
    max_workers: int = 8,
) -> Tuple[grpc.Server, int]:
    """Create (not start) the gRPC server; returns (server, bound_port)."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    sensorsim_pb2_grpc.add_SensorsimServiceServicer_to_server(
        SensorsimServicer(scenes, backend, options), server
    )
    bound_port = server.add_insecure_port(f"{host}:{port}")
    if bound_port == 0:
        raise RuntimeError(f"Could not bind gRPC server to {host}:{port}")
    return server, bound_port
