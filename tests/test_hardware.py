from nexus.hardware import recommend_ollama_model


def test_prefer_e4b_over_26b_when_present():
    models = ["gemma4:26b", "nomic-embed-text:latest", "gemma4:e4b", "gemma:7b"]
    assert recommend_ollama_model(models, mem_available_gb=30) == "gemma4:e4b"


def test_skip_heavy_when_low_ram():
    models = ["gemma4:26b", "gemma:7b"]
    assert recommend_ollama_model(models, mem_available_gb=16) == "gemma:7b"


def test_default_pull_name_when_empty():
    assert recommend_ollama_model([], mem_available_gb=8) == "gemma2:2b"
