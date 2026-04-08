"""
Generate a self-signed TLS certificate for Morgana.

Creates server.crt and server.key under the specified output directory.
Also exports morgana-ca.cer (DER format) for installation on client machines.

Usage:
    python generate-ssl-cert.py --ip 192.168.0.160 --out ../server/certs
"""

import argparse
import datetime
import ipaddress
import os
import sys

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
except ImportError:
    print("[ERROR] cryptography package not installed.")
    print("        Run: pip install cryptography")
    sys.exit(1)


def generate_cert(ip_address: str, out_dir: str, days: int = 1825) -> tuple:
    os.makedirs(out_dir, exist_ok=True)

    print(f"[INFO] Generating RSA-2048 self-signed cert for IP: {ip_address}")

    # Generate RSA key
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # Certificate subject
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Morgana"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "X3M.AI"),
    ])

    # Subject Alternative Names
    san_list = [
        x509.DNSName("localhost"),
        x509.DNSName("morgana"),
    ]
    try:
        san_list.append(x509.IPAddress(ipaddress.ip_address(ip_address)))
    except ValueError:
        print(f"[WARN] '{ip_address}' is not a valid IP address - SAN IP entry skipped.")

    # Also add 127.0.0.1
    san_list.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))

    not_before = datetime.datetime.now(datetime.timezone.utc)
    not_after  = not_before + datetime.timedelta(days=days)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(
            x509.SubjectAlternativeName(san_list),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    # Write private key (PEM, no passphrase)
    key_path = os.path.join(out_dir, "server.key")
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    print(f"[OK] Private key  : {key_path}")

    # Write certificate (PEM)
    crt_path = os.path.join(out_dir, "server.crt")
    with open(crt_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    print(f"[OK] Certificate  : {crt_path}")

    # Write DER copy for Windows certutil import on client machines
    cer_path = os.path.join(out_dir, "morgana-ca.cer")
    with open(cer_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.DER))
    print(f"[OK] CA cert (DER): {cer_path}")
    print(f"     --> Copy morgana-ca.cer to every Excel machine and run:")
    print(f"         certutil -addstore Root morgana-ca.cer   (as Administrator)")

    return crt_path, key_path, cer_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Morgana self-signed TLS certificate")
    parser.add_argument(
        "--ip",
        default="192.168.0.160",
        help="LAN IP address of the Morgana server (default: 192.168.0.160)",
    )
    parser.add_argument(
        "--out",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server", "certs"),
        help="Output directory for certs (default: ../server/certs)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1825,
        help="Certificate validity in days (default: 1825 = 5 years)",
    )
    args = parser.parse_args()

    crt, key, cer = generate_cert(
        ip_address=args.ip,
        out_dir=os.path.abspath(args.out),
        days=args.days,
    )
    print()
    print("[SUCCESS] Cert generation complete.")
    print(f"          Next: run Enable-MorganaSSL.ps1 as Administrator to activate HTTPS.")
