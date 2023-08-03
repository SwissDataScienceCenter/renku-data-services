FROM python:3.11-bullseye as builder
ARG DEV_BUILD=false

RUN groupadd --gid 1000 renku && \
    adduser --gid 1000 --uid 1000 renku
USER 1000:1000
WORKDIR /app
RUN python3 -m pip install --user pipx && \
    python3 -m pipx ensurepath && \
    /home/renku/.local/bin/pipx install poetry && \
    /home/renku/.local/bin/pipx install virtualenv && \
    /home/renku/.local/bin/virtualenv env && \
    /home/renku/.local/bin/poetry self add poetry-multiproject-plugin && \
    /home/renku/.local/bin/poetry self add poetry-polylith-plugin
COPY --chown=1000:1000 . .
RUN if $DEV_BUILD ; then \
    /home/renku/.local/bin/poetry export -o requirements.txt --with dev; \
    env/bin/pip install -r requirements.txt; \
  fi
RUN /home/renku/.local/bin/poetry build-project -f wheel -C projects/renku_crc
RUN env/bin/pip --no-cache-dir install projects/renku_crc/dist/*.whl

FROM python:3.11-slim-bullseye
RUN apt-get update && apt-get install -y \
    tini && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 1000 renku && \
    adduser --gid 1000 --uid 1000 renku
USER 1000:1000
WORKDIR /app
COPY --from=builder /app/env ./env
ENTRYPOINT ["tini", "-g", "--"]
CMD ["env/bin/python", "-m", "renku_data_services.crc_api.main", "--fast"]
