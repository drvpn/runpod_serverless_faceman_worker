FROM python:3.11-slim

# Set the working directory to /app
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Add app files (Worker Template)
COPY app /app

# Install torch and torchvision with the specific versions
RUN python3.11 -m pip install --upgrade pip && \
    python3.11 -m pip install torch==2.0.0+cu117 torchvision==0.15.0+cu117 --extra-index-url https://download.pytorch.org/whl/cu117 && \
    python3.11 -m pip install --upgrade -r /app/requirements.txt --no-cache-dir && \
    rm /app/requirements.txt

# Create symbolic links to the network volume
RUN ln -s runpod-volume/gfpgan/weights /app/gfpgan/weights

CMD ["python3.11", "-u", "/app/handler.py"]
