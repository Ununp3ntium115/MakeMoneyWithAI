import json


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = json.dumps(self._payload)

    def json(self):
        return self._payload


def openai_chat_payload(content_obj):
    """Wrap an object the way the Chat Completions API returns it."""
    return {"choices": [{"message": {"content": json.dumps(content_obj)}}]}
