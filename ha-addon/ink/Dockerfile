FROM python:3.12-slim

# git to pull the app; build deps only needed on 32-bit (armv7) where some
# wheels aren't prebuilt — harmless elsewhere.
RUN apt-get update \
  && apt-get install -y --no-install-recommends git libjpeg62-turbo zlib1g \
  && rm -rf /var/lib/apt/lists/*

# Pull the Ink code (pin to a tag/commit in production if you want stability).
RUN git clone --depth 1 https://github.com/tikel1/ink /app
WORKDIR /app
RUN pip install --no-cache-dir -r requirements.txt

COPY run.sh /run.sh
RUN sed -i 's/\r$//' /run.sh && chmod +x /run.sh   # guard against CRLF

CMD ["/run.sh"]
