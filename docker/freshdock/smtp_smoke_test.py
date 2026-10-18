#!/usr/bin/env python3
"""One-shot private Freshdock SMTP smoke test; no credentials in output."""
import argparse
from email.message import EmailMessage
import smtplib
import ssl
import sys
import tomllib
from pathlib import Path

CONF = Path("/docker/freshdock/freshdock.toml")

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--send", action="store_true",
                   help="deliver one configuration-test email")
    args = p.parse_args()
    if not CONF.is_file() or CONF.is_symlink() or (CONF.stat().st_mode & 0o077):
        raise RuntimeError("Private Freshdock TOML missing or not access-restricted")
    with CONF.open("rb") as f:
        target = tomllib.load(f).get("notifications", {}).get("email", {})
    if target.get("type") != "smtp":
        raise RuntimeError("Freshdock SMTP notifier is not configured")
    host, port = target["host"], int(target["port"])
    sender, targets = target["from"], target["to"]
    username, password = target["username"], target["password"]
    tls = target.get("tls")
    if tls not in ("starttls", "implicit") or not username or not password or not targets:
        raise RuntimeError("SMTP transport/login/recipients are incomplete")
    print("SMTP configuration: present; transport:", tls, "recipients:", len(targets))
    if not args.send:
        print("READ ONLY: add --send to deliver a single smoke-test message")
        return 0
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(targets)
    message["Subject"] = "Freshdock OMV email test"
    message.set_content("Freshdock SMTP configuration was tested successfully on openmediavault.")
    context = ssl.create_default_context()
    if tls == "implicit":
        with smtplib.SMTP_SSL(host, port, context=context, timeout=18) as smtp:
            smtp.login(username, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=18) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(username, password)
            smtp.send_message(message)
    print("PASS: SMTP server accepted the Freshdock test email.")
    print("Confirm delivery in the destination mailbox.")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, KeyError, OSError, smtplib.SMTPException) as exc:
        print("FAIL: SMTP test did not succeed (credentials/address details suppressed).",
              file=sys.stderr)
        sys.exit(1)
