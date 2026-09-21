FROM python:3.12-alpine
RUN apk add --no-cache openssl ca-certificates
WORKDIR /tools
COPY certificates.py /tools/certificates.py
ENTRYPOINT ["python", "/tools/certificates.py"]
