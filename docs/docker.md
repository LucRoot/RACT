# RACT Docker Quickstart

Run RACT inside a container so your host environment stays clean.

## Dockerfile example

Create a `Dockerfile` in your project root:

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . /app
RUN pip install -e .

ENTRYPOINT ["python", "-m", "rootact.cli"]
```

## Building the image

Build the image from the directory containing the Dockerfile:

```bash
docker build -t ract:latest .
```

## Running a plan

Mount your project directory and run RACT against it:

```bash
docker run --rm -v "$(pwd):/workspace" -w /workspace ract:latest \
  --config /workspace/rootact.yaml "add tests"
```

## Mounting the project directory

Always mount the project as a volume so RACT can read and write files on the host. Without the volume, changes made inside the container are lost when the container exits.

```bash
docker run --rm -v "$(pwd):/workspace" -w /workspace ract:latest --version
```
