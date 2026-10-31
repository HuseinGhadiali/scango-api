"""Sign and send a sample payment webhook to the local server, the way a provider would.

Run it with the server running (python manage.py runserver):

    python scripts/send_test_webhook.py <order_id>
    python scripts/send_test_webhook.py <order_id> --type payment.refunded
    python scripts/send_test_webhook.py <order_id> --event-id evt_1   # run twice: 2nd is a duplicate

The secret must match the server's PAYMENT_WEBHOOK_SECRET. Both use the same local default, or
set the PAYMENT_WEBHOOK_SECRET environment variable for both.

Only the standard library is used, so the script runs without Django or extra packages.
"""

import argparse
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
import uuid

DEFAULT_URL = "http://127.0.0.1:8000/api/payments/webhook/"
DEFAULT_SECRET = "local-dev-webhook-secret"  # the same default as config/settings.py


def sign(body, secret):
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("order_id")
    parser.add_argument(
        "--type",
        default="payment.succeeded",
        choices=["payment.succeeded", "payment.refunded"],
    )
    parser.add_argument("--event-id", help="defaults to a new random id")
    parser.add_argument("--url", default=DEFAULT_URL)
    return parser.parse_args()


def main():
    args = parse_args()
    secret = os.environ.get("PAYMENT_WEBHOOK_SECRET", DEFAULT_SECRET)
    payload = {
        "event_id": args.event_id or f"evt_{uuid.uuid4().hex[:16]}",
        "type": args.type,
        "order_id": args.order_id,
    }
    # The bytes that are signed must be exactly the bytes that are sent.
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        args.url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Signature": sign(body, secret)},
    )

    print(f"Sending {payload}")
    try:
        with urllib.request.urlopen(request) as response:
            print(response.status, response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        # urlopen raises on 4xx/5xx; print the server's answer instead of a traceback.
        print(error.code, error.read().decode("utf-8"))


if __name__ == "__main__":
    main()
