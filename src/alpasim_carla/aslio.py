"""Reader for AlpaSim .asl rollout logs.

Format (from alpasim_utils.logs at the pinned commit): a flat stream of
[4-byte big-endian length][serialized logging.LogEntry] records. LogEntry is
a oneof envelope; the sensorsim-relevant entries are:

  render_request              - every RGBRenderRequest the runtime sent
                                (render RESPONSES are not logged)
  available_cameras_request/-return, available_ego_masks_request/-return
  rollout_metadata            - scene id, actor AABBs + labels, rig info
  driver_camera_image         - the images the driver actually received;
                                usable as ground-truth responses, matched by
                                (camera logical_id, frame_start_us)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

from alpasim_carla._proto.alpasim_grpc.v0 import logging_pb2, sensorsim_pb2


def read_log_entries(path: str) -> Iterator[logging_pb2.LogEntry]:
    with open(path, "rb") as f:
        while True:
            prefix = f.read(4)
            if len(prefix) < 4:
                return
            (size,) = struct.unpack(">L", prefix)
            payload = f.read(size)
            if len(payload) != size:
                raise IOError(
                    f"Malformed .asl file {path}: expected {size} bytes, got {len(payload)}"
                )
            yield logging_pb2.LogEntry.FromString(payload)


@dataclass
class SensorsimLog:
    """The sensorsim-facing slice of one rollout."""

    path: str
    rollout_metadata: Optional[logging_pb2.RolloutMetadata] = None
    render_requests: List[sensorsim_pb2.RGBRenderRequest] = field(default_factory=list)
    available_cameras_request: Optional[sensorsim_pb2.AvailableCamerasRequest] = None
    available_cameras_return: Optional[sensorsim_pb2.AvailableCamerasReturn] = None
    available_ego_masks_return: Optional[sensorsim_pb2.AvailableEgoMasksReturn] = None
    aggregated_render_requests: List[sensorsim_pb2.AggregatedRenderRequest] = field(
        default_factory=list
    )
    entry_counts: Dict[str, int] = field(default_factory=dict)
    # (camera logical_id, frame_start_us) -> recorded image bytes
    driver_images: Dict[Tuple[str, int], bytes] = field(default_factory=dict)

    @property
    def scene_id(self) -> str:
        if self.rollout_metadata is None:
            raise ValueError(f"{self.path} has no rollout_metadata entry")
        return self.rollout_metadata.session_metadata.scene_id


def read_sensorsim_log(path: str, keep_driver_images: bool = False) -> SensorsimLog:
    log = SensorsimLog(path=path)
    for entry in read_log_entries(path):
        kind = entry.WhichOneof("log_entry")
        log.entry_counts[kind] = log.entry_counts.get(kind, 0) + 1
        if kind == "rollout_metadata":
            log.rollout_metadata = entry.rollout_metadata
        elif kind == "render_request":
            req = sensorsim_pb2.RGBRenderRequest()
            req.CopyFrom(entry.render_request)
            log.render_requests.append(req)
        elif kind == "available_cameras_request":
            req = sensorsim_pb2.AvailableCamerasRequest()
            req.CopyFrom(entry.available_cameras_request)
            log.available_cameras_request = req
        elif kind == "available_cameras_return":
            ret = sensorsim_pb2.AvailableCamerasReturn()
            ret.CopyFrom(entry.available_cameras_return)
            log.available_cameras_return = ret
        elif kind == "available_ego_masks_return":
            ret = sensorsim_pb2.AvailableEgoMasksReturn()
            ret.CopyFrom(entry.available_ego_masks_return)
            log.available_ego_masks_return = ret
        elif kind == "aggregated_render_request":
            agg = sensorsim_pb2.AggregatedRenderRequest()
            agg.CopyFrom(entry.aggregated_render_request)
            log.aggregated_render_requests.append(agg)
        elif kind == "driver_camera_image" and keep_driver_images:
            image = entry.driver_camera_image.camera_image
            log.driver_images[(image.logical_id, image.frame_start_us)] = bytes(
                image.image_bytes
            )
    return log
