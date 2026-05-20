"""
CLI: indexa os templates do registry na collection ChromaDB
`bridgemedai_templates`, usando o mesmo modelo de embeddings (Ollama)
do RAG regulatório.

Uso:
    python build_templates_index.py            # upsert idempotente
    python build_templates_index.py --rebuild  # apaga e recria a collection
"""

from __future__ import annotations

import argparse
import sys

from api_template_registry import (
    RegistryError,
    all_records,
    index_templates,
    is_indexed,
    reload_registry,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Apaga a collection antes de re-embeber tudo.",
    )
    args = parser.parse_args()

    reload_registry()
    try:
        total = len(all_records())
    except RegistryError as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        return 2

    print(f"[INFO] Registry carregado: {total} templates.")
    print(
        f"[INFO] Estado atual da collection: "
        f"{'indexada' if is_indexed() else 'vazia'}."
    )
    print(f"[INFO] A indexar (rebuild={args.rebuild})...")

    try:
        result = index_templates(rebuild=args.rebuild)
    except Exception as exc:
        print(f"[ERRO] Indexação falhou: {exc}", file=sys.stderr)
        return 1

    print(
        f"[OK] Indexados {result['indexed_count']} templates "
        f"na collection '{result['collection']}' (rebuilt={result['rebuilt']})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
