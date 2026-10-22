"""Self-signed HTTPS certificate (phone browsers only allow the mic on HTTPS)."""
from __future__ import annotations

import datetime
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def cert_fingerprint(cert_path: Path) -> str:
    """SHA-256 of the certificate (DER), hex - what the Android app pins."""
    cert = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
    return cert.fingerprint(hashes.SHA256()).hex()


def ensure_cert(data_dir: Path, ips: list[str], hostname: str | None = None) -> tuple[Path, Path]:
    """Create the certificate once and keep it.

    Chrome remembers "Proceed anyway" per certificate, so it is only regenerated when the stable
    hostname changes, never because the laptop got a different IP on another network.
    """
    cert_path = data_dir / "cert.pem"
    key_path = data_dir / "key.pem"
    meta_path = data_dir / "cert_host.txt"

    wanted = hostname or ""
    if cert_path.exists() and key_path.exists() and meta_path.exists() \
            and meta_path.read_text().strip() == wanted:
        return cert_path, key_path

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname or "Fasway")])
    san = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(i)) for i in set(ips)]
    if hostname:
        san.insert(0, x509.DNSName(hostname))
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    meta_path.write_text(wanted)
    (data_dir / "cert_ips.txt").unlink(missing_ok=True)   # old format
    return cert_path, key_path
