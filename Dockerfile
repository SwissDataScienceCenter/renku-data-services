FROM python:3.11-bullseye as builder
RUN groupadd --gid 1000 renku && \
    adduser --gid 1000 --uid 1000 renku
USER 1000:1000
WORKDIR /app
COPY . .
RUN python3 -m pip install --user pipx && \ 
    python3 -m pipx ensurepath && \
    /home/renku/.local/bin/pipx install poetry && \
    /home/renku/.local/bin/pipx install virtualenv && \
    /home/renku/.local/bin/poetry build --format wheel && \
    /home/renku/.local/bin/virtualenv env && \
    env/bin/pip install dist/*whl

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
CMD ["env/bin/python", "-m", "renku_crac.main", "--fast"]
