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
    /home/renku/.local/bin/virtualenv env
COPY poetry.lock pyproject.toml ./
RUN if $DEV_BUILD ; then \
    /home/renku/.local/bin/poetry export -o requirements.txt --with dev; \
  else \
    /home/renku/.local/bin/poetry export -o requirements.txt; \
  fi
RUN env/bin/pip install -r requirements.txt
COPY . .
RUN env/bin/pip install .

FROM python:3.11-slim-bullseye
RUN apt-get update && apt-get install -y \
    tini && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 1000 renku && \
    adduser --gid 1000 --uid 1000 renku
USER 1000:1000
WORKDIR /app
COPY --from=builder /app/env ./env
RUN mkdir -p /tmp/prometheus_multiproc_dir
ENTRYPOINT ["tini", "-g", "--"]
CMD ["env/bin/python", "-m", "renku_crc.main", "--fast"]
