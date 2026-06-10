"""Mnemonic password generation for secure, memorable authentication.

Uses a 1024-word list providing 10 bits of entropy per word.
Three words yield 30 bits of entropy (over 1 billion combinations).
"""

import hmac
import secrets

from qrdrop.core.wordlist import WORDS


def generate_password() -> str:
    """Generate a cryptographically secure mnemonic password.

    Returns a password in the format "word1-word2-word3" using three
    randomly selected words from the 1024-word list.

    Returns:
        str: A hyphen-separated three-word password.

    Entropy: 30 bits (1024^3 = 1,073,741,824 combinations)
    """
    word1 = secrets.choice(WORDS)
    word2 = secrets.choice(WORDS)
    word3 = secrets.choice(WORDS)
    return f"{word1}-{word2}-{word3}"


def validate_password(submitted: str, expected: str) -> bool:
    """Validate password using timing-safe comparison.

    Uses hmac.compare_digest to prevent timing attacks that could
    leak password information through response time analysis.

    Both values are encoded to UTF-8 bytes before comparison.
    hmac.compare_digest rejects str operands containing non-ASCII
    characters with a TypeError; comparing bytes both preserves the
    timing-safe guarantee and supports passwords/auth params that contain
    Unicode (e.g. a `--password` passphrase or a `?auth=` query value).

    Args:
        submitted: The password provided by the user.
        expected: The correct password to compare against.

    Returns:
        bool: True if passwords match, False otherwise.
    """
    return hmac.compare_digest(submitted.encode("utf-8"), expected.encode("utf-8"))
