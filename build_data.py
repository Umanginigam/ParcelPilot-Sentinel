"""One-time build: xlsx -> SQLite and PDFs -> sections.json.
Run once after placing the data pack in ./data:  python build_data.py
The two pipelines are independent; they only converge at the resolution engine.
"""
from src.db import build_sqlite
from src.retriever import build_sections

if __name__ == "__main__":
    build_sqlite()
    build_sections()
    print("Build complete: build/parcelpilot.db + build/sections.json")
