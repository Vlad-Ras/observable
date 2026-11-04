import os, tempfile, secrets
os.environ["UPLOAD_TOKEN"] = secrets.token_urlsafe(32)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="observable-preview-")
os.environ["PUBLIC_URL"] = "http://localhost:3000"
import uvicorn
uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", "3000")), access_log=False)
