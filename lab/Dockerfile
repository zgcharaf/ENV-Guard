# Optional: reproduce the same fixture suite in a clean Linux image.
# No Docker daemon or privileged runner is required for the Python-only lab.
FROM python:3.12-bookworm
WORKDIR /workspace
COPY . /workspace/
ENV PYTHONPATH=/workspace/src
RUN python -m pip install --no-cache-dir -e . && python -m unittest discover -s tests -v
CMD ["python", "lab/run_lab.py", "--out", "/workspace/lab-results"]
