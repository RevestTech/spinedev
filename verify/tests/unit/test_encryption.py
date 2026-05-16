"""
Expanded unit tests for field-level encryption utilities.

Tests:
  - Encrypt/decrypt roundtrip
  - Key generation and validation
  - Empty string handling
  - Error cases (invalid token, corrupted ciphertext)
  - Key rotation
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet

from tron.infra.encryption import FieldEncryptor, get_encryptor, reset_encryptor


class TestFieldEncryptorInit:
    """Tests for FieldEncryptor initialization."""

    def test_encryptor_init_with_valid_key(self):
        """FieldEncryptor initialized with valid Fernet key."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        assert encryptor is not None

    def test_encryptor_init_with_invalid_key_raises(self):
        """FieldEncryptor raises ValueError for invalid key."""
        invalid_key = b"not-a-valid-fernet-key"
        
        with pytest.raises(ValueError, match="Invalid encryption key"):
            FieldEncryptor(invalid_key)

    def test_encryptor_init_stores_key(self):
        """FieldEncryptor stores the key internally."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        assert encryptor._key == key

    def test_encryptor_init_creates_cipher(self):
        """FieldEncryptor creates Fernet cipher."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        assert encryptor._cipher is not None


class TestEncryptDecryptRoundtrip:
    """Tests for encrypt/decrypt operations."""

    def test_encrypt_decrypt_simple_string(self):
        """Encrypt and decrypt returns original string."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        plaintext = "secret-data-123"
        encrypted = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(encrypted)
        
        assert decrypted == plaintext

    def test_encrypt_returns_base64_encoded(self):
        """Encrypted output is base64-encoded string."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        plaintext = "test"
        encrypted = encryptor.encrypt(plaintext)
        
        assert isinstance(encrypted, str)
        # Base64 encoded strings have alphanumeric + /+= characters
        import re
        assert re.match(r"^[A-Za-z0-9+/=]+$", encrypted)

    def test_encrypt_multiple_calls_produce_different_ciphertexts(self):
        """Multiple encryptions of same plaintext produce different tokens."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        plaintext = "data"
        encrypted1 = encryptor.encrypt(plaintext)
        encrypted2 = encryptor.encrypt(plaintext)
        
        # Fernet uses timestamp and nonce, so ciphertexts differ
        assert encrypted1 != encrypted2

    def test_decrypt_different_encrypted_tokens_same_result(self):
        """Decrypting different tokens of same plaintext gives same result."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        plaintext = "data"
        encrypted1 = encryptor.encrypt(plaintext)
        encrypted2 = encryptor.encrypt(plaintext)
        
        assert encryptor.decrypt(encrypted1) == plaintext
        assert encryptor.decrypt(encrypted2) == plaintext

    def test_encrypt_unicode_string(self):
        """Encrypt/decrypt handles Unicode strings."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        plaintext = "Hello-世界-🔐"
        encrypted = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(encrypted)
        
        assert decrypted == plaintext

    def test_encrypt_very_long_string(self):
        """Encrypt/decrypt handles very long strings."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        plaintext = "x" * 100000  # 100KB
        encrypted = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(encrypted)
        
        assert decrypted == plaintext

    def test_encrypt_string_with_special_characters(self):
        """Encrypt/decrypt handles special characters."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        plaintext = "!@#$%^&*()_+-=[]{}|;:',.<>?/~`\n\t\r"
        encrypted = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(encrypted)
        
        assert decrypted == plaintext

    def test_encrypt_empty_string_returns_empty(self):
        """Encrypt empty string returns empty string."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        encrypted = encryptor.encrypt("")
        
        assert encrypted == ""

    def test_decrypt_empty_string_returns_empty(self):
        """Decrypt empty string returns empty string."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        decrypted = encryptor.decrypt("")
        
        assert decrypted == ""

    def test_decrypt_invalid_token_raises(self):
        """Decrypt with invalid token raises ValueError."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        invalid_token = "not-a-valid-token"
        
        with pytest.raises(ValueError, match="Decryption failed"):
            encryptor.decrypt(invalid_token)

    def test_decrypt_corrupted_ciphertext_raises(self):
        """Decrypt with corrupted ciphertext raises ValueError."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        plaintext = "test"
        encrypted = encryptor.encrypt(plaintext)
        
        # Corrupt the encrypted data
        corrupted = encrypted[:-5] + "xxxxx"
        
        with pytest.raises(ValueError, match="Decryption failed"):
            encryptor.decrypt(corrupted)

    def test_decrypt_with_wrong_key_raises(self):
        """Decrypt with different key raises ValueError."""
        key1 = Fernet.generate_key()
        key2 = Fernet.generate_key()
        
        encryptor1 = FieldEncryptor(key1)
        encryptor2 = FieldEncryptor(key2)
        
        plaintext = "secret"
        encrypted = encryptor1.encrypt(plaintext)
        
        with pytest.raises(ValueError, match="Decryption failed"):
            encryptor2.decrypt(encrypted)


class TestKeyRotation:
    """Tests for key rotation functionality."""

    def test_rotate_key_success(self):
        """Key rotation re-encrypts data with new key."""
        old_key = Fernet.generate_key()
        new_key = Fernet.generate_key()
        
        encryptor_old = FieldEncryptor(old_key)
        plaintext = "sensitive-data"
        encrypted_old = encryptor_old.encrypt(plaintext)
        
        # Rotate the key
        rotated = encryptor_old.rotate_key(old_key, new_key, encrypted_old)
        
        # Verify the rotated ciphertext decrypts with new key
        encryptor_new = FieldEncryptor(new_key)
        decrypted = encryptor_new.decrypt(rotated)
        
        assert decrypted == plaintext

    def test_rotate_key_invalid_old_key_raises(self):
        """Key rotation with invalid old key raises ValueError."""
        old_key = Fernet.generate_key()
        new_key = Fernet.generate_key()
        invalid_key = b"not-valid"
        
        encryptor = FieldEncryptor(old_key)
        ciphertext = encryptor.encrypt("data")
        
        with pytest.raises(ValueError, match="Key rotation failed"):
            encryptor.rotate_key(invalid_key, new_key, ciphertext)

    def test_rotate_key_corrupted_ciphertext_raises(self):
        """Key rotation with corrupted ciphertext raises ValueError."""
        old_key = Fernet.generate_key()
        new_key = Fernet.generate_key()
        
        encryptor = FieldEncryptor(old_key)
        corrupted = "not-a-valid-ciphertext"
        
        with pytest.raises(ValueError, match="Key rotation failed"):
            encryptor.rotate_key(old_key, new_key, corrupted)

    def test_rotate_key_multiple_times(self):
        """Multiple key rotations work correctly."""
        keys = [Fernet.generate_key() for _ in range(5)]
        plaintext = "original-data"
        
        # Encrypt with first key
        encryptor = FieldEncryptor(keys[0])
        ciphertext = encryptor.encrypt(plaintext)
        
        # Rotate through all keys
        for i in range(len(keys) - 1):
            ciphertext = encryptor.rotate_key(keys[i], keys[i + 1], ciphertext)
        
        # Verify with final key
        final_encryptor = FieldEncryptor(keys[-1])
        decrypted = final_encryptor.decrypt(ciphertext)
        
        assert decrypted == plaintext


class TestGetEncryptor:
    """Tests for get_encryptor initialization."""

    async def test_get_encryptor_returns_instance(self):
        """get_encryptor returns FieldEncryptor instance."""
        reset_encryptor()

        with patch("tron.infra.secrets.get_secret") as mock_get_secret:
            key = Fernet.generate_key()
            mock_get_secret.return_value = key

            encryptor = await get_encryptor()

            assert isinstance(encryptor, FieldEncryptor)

    async def test_get_encryptor_caches_instance(self):
        """get_encryptor returns cached instance on subsequent calls."""
        reset_encryptor()

        with patch("tron.infra.secrets.get_secret") as mock_get_secret:
            key = Fernet.generate_key()
            mock_get_secret.return_value = key

            encryptor1 = await get_encryptor()
            encryptor2 = await get_encryptor()

            assert encryptor1 is encryptor2
            # Secret should only be fetched once
            assert mock_get_secret.call_count == 1

    async def test_get_encryptor_missing_key_raises(self):
        """get_encryptor raises RuntimeError if key not in keyvault."""
        reset_encryptor()

        with patch("tron.infra.secrets.get_secret") as mock_get_secret:
            mock_get_secret.return_value = None

            with pytest.raises(RuntimeError, match="Encryption initialization failed"):
                await get_encryptor()

    async def test_get_encryptor_key_from_keyvault(self):
        """get_encryptor fetches key from keyvault."""
        reset_encryptor()

        with patch("tron.infra.secrets.get_secret") as mock_get_secret:
            key = Fernet.generate_key()
            mock_get_secret.return_value = key

            await get_encryptor()

            mock_get_secret.assert_called_once_with("encryption/master-key")

    async def test_get_encryptor_handles_string_key(self):
        """get_encryptor converts string key to bytes."""
        reset_encryptor()

        with patch("tron.infra.secrets.get_secret") as mock_get_secret:
            key_bytes = Fernet.generate_key()
            key_str = key_bytes.decode("utf-8")
            mock_get_secret.return_value = key_str

            encryptor = await get_encryptor()

            # Should work without error
            plaintext = "test"
            encrypted = encryptor.encrypt(plaintext)
            decrypted = encryptor.decrypt(encrypted)

            assert decrypted == plaintext

    async def test_get_encryptor_invalid_key_raises(self):
        """get_encryptor raises if key is invalid."""
        reset_encryptor()

        with patch("tron.infra.secrets.get_secret") as mock_get_secret:
            mock_get_secret.return_value = b"invalid-key"

            with pytest.raises(RuntimeError, match="Encryption initialization failed"):
                await get_encryptor()


class TestResetEncryptor:
    """Tests for reset_encryptor utility."""

    async def test_reset_encryptor_clears_cache(self):
        """reset_encryptor clears cached instance."""
        reset_encryptor()

        with patch("tron.infra.secrets.get_secret") as mock_get_secret:
            key = Fernet.generate_key()
            mock_get_secret.return_value = key

            await get_encryptor()
            reset_encryptor()
            await get_encryptor()

            # Should fetch key twice (once for each get_encryptor after reset)
            assert mock_get_secret.call_count == 2


class TestEncryptionEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_encrypt_whitespace_only_string(self):
        """Encrypt/decrypt whitespace-only strings."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        plaintext = "   \n\t\r  "
        encrypted = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(encrypted)
        
        assert decrypted == plaintext

    def test_encrypt_string_with_null_bytes(self):
        """Encrypt/decrypt handles strings with null bytes."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        plaintext = "before\x00after"
        encrypted = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(encrypted)
        
        assert decrypted == plaintext

    def test_encrypt_newlines_preserved(self):
        """Encrypt/decrypt preserves newlines."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        plaintext = "line1\nline2\nline3"
        encrypted = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(encrypted)
        
        assert decrypted == plaintext

    def test_encrypt_tabs_preserved(self):
        """Encrypt/decrypt preserves tabs."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        plaintext = "col1\tcol2\tcol3"
        encrypted = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(encrypted)
        
        assert decrypted == plaintext

    def test_multiple_encryptors_same_key_interoperable(self):
        """Multiple encryptor instances with same key are interoperable."""
        key = Fernet.generate_key()
        
        encryptor1 = FieldEncryptor(key)
        encryptor2 = FieldEncryptor(key)
        
        plaintext = "data"
        encrypted_by_1 = encryptor1.encrypt(plaintext)
        decrypted_by_2 = encryptor2.decrypt(encrypted_by_1)
        
        assert decrypted_by_2 == plaintext


class TestEncryptionPerformance:
    """Tests for encryption performance characteristics."""

    def test_encrypt_large_data(self):
        """Encryption works with large data payloads."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        # 10MB of data
        plaintext = "x" * (10 * 1024 * 1024)
        
        encrypted = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(encrypted)
        
        assert decrypted == plaintext
        assert len(encrypted) > len(plaintext)  # Ciphertext larger due to overhead

    def test_encrypt_many_small_items(self):
        """Encryption works with many small items."""
        key = Fernet.generate_key()
        encryptor = FieldEncryptor(key)
        
        items = [f"item-{i}" for i in range(1000)]
        encrypted_items = [encryptor.encrypt(item) for item in items]
        decrypted_items = [encryptor.decrypt(enc) for enc in encrypted_items]
        
        assert decrypted_items == items
