import uvicorn
from common.utils import load_config


def main():
    print("[API] Starting Smart Grid Monitoring API & Dashboard Server at http://localhost:8000 ...")
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
