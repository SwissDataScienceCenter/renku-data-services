ARG RCLONE_IMAGE_REPOSITORY="ghcr.io/swissdatasciencecenter/rclone"
ARG RCLONE_IMAGE_TAG="sha-66b7f3e"
FROM ${RCLONE_IMAGE_REPOSITORY}:${RCLONE_IMAGE_TAG} AS rclone

FROM python:3.13-bookworm AS builder
ARG DEV_BUILD=false
ARG USER_UID=1000
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID renku && \
    DEBIAN_FRONTEND=noninteractive adduser --gid $USER_GID --uid $USER_UID renku
COPY --from=rclone --chown=root:root --chmod=755 /rclone /usr/bin/rclone
USER $USER_UID:$USER_GID
WORKDIR /app
RUN python3 -m pip install --user pipx && \
    python3 -m pipx ensurepath && \
    /home/renku/.local/bin/pipx install poetry && \
    /home/renku/.local/bin/pipx install virtualenv && \
    /home/renku/.local/bin/virtualenv env && \
    /home/renku/.local/bin/poetry self add poetry-multiproject-plugin && \
    /home/renku/.local/bin/poetry self add poetry-polylith-plugin && \
    /home/renku/.local/bin/poetry self add poetry-plugin-export

COPY --chown=$USER_UID:$USER_GID . .
RUN if $DEV_BUILD ; then \
    /home/renku/.local/bin/poetry export -o requirements.txt --with dev; \
  else \
    /home/renku/.local/bin/poetry export -o requirements.txt; \
  fi && \
  env/bin/pip install -r requirements.txt
RUN /home/renku/.local/bin/poetry -C projects/renku_data_service build-project -f wheel --custom-temp-path=/tmp
RUN env/bin/pip --no-cache-dir install projects/renku_data_service/dist/*.whl

FROM python:3.13-slim-bookworm
ARG USER_UID=1000
ARG USER_GID=$USER_UID
ENV prometheus_multiproc_dir=/prometheus
ENV PROMETHEUS_MULTIPROC_DIR=/prometheus
RUN mkdir /prometheus && chown $USER_UID:$USER_GID /prometheus
RUN apt-get update && apt-get install -y \
    tini vim-tiny procps curl && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid $USER_GID renku && \
    adduser --gid $USER_GID --uid $USER_UID renku
COPY --from=builder /usr/bin/rclone /usr/bin
USER $USER_UID:$USER_GID
WORKDIR /app
COPY --from=builder /app/env ./env
ENV DB_POOL_SIZE=10
ENTRYPOINT ["tini", "-g", "--", "env/bin/python", "-m", "renku_data_services.data_api.main", "--single-process"]
