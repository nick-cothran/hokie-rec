"""Shared validation for account names and contact information."""

import re
from typing import Annotated

from pydantic import AfterValidator, EmailStr, StringConstraints


def normalize_email(value: str) -> str:
    return value.lower()


def validate_phone(value: str) -> str:
    if len(re.sub(r"\D", "", value)) < 7:
        raise ValueError("Enter a phone number with at least seven digits.")
    return value


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50,
                                      pattern=r"^[^\x00-\x1f\x7f]+$")]
Email = Annotated[EmailStr, StringConstraints(max_length=100), AfterValidator(normalize_email)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, min_length=7, max_length=20,
                                       pattern=r"^[+0-9(). -]+$"), AfterValidator(validate_phone)]
