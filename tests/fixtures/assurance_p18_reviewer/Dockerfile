# P1.8 provider-free Python Reviewer: deterministic acceptance checker.
# Pinned official Python base, stdlib only; this is NOT a GLM/LFL Agent image.
FROM python@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a
COPY --chmod=0555 reviewer.py /opt/lfl/reviewer.py
USER 65534:65534
WORKDIR /scratch
ENV PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["python3", "-I", "-B", "/opt/lfl/reviewer.py"]
