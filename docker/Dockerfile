# alpasim-carla bridge image (the renderer process only - bring your own
# CARLA server; see docker/README.md for a compose example).
#
# The CARLA client wheel is copied out of the CARLA image rather than fetched
# from PyPI. There is no `carla==0.10.0` on PyPI at all: the 0.10 client ships
# only as a .whl inside the release package, and the copy inside the server
# image is the one guaranteed to match that server. For stock 0.9.16 twins
# PyPI does work - build with CARLA_IMAGE="" to use the [carla] extra instead.
#
#   docker build -f docker/Dockerfile \
#       --build-arg CARLA_IMAGE=ghcr.io/abhisheksimforgeai/carla-rfs-munich-belmont:0.10.0 \
#       --build-arg PYTHON_VERSION=3.12 \
#       -t alpasim-carla:0.10 .
#
# PYTHON_VERSION must match a cp<ver> wheel present in the CARLA image.
# CARLA 0.10 ships cp38 through cp312; 0.9.16 ships cp310 through cp312. The
# wheel-selection step below fails with the available filenames listed rather
# than a bare "no matching distribution".

ARG PYTHON_VERSION=3.12
ARG CARLA_IMAGE=ghcr.io/abhisheksimforgeai/carla-rfs-munich-belmont:0.10.0

# Stage 1: the CARLA server image, used only as a source of the client wheel.
FROM ${CARLA_IMAGE} AS carla-dist

# Stage 2: the bridge.
FROM python:${PYTHON_VERSION}-slim
ARG PYTHON_VERSION

# The wheel lives at PythonAPI/dist/ on 0.10 and PythonAPI/carla/dist/ on
# 0.9.x. Copy both candidate trees; at least one exists in any CARLA image.
COPY --from=carla-dist /home/carla/PythonAPI/ /tmp/carla-pythonapi/

RUN set -eu; \
    tag="cp$(echo "${PYTHON_VERSION}" | tr -d '.')"; \
    wheel="$(find /tmp/carla-pythonapi -name "carla-*-${tag}-*.whl" | head -n1)"; \
    if [ -z "${wheel}" ]; then \
        echo "No CARLA wheel for ${tag} (Python ${PYTHON_VERSION}) in this image." >&2; \
        echo "Wheels present:" >&2; \
        find /tmp/carla-pythonapi -name 'carla-*.whl' -printf '  %f\n' >&2 || true; \
        echo "Rebuild with --build-arg PYTHON_VERSION=<one of the above>." >&2; \
        exit 1; \
    fi; \
    echo "Installing ${wheel}"; \
    pip install --no-cache-dir "${wheel}"; \
    rm -rf /tmp/carla-pythonapi

WORKDIR /opt/alpasim-carla
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY scenes ./scenes
COPY tools ./tools

# Note: plain "." and NOT ".[carla]" - the client is already installed above
# from the server image, and the extra would pull the 0.9.16 PyPI wheel over
# it.
RUN pip install --no-cache-dir .

# Fail the build rather than the first render if the wheel does not import.
RUN python -c "import carla; print('carla client', carla.__file__)"

# SensorsimService port
EXPOSE 50051

ENTRYPOINT ["alpasim-carla"]
CMD ["serve", "--port", "50051", "--scenes-dir", "scenes/examples", \
     "--carla-host", "host.docker.internal", "--carla-port", "2000"]
