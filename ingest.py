from rag import GITHUB_USERNAME, INDEX_PATH, build_index, discover_source_files


def main() -> None:
    files = discover_source_files()
    print("Indexing career documents:")
    for path in files:
        print(f"- {path}")

    if GITHUB_USERNAME:
        print(f"- GitHub profile and repositories for {GITHUB_USERNAME}")

    index = build_index(force=True)
    print(f"\nIndexed {len(index.get('chunks', []))} chunks.")
    print(f"Saved vector index to {INDEX_PATH}")


if __name__ == "__main__":
    main()
