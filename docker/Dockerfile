# alpasim-carla bridge image (the renderer process only - bring your own
# CARLA server; see docker/README.md for a compose example).
FROM python:3.10-slim

WORKDIR /opt/alpasim-carla
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY scenes ./scenes

RUN pip install --no-cache-dir ".[carla]"

# SensorsimService port
EXPOSE 50051

ENTRYPOINT ["alpasim-carla"]
CMD ["serve", "--port", "50051", "--scenes-dir", "scenes/examples", \
     "--carla-host", "host.docker.internal", "--carla-port", "2000"]
