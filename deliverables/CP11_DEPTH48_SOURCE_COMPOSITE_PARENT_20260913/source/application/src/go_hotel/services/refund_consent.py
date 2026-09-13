"""Bind customer acceptance to the exact owner/order/terms under the order lock."""
from hmac import compare_digest

from go_hotel.autonomy.durable import digest


def bind(vertical, order, quote):
    value = dict(quote)
    value.pop('quote_hash', None)
    value['quote_hash'] = digest({
        'version': 1, 'vertical': vertical, 'account_id': order.account_id,
        'order_id': order.order_id, 'order_status': order.status,
        'order_updated_at': str(order.updated_at), 'terms': value.copy(),
    })
    return value


def verify(quote, accepted_hash):
    if accepted_hash is None:
        # Compatibility only for existing internal/legacy callers. New native
        # confirmed endpoints require a strict nonempty SHA256 and explicit yes.
        return
    current = quote.get('quote_hash')
    if (not isinstance(accepted_hash, str) or not isinstance(current, str)
            or len(accepted_hash) != 64 or not compare_digest(current, accepted_hash)):
        raise ValueError('REFUND_QUOTE_CHANGED_RECONFIRM_REQUIRED')
