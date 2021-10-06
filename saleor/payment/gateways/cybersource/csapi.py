# CyberSource Payment Gateway API

import hmac
import hashlib
import uuid

from datetime import datetime
from base64 import b64encode

# Payment Gateway API endpoint URLs:
LIVE_URL = 'https://secureacceptance.cybersource.com/pay'
TEST_URL = 'https://testsecureacceptance.cybersource.com/pay'

CURRENCY = 'NPR'    # Currency used for order/payment transaction.
LOCALE = 'en-us'    # Language to use for customer-facing content.

PAYMENT_METHOD = 'card' # Default payment method.

AUTH = 'authorization'  # Authorization/Hold the Payment.
CAPTURE = 'sale'        # Capture (Transfer) the Payment.

CREATE_TOKEN = 'create_payment_token'   # Create customer's payment card token.
UPDATE_TOKEN = 'update_payment_token'   # Update customer's payment card token.

TRANSACTION_TYPES = [
    f'{AUTH}',                      # Authorization/Hold the payment.
    f'{AUTH},{CREATE_TOKEN}',       # Not Used (implemented) for now.
    f'{AUTH},{UPDATE_TOKEN}',       # Not Used (implemented) for now.
    f'{CAPTURE}',                   # Capture (Transfer) the payment.
    f'{CAPTURE},{CREATE_TOKEN}',    # Not Used (implemented) for now.
    f'{CAPTURE},{UPDATE_TOKEN}',    # Not Used (implemented) for now.
]

# Format of the timestamp field.
TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

REQUIRED_FIELDS = {
    'access_key',
    'amount',
    'currency',
    'locale',
    'profile_id',
    'reference_number',
    #'signature',
    'signed_date_time',
    'signed_field_names',
    'transaction_type',
    'transaction_uuid',
    'unsigned_field_names',
}

SIGNED_FIELDS = {
    *REQUIRED_FIELDS,
    'bill_to_forename',
    'bill_to_surname',
    'bill_to_phone',
    'bill_to_address_line1',
    'bill_to_address_line2',
    'bill_to_address_city',
    'bill_to_address_postal_code',
    'bill_to_address_state',
    'bill_to_address_country',
    'payment_method',
}

ADDED_FIELDS = {
    'access_key',
    'currency',
    'locale',
    'profile_id',
    'signed_date_time',
    'signed_field_names',
    'transaction_type',
    'transaction_uuid',
    'unsigned_field_names',
}

CHECK_FIELDS = REQUIRED_FIELDS - ADDED_FIELDS

OPTIONAL_FIELDS = {
    'card_type',
    'card_number',
    'card_expiry_date',
}


class CyberSource:

    def __init__(self, config, auto_capture=True):
        try:
            self.profile_id = config['profile_id']
            self.access_key = config['access_key']
            self.secret_key = config['secret_key']
            self.is_live = config.get('is_live', False)
            self.locale = config.get('locale', LOCALE)
            self.auto_capture = auto_capture
        except KeyError as e:
            #FIXME: Raise custom exception.
            raise e

    @property
    def endpoint(self):
        if self.is_live:
            return LIVE_URL
        return TEST_URL

    @staticmethod
    def html(result, glue=''):
        return glue.join(
            f'<input type="hidden" name="{k}" value="{v}" />' \
            for k, v in result.items()
        )

    def _add_missing(self, result):
        if 'currency' not in result:
            result['currency'] = CURRENCY
        if 'locale' not in result:
            result['locale'] = LOCALE
        if 'payment_method' not in result:
            result['payment_method'] = PAYMENT_METHOD
        if 'transaction_uuid' not in result:
            result['transaction_uuid'] = str(uuid.uuid4())
        if 'signed_date_time' not in result:
            timestamp = datetime.now().strftime(TS_FORMAT)
            result['signed_date_time'] = timestamp
        return result

    def _create_result(self, data):
        result = data.copy()
        result['profile_id'] = self.profile_id
        result['access_key'] = self.access_key
        result['transaction_type'] = CAPTURE \
                if self.auto_capture else AUTH
        return self._add_missing(result)

    def process(self, data, html=False, glue=''):
        if CHECK_FIELDS.issubset(data.keys()):
            result = self._create_result(data)
            fields = result.keys()
            signed = set([f for f in fields if f in SIGNED_FIELDS])
            signed.update([
                'signed_field_names',
                'unsigned_field_names',
            ])
            unsigned = set([f for f in fields if f not in signed])
            signed, unsigned = sorted(signed), sorted(unsigned)
            result['signed_field_names'] = ','.join(signed)
            result['unsigned_field_names'] = ','.join(unsigned)
            if REQUIRED_FIELDS.issubset(fields):
                result['signature'] = self.sign(result, signed)
                if html:
                    return self.html(result, glue)
                return result
            #FIXME: Raise custom exception.
            raise Exception('Required fields check failed.')
        else:
            #FIXME: Raise custom exception.
            raise Exception('Required fields are missing.')

    def sign(self, data, fields, glue=','):
        try:
            vals = [str(data[f]) for f in fields]
        except KeyError as e:
            #FIXME: Raise custom exception.
            raise e
        digest = hmac.new(self.secret_key.encode(),
                msg=glue.join(vals).encode(),
                digestmod=hashlib.sha256).hexdigest()
        return b64encode(digest.encode()).decode()


# Test code.
if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        amount = float(sys.argv[1])
    else:
        amount = 100.00
    config = {
        'profile_id': 'F1A9A61D-44FE-489D-A167-925D0A669D26',
        'access_key': '028c5892be8233baba7baa30837c46e7',
        'secret_key': '99aae74b5abf45a494406cd9411aa93f231f1947d8be474ebdbc389fe6a0327017c2560ee6064e92b72922b63670941d88d81072416242f4931d52daf66da518131041cc6be04160b95cd9dde6bcfb99ce9cb11446054876aa8c2ab687067299ae456f34e3a84539bc0a884ac00a80c80ca762ac48f847a087550daa13da9ed7',
    }
    cs = CyberSource(config)
    data = {
        'amount': amount,
        'reference_number': datetime.now().strftime("%Y%m%d%H%M%S"),
        'bill_to_forename': "Bibek",
        'bill_to_surname': "Shrestha",
        'bill_to_phone': "9841234567",
        'bill_to_address_line1': "Lainchaur",
        'bill_to_address_city': "Kathmandu",
        'bill_to_address_postal_code': "44600",
        'bill_to_address_state': "Bagmati",
        'bill_to_address_country': "NP",
    }
    result = cs.process(data)
    rows = ['''
                <tr>
                  <td style="text-align: right;">%s</td>
                  <td style="text-align: left;">%s</td>
                </tr>
            ''' % (f, result[f]) for f in sorted(result.keys())]
    html = '''
        <html>
          <head>
            <title>CyberSource Test</title>
          </head>
          <body>
            <h1>CyberSource Payment Gateway Test</h1>
            <p>URL: %s</p>
            <form action="%s" method="POST">
              <table border="1" cellspacing="2" cellpadding="2">
                <tr>
                  <th>Field</th>
                  <th>Value</th>
                </tr>
                %s
                <tr>
                  <td colspan="2" style="text-align: center;">
                    %s<input type="submit" value=" Pay " />
                  </td>
                </tr>
              </table>
            </form>
          </body>
        </html>
    ''' % (cs.endpoint, cs.endpoint, ''.join(rows), cs.html(result, '\n'))
    print(html)
