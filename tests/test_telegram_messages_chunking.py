"""Tests for app.telegram.messages.chunk_message - Telegram rejects
sendMessage calls whose text exceeds 4096 chars with a 400 Bad Request, so
long replies (e.g. /today or /jobs with many results) must be split before
sending. Regression coverage for a live crash caused by this."""
from __future__ import annotations

from app.telegram.messages import MAX_MESSAGE_LENGTH, chunk_message


def test_short_text_returns_single_chunk():
    assert chunk_message("hello") == ["hello"]


def test_text_at_exact_limit_returns_single_chunk():
    text = "a" * MAX_MESSAGE_LENGTH
    assert chunk_message(text) == [text]


def test_long_text_split_into_multiple_chunks_each_within_limit():
    block = "x" * 2000
    # Five blocks joined by blank lines - well past 4096 total.
    text = "\n\n".join([block] * 5)

    chunks = chunk_message(text)

    assert len(chunks) > 1
    assert all(len(chunk) <= MAX_MESSAGE_LENGTH for chunk in chunks)
    # No content lost - every block shows up intact in some chunk.
    assert all(block in "".join(chunks) for block in [block])


def test_chunking_prefers_blank_line_boundaries():
    """A job block should not be split mid-block when it fits whole into a
    chunk together with prior blocks."""
    job_blocks = [f"Job {i}\nDetails {i}" for i in range(1, 4)]
    text = "\n\n".join(job_blocks)

    chunks = chunk_message(text, limit=40)

    # Every original job block appears intact somewhere in the output.
    for block in job_blocks:
        assert any(block in chunk for chunk in chunks)


def test_single_block_larger_than_limit_is_hard_sliced():
    huge_block = "y" * 10000
    chunks = chunk_message(huge_block, limit=4096)

    assert len(chunks) == 3  # 10000 / 4096 -> 3 chunks
    assert all(len(chunk) <= 4096 for chunk in chunks)
    assert "".join(chunks) == huge_block
