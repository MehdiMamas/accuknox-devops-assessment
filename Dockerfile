FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fortune-mod fortunes-min cowsay netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/usr/games:${PATH}"

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin wisecow

WORKDIR /app
COPY --chown=wisecow:wisecow wisecow.sh /app/wisecow.sh
RUN chmod 0755 /app/wisecow.sh && chown wisecow:wisecow /app

USER 10001
EXPOSE 4499
CMD ["./wisecow.sh"]
