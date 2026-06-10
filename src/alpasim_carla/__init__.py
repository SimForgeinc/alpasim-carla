"""alpasim-carla: a CARLA-backed renderer (SensorsimService) for NVIDIA AlpaSim."""

__version__ = "0.1.0"

# Pinned AlpaSim contract identity. The runtime's validation collects
# grpc_api_version from every service and asserts consistency per service;
# we echo the version of the alpasim_grpc distribution our protos were
# vendored from (AlpaSim commit a1f05bb628f3, alpasim_grpc 0.54.0).
ALPASIM_COMMIT = "a1f05bb628f3d1d19d79d44188e836e9108f98c6"
GRPC_API_VERSION = (0, 54, 0)
