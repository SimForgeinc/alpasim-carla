"""CarlaBackend: pose-slaved rendering against a live CARLA server.

Render path for one render_rgb (all under the server's render lock):
  ensure scene loaded (map, synchronous mode, fixed weather)
  -> registry.sync(dynamic_objects)            # spawn / teleport / despawn
  -> resolve_camera(...)                       # explicit-or-approved pinhole
  -> sensor pool: place the pooled RGB sensor for (w, h, fov)
  -> world.tick() once
  -> take the frame with snapshot's frame id from the sensor queue
  -> encode (PNG/JPEG) per the request.

CARLA is configured in synchronous mode and this bridge must be the only
ticking client of that server (documented constraint). Sensors are pooled by
(width, height, fov): real alpamayo traffic uses two distinct keys (120 and
30 deg FOV at 1900x1080), so the pool stays tiny; pooled sensors keep
listening and stale frames are drained before each tick.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Dict, Optional, Tuple

import numpy as np
from PIL import Image

from alpasim_carla import frames
from alpasim_carla.cameras import resolve_camera
from alpasim_carla.registry import ActorRegistry
from alpasim_carla.scenes import SceneManifest
from alpasim_carla.server import RenderBackend, ServerOptions, encode_image

logger = logging.getLogger("alpasim_carla.world")


class _PooledSensor:
    def __init__(self, carla_module, world, width: int, height: int, fov_deg: float):
        self._carla = carla_module
        blueprint_library = world.get_blueprint_library()
        blueprint = blueprint_library.find("sensor.camera.rgb")
        blueprint.set_attribute("image_size_x", str(width))
        blueprint.set_attribute("image_size_y", str(height))
        blueprint.set_attribute("fov", str(fov_deg))
        blueprint.set_attribute("sensor_tick", "0.0")  # capture every tick
        # Spawn detached, high above the map; per-request set_transform moves it.
        spawn = carla_module.Transform(carla_module.Location(z=200.0))
        self.actor = world.spawn_actor(blueprint, spawn)
        self.width = width
        self.height = height
        self.queue: "queue.Queue" = queue.Queue()
        self.actor.listen(self.queue.put)

    def drain(self) -> None:
        try:
            while True:
                self.queue.get_nowait()
        except queue.Empty:
            pass

    def wait_for_frame(self, frame_id: int, timeout_s: float = 10.0):
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"No camera frame >= {frame_id} within {timeout_s}s "
                    f"({self.width}x{self.height})"
                )
            try:
                image = self.queue.get(timeout=remaining)
            except queue.Empty:
                continue
            if image.frame >= frame_id:
                return image

    def destroy(self) -> None:
        try:
            self.actor.stop()
        except RuntimeError:
            pass
        try:
            self.actor.destroy()
        except RuntimeError:
            pass


class CarlaBackend(RenderBackend):
    name = "carla"

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 2000,
        options: Optional[ServerOptions] = None,
        fixed_delta_seconds: float = 0.05,
        client_timeout_s: float = 60.0,
    ) -> None:
        import carla  # lazy: keeps the simulator-free suite carla-free

        self._carla = carla
        self._options = options or ServerOptions()
        self._fixed_delta = fixed_delta_seconds
        self._client = carla.Client(host, port)
        self._client.set_timeout(client_timeout_s)
        self._world = None
        self._scene_id: Optional[str] = None
        self.registry: Optional[ActorRegistry] = None
        self._sensors: Dict[Tuple[int, int, int], _PooledSensor] = {}
        self._lock = threading.Lock()
        version = self._client.get_server_version()
        logger.info("Connected to CARLA %s at %s:%d", version, host, port)
        if "0.9.16" not in version:
            logger.warning(
                "CARLA server version %s != pinned 0.9.16; proceeding, but the "
                "pin is what this bridge is tested against",
                version,
            )

    # -- scene lifecycle ------------------------------------------------------

    def _ensure_scene(self, scene: SceneManifest) -> None:
        if self._scene_id == scene.scene_id and self._world is not None:
            return
        logger.info("Loading scene %s -> map %s", scene.scene_id, scene.carla_map)
        for sensor in self._sensors.values():
            sensor.destroy()
        self._sensors.clear()
        if self.registry is not None:
            self.registry.clear()

        world = self._client.get_world()
        current = world.get_map().name  # e.g. "Carla/Maps/Town10HD_Opt"
        if not current.endswith(scene.carla_map):
            world = self._client.load_world(scene.carla_map)
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = self._fixed_delta
        settings.no_rendering_mode = False
        world.apply_settings(settings)
        # Deterministic environment: fixed weather, no dynamic time-of-day.
        world.set_weather(self._carla.WeatherParameters.ClearNoon)
        world.tick()
        self._world = world
        self._scene_id = scene.scene_id
        self.registry = ActorRegistry(self._carla, world, scene)

    def _sensor_for(self, width: int, height: int, fov_deg: float) -> _PooledSensor:
        key = (width, height, int(round(fov_deg * 100)))
        sensor = self._sensors.get(key)
        if sensor is None:
            sensor = _PooledSensor(self._carla, self._world, width, height, fov_deg)
            self._sensors[key] = sensor
            logger.info(
                "Created pooled RGB sensor %dx%d fov=%.2f (pool size %d)",
                width, height, fov_deg, len(self._sensors),
            )
        return sensor

    # -- RenderBackend --------------------------------------------------------

    def render_rgb(self, request, scene: SceneManifest) -> bytes:
        with self._lock:
            self._ensure_scene(scene)
            resolved = resolve_camera(
                request.camera_intrinsics,
                request.resolution_w,
                request.resolution_h,
                self._options.allow_pinhole_approximation,
            )
            for note in resolved.approximation_notes:
                logger.info(
                    "approximation scene=%s camera=%s: %s",
                    scene.scene_id, resolved.logical_id or "?", note,
                )

            self.registry.sync(request.dynamic_objects)

            sensor_pose = frames.grpc_pose_to_tuple(request.sensor_pose.start_pose)
            anchored = frames.apply_anchor(
                scene.anchor_translation, scene.anchor_yaw_deg, sensor_pose
            )
            location, rotator = frames.carla_transform_tuple(*anchored, axes="optical")
            sensor = self._sensor_for(
                resolved.width, resolved.height, resolved.hfov_deg
            )
            sensor.actor.set_transform(
                self._carla.Transform(
                    self._carla.Location(*location),
                    self._carla.Rotation(
                        pitch=rotator[0], yaw=rotator[1], roll=rotator[2]
                    ),
                )
            )
            sensor.drain()
            frame_id = self._world.tick()
            image = sensor.wait_for_frame(frame_id)

            # carla.Image raw_data is BGRA uint8.
            array = np.frombuffer(image.raw_data, dtype=np.uint8).reshape(
                (image.height, image.width, 4)
            )
            rgb = array[:, :, [2, 1, 0]]
            pil_image = Image.fromarray(rgb, "RGB")
            return encode_image(pil_image, request.image_format, request.image_quality)

    def render_lidar(self, request, scene: SceneManifest):
        raise NotImplementedError(
            "render_lidar is out of scope for alpasim-carla v0.1 (roadmap); the "
            "CARLA backend renders RGB only."
        )

    def close(self) -> None:
        with self._lock:
            for sensor in self._sensors.values():
                sensor.destroy()
            self._sensors.clear()
            if self.registry is not None:
                self.registry.clear()
            if self._world is not None:
                settings = self._world.get_settings()
                settings.synchronous_mode = False
                settings.fixed_delta_seconds = None
                self._world.apply_settings(settings)
