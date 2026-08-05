ARG POSTGIS_BASE_IMAGE=imresamu/postgis:17-3.5
FROM ${POSTGIS_BASE_IMAGE}

# Install tools needed for initialization
# wget for downloading, unzip for extraction, postgresql-client for psql
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget unzip postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy initialization script
COPY geo_init.sh /usr/local/bin/geo_init.sh
RUN chmod +x /usr/local/bin/geo_init.sh
