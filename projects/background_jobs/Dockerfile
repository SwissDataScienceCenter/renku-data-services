FROM python:3.12-bookworm as builder
ARG DEV_BUILD=false
ARG USER_UID=1000
ARG USER_GID=$USER_UID

RUN groupadd --gid $USER_GID renku && \
    DEBIAN_FRONTEND=noninteractive adduser --gid $USER_GID --uid $USER_UID renku
USER $USER_UID:$USER_GID
WORKDIR /app
RUN python3 -m pip install --user pipx && \
    python3 -m pipx ensurepath && \
    /home/renku/.local/bin/pipx install poetry && \
    /home/renku/.local/bin/pipx install virtualenv && \
    /home/renku/.local/bin/virtualenv env && \
    /home/renku/.local/bin/poetry self add poetry-multiproject-plugin && \
    /home/renku/.local/bin/poetry self add poetry-polylith-plugin
COPY --chown=$USER_UID:$USER_GID . .
RUN if $DEV_BUILD ; then \
    /home/renku/.local/bin/poetry export -o requirements.txt --with dev; \
  else \
    /home/renku/.local/bin/poetry export -o requirements.txt; \
  fi && \
  env/bin/pip install -r requirements.txt
RUN /home/renku/.local/bin/poetry build-project -f wheel -C projects/background_jobs
RUN env/bin/pip --no-cache-dir install projects/background_jobs/dist/*.whl

FROM python:3.12-slim-bookworm
ARG USER_UID=1000
ARG USER_GID=$USER_UID
RUN apt-get update && apt-get install -y \
    tini vim-tiny procps curl && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid $USER_GID renku && \
    adduser --gid $USER_GID --uid $USER_UID renku
USER $USER_UID:$USER_GID
WORKDIR /app
COPY --from=builder /app/env ./env
ENTRYPOINT ["tini", "-g", "--", "env/bin/python", "-m", "renku_data_services.background_jobs.main"]
