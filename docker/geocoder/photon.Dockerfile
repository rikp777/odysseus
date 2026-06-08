FROM docker.io/eclipse-temurin:21-jre

ARG PHOTON_VERSION=1.1.0
ENV PHOTON_VERSION=${PHOTON_VERSION}

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl bzip2 tar \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL \
    -o /opt/photon.jar \
    "https://github.com/komoot/photon/releases/download/${PHOTON_VERSION}/photon-${PHOTON_VERSION}.jar"

COPY docker/geocoder/photon-entrypoint.sh /usr/local/bin/photon-entrypoint.sh

WORKDIR /photon
EXPOSE 2322

ENTRYPOINT ["sh", "/usr/local/bin/photon-entrypoint.sh"]
