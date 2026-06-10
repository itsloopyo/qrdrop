"""Tests for mnemonic password generation and timing-safe validation."""

from qrdrop.core.password import generate_password, validate_password
from qrdrop.core.wordlist import WORDS


class TestGeneratePassword:
    def test_returns_three_words_separated_by_hyphen(self) -> None:
        pw = generate_password()
        parts = pw.split("-")
        assert len(parts) == 3
        for word in parts:
            assert word in WORDS

    def test_passwords_are_random(self) -> None:
        # 1024^3 combinations; collisions in 100 samples are essentially impossible
        seen = {generate_password() for _ in range(100)}
        assert len(seen) == 100


class TestValidatePassword:
    def test_match_returns_true(self) -> None:
        assert validate_password("abc-def-ghi", "abc-def-ghi") is True

    def test_mismatch_returns_false(self) -> None:
        assert validate_password("abc-def-ghi", "xyz-def-ghi") is False

    def test_empty_strings_match(self) -> None:
        assert validate_password("", "") is True

    def test_one_empty_does_not_match(self) -> None:
        assert validate_password("", "secret") is False

    def test_case_sensitive(self) -> None:
        assert validate_password("ABC", "abc") is False

    def test_length_difference_does_not_raise(self) -> None:
        # hmac.compare_digest accepts unequal lengths (returns False)
        assert validate_password("short", "muchlongerpassword") is False

    def test_non_ascii_submitted_does_not_raise(self) -> None:
        # Raw hmac.compare_digest raises TypeError on non-ASCII str operands;
        # validate_password must encode to bytes and simply return False.
        assert validate_password("café-naïve-señor", "apple-banana-cherry") is False

    def test_non_ascii_expected_password_is_usable(self) -> None:
        # A user-supplied --password with Unicode must still validate correctly
        # rather than crashing every login attempt.
        assert validate_password("café-naïve-señor", "café-naïve-señor") is True
        assert validate_password("wrong", "café-naïve-señor") is False
