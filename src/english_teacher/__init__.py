import os

# Everything runs locally: use the cached Hugging Face models and never call the Hub.
# Must be set before huggingface_hub is imported. Download models with scripts/download_models.py.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
