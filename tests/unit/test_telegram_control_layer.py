from __future__ import annotations

import pytest


class FakeUser:
    def __init__(self, user_id: int, username: str = "hamza") -> None:
        self.id = user_id
        self.username = username


class FakeQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.answered = []
        self.edited_text = None
        self.reply_markup = None

    async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
        self.answered.append({"text": text, "show_alert": show_alert})

    async def edit_message_text(self, text: str, reply_markup=None) -> None:
        self.edited_text = text
        self.reply_markup = reply_markup


class FakeMessage:
    def __init__(self) -> None:
        self.replies = []

    async def reply_text(self, text: str, reply_markup=None) -> None:
        self.replies.append({"text": text, "reply_markup": reply_markup})


class FakeUpdate:
    def __init__(self, user_id: int, query: FakeQuery | None = None) -> None:
        self.effective_user = FakeUser(user_id)
        self.callback_query = query
        self.effective_message = FakeMessage()


def _layer():
    from autonomous_xauusd.communication_layer import TelegramControlLayer

    return TelegramControlLayer(
        token="token",
        chat_id="chat",
        owner_user_id="999",
        backend_api_key="test_secret_key_32_characters_long",
        backend_base_url="http://testserver",
        status_callback=lambda: "status",
        stop_callback=lambda: "stop",
        train_callback=lambda: "train",
    )


@pytest.mark.asyncio
async def test_unauthorized_user_is_blocked():
    layer = _layer()
    query = FakeQuery("menu:dashboard")
    update = FakeUpdate(user_id=123, query=query)

    await layer._on_callback(update, None)

    assert query.answered[-1]["show_alert"] is True
    assert query.answered[-1]["text"] == "Geen toegang"


@pytest.mark.asyncio
async def test_dangerous_action_requests_confirmation(monkeypatch):
    layer = _layer()
    query = FakeQuery("control:emergency_stop")
    update = FakeUpdate(user_id=999, query=query)

    # Mock the embedded service — emergency_stop without confirmation must ask for it
    class FakeService:
        def handle_control_action(self, action, user_id, username, confirmed=False):
            return {
                "action": action,
                "status": "confirmation_required",
                "summary": "Bevestiging vereist.",
                "requires_confirmation": True,
                "command_id": None,
                "data": {},
            }

    monkeypatch.setattr(layer, "_service", FakeService())

    await layer._on_callback(update, None)

    assert "Weet je zeker" in query.edited_text
    buttons = query.reply_markup.inline_keyboard[0]
    assert buttons[0].callback_data == "confirm:emergency_stop:yes"
    assert buttons[1].callback_data == "confirm:emergency_stop:no"


@pytest.mark.asyncio
async def test_confirm_yes_executes_action(monkeypatch):
    layer = _layer()
    query = FakeQuery("confirm:emergency_stop:yes")
    update = FakeUpdate(user_id=999, query=query)
    called = {}

    # Mock the embedded service — confirmed action must be executed
    class FakeService:
        def handle_control_action(self, action, user_id, username, confirmed=False):
            called["action"] = action
            called["confirmed"] = confirmed
            return {
                "action": action,
                "status": "accepted",
                "summary": "Emergency Stop command geaccepteerd.",
                "requires_confirmation": False,
                "command_id": 1,
                "data": {},
            }

    monkeypatch.setattr(layer, "_service", FakeService())

    await layer._on_callback(update, None)

    assert called["action"] == "emergency_stop"
    assert called["confirmed"] is True
    assert query.edited_text == "Emergency Stop command geaccepteerd."
