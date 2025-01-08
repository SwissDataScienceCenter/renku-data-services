FROM python:3.12-bookworm as builder
ARG DEV_BUILD=false
ARG USER_UID=1000
ARG RCLONE_VERSION=v1.65.2
ARG RCLONE_ARCH=amd64
ARG RCLONE_OS=linux
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID renku && \
    DEBIAN_FRONTEND=noninteractive adduser --gid $USER_GID --uid $USER_UID renku
RUN cd /tmp \
    && wget -q https://downloads.rclone.org/${RCLONE_VERSION}/rclone-${RCLONE_VERSION}-${RCLONE_OS}-${RCLONE_ARCH}.zip \
    && unzip /tmp/rclone-${RCLONE_VERSION}-${RCLONE_OS}-${RCLONE_ARCH}.zip \
    && mv /tmp/rclone-${RCLONE_VERSION}-${RCLONE_OS}-${RCLONE_ARCH}/rclone /usr/bin \
    && chmod 755 /usr/bin/rclone \
    && chown root:root /usr/bin/rclone \
    && rm -r /tmp/rclone*
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

FROM python:3.12-slim-bookworm
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
ENTRYPOINT ["tini", "-g", "--", "env/bin/python", "-m", "renku_data_services.data_api.main"]
