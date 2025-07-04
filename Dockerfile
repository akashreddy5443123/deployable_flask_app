FROM python:3.9-slim-buster

WORKDIR /app

# Add this section if your app needs specific system dependencies
# (Keep it commented if you're not getting compilation errors)
# RUN apt-get update && apt-get install -y \
#     build-essential \
#     # libpq-dev \
#     # libjpeg-dev \
#     # zlib1g-dev \
#     # libffi-dev \
#     # libssl-dev \
#     # git \
#     && rm -rf /var/lib/apt/lists/*

# Add this line to ensure the virtual environment's bin is in the PATH
ENV PATH="/opt/venv/bin:$PATH"

# This NIXPACKS_PATH might be redundant if we set PATH explicitly,
# but no harm in keeping it for now if Railway's build system uses it.
ENV NIXPACKS_PATH=/opt/venv/bin:$NIXPACKS_PATH

COPY . /app/.

# Separate the venv creation and pip install steps
RUN --mount=type=cache,id=s/2870766a-2668-4da8-b125-382cce9fc717-/root/cache/pip,target=/root/.cache/pip python -m venv --copies /opt/venv

RUN pip install -r requirements.txt
# No need to explicitly activate venv with '.' if PATH is set correctly above

# Your Procfile is also in the root, which is correct for Railway
# No changes needed for that based on this error.
# CMD (or ENTRYPOINT) for starting your app will go here if you use it,
# otherwise Railway will use your Procfile.
