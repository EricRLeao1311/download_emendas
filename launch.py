from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "app:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8501")),
        reload=False,
    )


if __name__ == "__main__":
    main()
