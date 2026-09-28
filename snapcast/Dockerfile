FROM debian:trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends snapserver ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/lib/snapserver

COPY snapserver.conf /etc/snapserver.conf

EXPOSE 1704 1705 1780 4953

CMD ["snapserver", "--config", "/etc/snapserver.conf"]
