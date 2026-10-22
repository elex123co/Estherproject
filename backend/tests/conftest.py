import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.ml.training import run_training  # noqa: E402
from generate_synthetic_data import generate  # noqa: E402


@pytest.fixture(scope="session")
def workspace(tmp_path_factory):
    """Synthetic data + a small trained model in a temp dir. Synthetic data is used ONLY for tests."""
    root = tmp_path_factory.mktemp("nid")
    data_dir = root / "synthetic"
    data_dir.mkdir()
    df = generate(5000, seed=3)
    df.to_csv(data_dir / "train.csv", index=False)
    model_dir = root / "models"
    run_training(data_dir, model_dir, seed=1, rf_trees=20, min_class_count=5,
                 dataset_name="synthetic-test", is_synthetic=True)
    # An upload that differs from the training file (fresh sample)
    generate(1200, seed=99).to_csv(root / "upload.csv", index=False)
    return root


def make_client(workspace, model_dir=None):
    settings = Settings(
        model_dir=model_dir or workspace / "models",
        data_dir=workspace / "data",
        database_path=workspace / "data" / f"test-{id(object())}.sqlite3",
        chunk_rows=500,
        max_upload_mb=5,
    )
    return TestClient(create_app(settings))


@pytest.fixture()
def client(workspace):
    with make_client(workspace) as c:
        yield c
