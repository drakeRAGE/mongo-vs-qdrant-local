# Third-party data

This harness can download:

- [Tevatron/msmarco-passage-corpus](https://huggingface.co/datasets/Tevatron/msmarco-passage-corpus)
- BEIR / MS MARCO query splits via Hugging Face `datasets`

Those corpora remain under their upstream licenses and terms. This repository stores only SHA-256 hashes of the frozen embedding files in `data/manifests/MANIFEST.json`. It does not ship the passages or vectors.

MongoDB Community Search (`mongot`) and Qdrant are used under their respective licenses. Image pins are recorded in `compose/docker-compose.yml`.
