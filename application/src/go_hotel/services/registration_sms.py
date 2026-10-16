"""Registration / recovery delivery over SMS.

There is **no** SMS provider connected in this environment, so this module is a
deliberate stub: it reports not-ready and refuses to send. The verification
service still routes the ``sms`` channel through it, which keeps the channel
honest — an account can never be created, and a password can never be reset, on
an SMS code that was never actually delivered.

The only way the ``sms`` channel becomes usable here is
``registration_verification_test_code``, which is an explicit operator switch and
skips delivery entirely (see ``registration_verification.issue``). Wiring a real
provider means implementing ``send_code`` and returning ``True`` from ``ready``;
nothing else about the challenge lifecycle has to change.
"""


def ready():
    """False until a real SMS transport exists for this environment."""
    return False


def send_code(recipient, code):
    raise ValueError('REGISTRATION_SMS_NOT_READY')
