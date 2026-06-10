"""Tests for wordlist module."""

from qrdrop.core.wordlist import WORDS


class TestWordlist:
    """Tests for the wordlist."""

    def test_wordlist_has_1024_words(self) -> None:
        """Wordlist must have exactly 1024 words for proper entropy."""
        assert len(WORDS) == 1024, f"Expected 1024 words, got {len(WORDS)}"

    def test_all_words_are_unique(self) -> None:
        """Duplicate words would reduce entropy below the advertised 30 bits."""
        from collections import Counter

        duplicates = [word for word, count in Counter(WORDS).items() if count > 1]
        assert not duplicates, f"Duplicate words in wordlist: {duplicates}"

    def test_all_words_are_strings(self) -> None:
        """All entries in wordlist must be strings."""
        for word in WORDS:
            assert isinstance(word, str), f"Expected string, got {type(word)}: {word}"

    def test_all_words_are_non_empty(self) -> None:
        """All words must be non-empty."""
        for word in WORDS:
            assert len(word) > 0, "Found empty word in wordlist"

    def test_all_words_are_lowercase(self) -> None:
        """All words should be lowercase for consistency."""
        for word in WORDS:
            assert word == word.lower(), f"Word is not lowercase: {word}"

    def test_words_have_reasonable_length(self) -> None:
        """Words should be between 2 and 10 characters."""
        for word in WORDS:
            assert 2 <= len(word) <= 10, f"Word has unreasonable length: {word}"
