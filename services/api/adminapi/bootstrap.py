"""Idempotent private bucket and initial administrator provisioning."""

import os

from botocore.exceptions import ClientError
from sqlalchemy import select

from adminapi.db import get_session_factory
from adminapi.models import User
from adminapi.security import hash_password
from adminapi.storage import get_storage


def main():
    storage = get_storage()
    try:
        storage._client.head_bucket(Bucket=storage._bucket)
    except ClientError as exc:
        if str(exc.response["Error"]["Code"]) not in ("404", "NoSuchBucket"):
            raise
        storage._client.create_bucket(Bucket=storage._bucket)
    email = os.environ["R4_ADMIN_EMAIL"].lower()
    with get_session_factory()() as session:
        if session.scalar(select(User).where(User.email == email)) is None:
            session.add(
                User(email=email, password_hash=hash_password(os.environ["R4_ADMIN_PASSWORD"]))
            )
            session.commit()
    print("Private bucket and administrator are ready.")


if __name__ == "__main__":
    main()
