from app.services.embedding_service import chunk_text


def test_long_paragraph_makes_progress_with_overlap():
    chunks = chunk_text("abcdefghij", chunk_size=4, overlap=2)
    assert chunks
    assert chunks[-1].endswith("ij")
    assert all(len(chunk) <= 7 for chunk in chunks)


def test_explicit_zero_overlap_is_respected():
    assert chunk_text("abcdefgh", chunk_size=4, overlap=0) == ["abcd", "efgh"]


def test_overlap_is_capped_below_chunk_size():
    chunks = chunk_text("abcdef", chunk_size=3, overlap=99)
    assert chunks[-1].endswith("def")


def test_invalid_chunk_size_is_rejected():
    try:
        chunk_text("abc", chunk_size=0)
    except ValueError:
        return
    raise AssertionError("expected ValueError")
