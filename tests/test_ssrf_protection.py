"""Tests de la protection SSRF dans le scraper d'URL.

Vérifie que les adresses privées, loopback, link-local et IPv6
ne peuvent pas être accédées via le scraper.
"""

import pytest

from src.interfaces.scrapers.url.scraper import (
    _is_private_host,
    _is_private_ip,
    normalize_url,
)


class TestPrivateIP:
    """Détection des IPs privées/réservées."""

    def test_ipv4_private_a_class(self):
        assert _is_private_ip("10.0.0.1") is True
        assert _is_private_ip("10.255.255.255") is True

    def test_ipv4_private_b_class(self):
        assert _is_private_ip("172.16.0.1") is True
        assert _is_private_ip("172.31.255.255") is True

    def test_ipv4_private_c_class(self):
        assert _is_private_ip("192.168.0.1") is True
        assert _is_private_ip("192.168.255.255") is True

    def test_ipv4_loopback(self):
        assert _is_private_ip("127.0.0.1") is True
        assert _is_private_ip("127.255.255.255") is True

    def test_ipv4_link_local(self):
        assert _is_private_ip("169.254.0.1") is True
        assert _is_private_ip("169.254.255.255") is True

    def test_ipv4_unspecified(self):
        assert _is_private_ip("0.0.0.0") is True

    def test_ipv4_multicast(self):
        assert _is_private_ip("224.0.0.1") is True
        assert _is_private_ip("239.255.255.250") is True

    def test_ipv4_reserved(self):
        assert _is_private_ip("240.0.0.1") is True

    def test_ipv4_public(self):
        assert _is_private_ip("8.8.8.8") is False
        assert _is_private_ip("1.1.1.1") is False
        assert _is_private_ip("34.120.195.1") is False

    def test_ipv6_loopback(self):
        """::1 est le loopback IPv6 —doit être détecté comme privé."""
        assert _is_private_ip("::1") is True

    def test_ipv6_ipv4_mapped(self):
        """::ffff:127.0.0.1 est le loopback IPv4 en IPv6 —doit être détecté."""
        assert _is_private_ip("::ffff:127.0.0.1") is True

    def test_ipv6_link_local(self):
        """fe80::1 est une adresse link-local IPv6 —doit être détectée."""
        assert _is_private_ip("fe80::1") is True

    def test_ipv6_unique_local(self):
        """fc00:: et fd00:: sont des ULAs IPv6 —doivent être détectés."""
        assert _is_private_ip("fc00::1") is True
        assert _is_private_ip("fd00::1") is True

    def test_ipv6_multicast(self):
        """ff00:: sont des адреса multicast IPv6 —doivent être détectés."""
        assert _is_private_ip("ff02::1") is True

    def test_ipv6_technical_scope(self):
        """Les адреса de groupe technique (ff00::/8) sont réservées."""
        assert _is_private_ip("ff01::1") is True  # interface-local

    def test_ipv6_public(self):
        """Les адреса IPv6 publiques ne sont pas privées."""
        assert _is_private_ip("2001:4860:4860::8888") is False
        assert _is_private_ip("2a00:1450:4001:802::200e") is False


class TestPrivateHost:
    """Résolution DNS d'hôtes privés."""

    def test_hostname_public(self):
        """Un hostname public n'est pas privé."""
        # Ne dépend pas de la résolution DNS réelle
        assert _is_private_host("example.com") is False
        assert _is_private_host("google.com") is False

    def test_hostname_literal_private_ip(self):
        """Un hostname qui est littéralement une IP privée."""
        assert _is_private_host("127.0.0.1") is True
        assert _is_private_host("192.168.1.1") is True
        assert _is_private_host("10.0.0.1") is True

    def test_hostname_literal_ipv6(self):
        """Un hostname qui est littéralement une IPv6."""
        assert _is_private_host("::1") is True
        assert _is_private_host("fe80::1") is True

    def test_hostname_empty(self):
        """Un hostname vide n'est pas privé."""
        assert _is_private_host("") is False
        assert _is_private_host(None) is False  # type: ignore

    def test_invalid_hostname(self):
        """Un hostname invalide (non résolvable) passe (Playwright échouera)."""
        assert _is_private_host("this-does-not-exist-xyz123.invalid") is False


class TestNormalizeURL:
    """Validation et normalisation des URLs."""

    def test_rejects_non_http(self):
        with pytest.raises(Exception):  # URLScrapingError
            normalize_url("ftp://example.com/file")
        with pytest.raises(Exception):
            normalize_url("file:///etc/passwd")
        with pytest.raises(Exception):
            normalize_url("javascript:alert(1)")

    def test_rejects_private_ip_literal(self):
        with pytest.raises(Exception):
            normalize_url("http://127.0.0.1/")
        with pytest.raises(Exception):
            normalize_url("http://192.168.0.1/admin")
        with pytest.raises(Exception):
            normalize_url("http://10.0.0.1/")
        with pytest.raises(Exception):
            normalize_url("http://[::1]/")

    def test_rejects_private_hostname(self):
        """Un hostname qui résout vers une IP privée."""
        # localhost résout typiquement vers 127.0.0.1
        with pytest.raises(Exception):
            normalize_url("http://localhost/")

    def test_strips_fragment(self):
        """Le fragment (#) est retiré pour éviter le dédoublonnage par ancres."""
        url = normalize_url("https://example.com/page#section")
        assert "#" not in url

    def test_normalizes_scheme_lowercase(self):
        """Le schéma est normalisé en minuscules (le path/host peut être
        préservé tel quel — c'est un comportement connu de urlsplit)."""
        url = normalize_url("HTTPS://EXAMPLE.COM/Page")
        assert url.startswith("https://")
        assert "EXAMPLE.COM" in url or "example.com" in url
        assert "Page" in url

    def test_accepts_valid_public_url(self):
        url = normalize_url("https://example.com/page?q=1")
        assert "example.com" in url
        assert url.startswith("https://")

    def test_rejects_empty_url(self):
        with pytest.raises(Exception):
            normalize_url("")
        with pytest.raises(Exception):
            normalize_url("   ")
