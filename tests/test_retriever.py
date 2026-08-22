from src.retriever import BM25Retriever


def test_bm25_can_find_cancellation_content():

    retriever = BM25Retriever.from_build()

    results = retriever.retrieve(
        "Northstar cancellation fee",
        account_id="ACCT-001",
        k=5,
    )

    assert results

    text = " ".join(
        result.section.text.lower()
        for result in results
    )

    assert (
        "cancellation" in text
        or "cancel" in text
    )


def test_account_scoped_documents_are_filtered():

    retriever = BM25Retriever.from_build()

    results = retriever.retrieve(
        "service agreement cancellation",
        account_id="ACCT-001",
        k=20,
    )

    for result in results:

        source = result.section.source

        if source is None:
            continue

        if source.scope != "global":

            assert source.scope == "ACCT-001"