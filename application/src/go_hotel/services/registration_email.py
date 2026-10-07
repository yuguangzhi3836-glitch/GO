"""Registration delivery through the operator's existing SMTP account.

Only server-configured read-only files are read. No public endpoint accepts a
host, sender, credential path or SMTP parameters. No credential/code is logged.
"""
import json
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from go_hotel.core.config import settings

SENDER = 'postmaster@goaidirect.com'


def configuration():
    try:
        path = settings.registration_email_config_path
        if not path:
            raise ValueError()
        value = json.loads(Path(path).read_text())
        if not isinstance(value, dict):
            raise ValueError()
        if value.get('sender') != SENDER or value.get('credential_reference') != 'hk-staging-registration-email':
            raise ValueError()
        if value.get('tls') not in ('STARTTLS', 'SSL'):
            raise ValueError()
        for field in ('host', 'username'):
            if not isinstance(value.get(field), str) or not value[field].strip():
                raise ValueError()
        # bool is an int subclass, but is not a valid SMTP port configuration.
        if type(value.get('port')) is not int or not 1 <= value['port'] <= 65535:
            raise ValueError()
        if not Path(value['password_file']).is_absolute():
            raise ValueError()
        # This is the EXISTING account's mounted secret, never returned to callers.
        password = Path(value['password_file']).read_text().rstrip('\r\n')
        if not password:
            raise ValueError()
        return value, password
    except (ValueError, TypeError, KeyError, OSError):
        raise ValueError('REGISTRATION_VERIFICATION_NOT_READY') from None


def ready():
    if not settings.registration_verification_enabled:
        return False
    try:
        configuration()
        return True
    except ValueError:
        return False


def send_code(recipient, code):
    cfg, password = configuration()
    msg = EmailMessage()
    msg['From'] = SENDER
    msg['To'] = recipient
    msg['Subject'] = 'GO 注册验证码'
    msg.set_content(f'您的 GO 注册验证码是：{code}。10 分钟内有效。请勿向他人提供验证码。若非本人操作，请忽略此邮件。')
    try:
        factory = smtplib.SMTP_SSL if cfg['tls'] == 'SSL' else smtplib.SMTP
        kwargs = {'timeout': 10}
        if cfg['tls'] == 'SSL':
            kwargs['context'] = ssl.create_default_context()
        with factory(cfg['host'], cfg['port'], **kwargs) as smtp:
            if cfg['tls'] == 'STARTTLS':
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            smtp.login(cfg['username'], password)
            if smtp.send_message(msg, from_addr=SENDER, to_addrs=[recipient]):
                raise ValueError()
    except Exception:
        # Provider messages may contain recipient/credentials. Do not propagate.
        raise ValueError('REGISTRATION_EMAIL_SEND_FAILED') from None
