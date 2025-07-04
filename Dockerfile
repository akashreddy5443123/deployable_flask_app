# Assuming you have a FROM line at the top, e.g.:
FROM python:3.9-slim-buster # Or whatever Python version you prefer and have tested locally

WORKDIR /app

# Add this section if your app needs specific system dependencies
# This is a common requirement for packages like psycopg2, Pillow, numpy, cryptography
# You'll likely need to add more here depending on your requirements.txt
# RUN apt-get update && apt-get install -y \
#     build-essential \
#     libpq-dev \
#     libjpeg-dev \
#     zlib1g-dev \
#     # ... potentially other libraries like libffi-dev, libssl-dev, git ...
#     && rm -rf /var/lib/apt/lists/*


ENV NIXPACKS_PATH=/opt/venv/bin:$NIXPACKS_PATH

COPY . /app/.

# --- IMPORTANT CHANGE HERE ---
# Separate the venv creation and pip install steps
RUN --mount=type=cache,id=s/2870766a-2668-4da8-b125-382cce9fc717-/root/cache/pip,target=/root/.cache/pip python -m venv --copies /opt/venv

# This next line is where the error will become clear
RUN . /opt/venv/bin/activate && pip install -r requirements.txt
# --- END IMPORTANT CHANGE ---

# Your Procfile is also in the root, which is correct for Railway
# No changes needed for that based on this error.
# CMD (or ENTRYPOINT) for starting your app will go here if you use it,
# otherwise Railway will use your Procfile.