FROM python:3.9.7-slim

ARG PDM_BUILD_SCM_VERSION
ENV PDM_BUILD_SCM_VERSION ${PDM_BUILD_SCM_VERSION}

RUN pip3 install -U pdm

# Install package
WORKDIR /code
COPY . .
RUN pdm install --check --prod --no-editable

ENV EXPORTER_CONFIG="/config/config.yml"
ENV EXPORTER_PORT=9000
ENV USE_MULTI_PORTS=

ENTRYPOINT downloader-exporter -c ${EXPORTER_CONFIG} -p ${EXPORTER_PORT} ${USE_MULTI_PORTS:+--multi}
