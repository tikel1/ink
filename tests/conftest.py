"""Test fixtures — isolate each run in a temp data dir with test secrets."""
import os
import tempfile

import pytest
from cryptography.fernet import Fernet

# Configure the backend BEFORE its settings are first read (lru_cache).
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="artframe-test-")
os.environ["MASTER_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["PLATFORM_OPENAI_API_KEY"] = "platform-test-key"
os.environ["ADMIN_TOKEN"] = "admin-test-token"
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ["PUBLIC_BASE_URL"] = "http://testserver"


@pytest.fixture(autouse=True)
def fresh_db():
    from backend.config import get_settings
    from backend.db import init_db

    get_settings.cache_clear()
    settings = get_settings()
    if settings.db_path.exists():
        settings.db_path.unlink()
    init_db()
    yield
