"""Small HTTPS RPC transport for Alibaba DirectMail; no request/body logging."""
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import uuid


class MailError(Exception):
    def __init__(self, code, status=None):
        super().__init__(code)
        self.code, self.status = code, status


def signature(parameters, secret):
    encode = lambda value: urllib.parse.quote(str(value), safe='~-._')
    canonical = '&'.join(encode(k) + '=' + encode(v) for k, v in sorted(parameters.items()))
    value = 'POST&%2F&' + encode(canonical)
    return base64.b64encode(hmac.new((secret + '&').encode(), value.encode(), hashlib.sha1).digest()).decode()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


class DirectMail:
    kind = 'aliyun_directmail'

    def __init__(self, *, timeout=10):
        self._id = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_ID', '')
        self._secret = os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_SECRET', '')
        if not self._id or not self._secret:
            raise MailError('credentials_missing')
        self.timeout = timeout

    def send(self, address, code, purpose):
        if not re.fullmatch(r'[0-9]{6}', code) or purpose not in ('register', 'login', 'preflight'):
            raise MailError('invalid_message')
        if not isinstance(address, str) or len(address) > 254 or re.search(r'[\r\n,;<>]', address):
            raise MailError('invalid_message')
        parameters = {
            'AccessKeyId': self._id, 'Action': 'SingleSendMail', 'Format': 'JSON',
            'Version': '2015-11-23', 'RegionId': 'cn-hangzhou',
            'SignatureMethod': 'HMAC-SHA1', 'SignatureVersion': '1.0',
            'SignatureNonce': uuid.uuid4().hex,
            'Timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'AccountName': 'no-reply@auth.cmcs.codes', 'AddressType': '1',
            'ReplyToAddress': 'false', 'ToAddress': address, 'FromAlias': 'OreBOGAO',
            'Subject': 'OreBOGAO 邮箱验证码',
            'TextBody': '您的 OreBOGAO 验证码为：' + code + '。有效期为 5 分钟，请勿向他人提供。如非本人操作，请忽略本邮件。',
        }
        parameters['Signature'] = signature(parameters, self._secret)
        request = urllib.request.Request('https://dm.aliyuncs.com/',
            data=urllib.parse.urlencode(parameters).encode(),
            headers={'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=self.timeout) as response:
                result = json.loads(response.read(65536))
                if response.status != 200 or result.get('Code') or not result.get('RequestId'):
                    raise MailError('provider_rejected')
                return {'request_id': result['RequestId'], 'envelope_id': result.get('EnvId')}
        except urllib.error.HTTPError as exc:
            # Do not expose provider messages, signed requests, addresses, or key IDs.
            try:
                error_code = json.loads(exc.read(16384)).get('Code', '')
            except Exception:
                error_code = ''
            if 'Forbidden' in error_code or exc.code == 403:
                reason = 'permission_denied'
            elif any(x in error_code for x in ('InvalidAccessKey', 'SignatureDoesNotMatch', 'Authentication')):
                reason = 'credentials_invalid'
            else:
                reason = 'provider_rejected'
            raise MailError(reason, exc.code) from None
        except (TimeoutError, socket.timeout):
            raise MailError('timeout') from None
        except urllib.error.URLError as exc:
            raise MailError('timeout' if isinstance(exc.reason, (TimeoutError, socket.timeout)) else 'unavailable') from None
        except (ValueError, OSError):
            raise MailError('unavailable') from None
