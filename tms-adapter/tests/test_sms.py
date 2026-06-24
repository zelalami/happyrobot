import pytest

from app.services.phone import mask_phone, normalize_phone
from app.services.sms import StubSmsSender, TwilioSmsSender, get_sms_sender


# ------------------------------- phone utils ------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("9203695500", "+19203695500"),
    ("(920) 369-5500", "+19203695500"),
    ("1-920-369-5500", "+19203695500"),
    ("", None),
    (None, None),
])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_mask_phone_keeps_prefix_and_last4():
    assert mask_phone("+19203695500") == "+1******5500"
    assert mask_phone(None) is None


# ------------------------------- stub sender ------------------------------- #
async def test_stub_records_and_masks():
    s = StubSmsSender()
    res = await s.send("+19203695500", "Your code is 424242")
    assert res.sent is True and res.to_masked == "+1******5500"
    assert len(s.outbox) == 1 and s.outbox[0].to == "+19203695500"


async def test_twilio_sender_is_deferred():
    with pytest.raises(NotImplementedError):
        await TwilioSmsSender().send("+19203695500", "hi")


def test_factory_returns_stub_shared_instance():
    # SMS is stub-only for now; the factory hands back the shared stub regardless of settings.
    assert get_sms_sender() is get_sms_sender()
    assert isinstance(get_sms_sender(), StubSmsSender)
