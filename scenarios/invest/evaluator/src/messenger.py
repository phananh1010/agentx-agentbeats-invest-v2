import json
from uuid import uuid4
from typing import Any, Dict, List, Tuple

import httpx
from a2a.client import (
    A2ACardResolver,
    ClientConfig,
    ClientFactory,
    Consumer,
)
from a2a.types import (
    DataPart,
    Message,
    Part,
    Role,
    TextPart,
)

DEFAULT_TIMEOUT = 300


def create_message(*, role: Role = Role.user, text: str, context_id: str | None = None) -> Message:
    return Message(
        kind="message",
        role=role,
        parts=[Part(TextPart(kind="text", text=text))],
        message_id=uuid4().hex,
        context_id=context_id,
    )


def _collect_parts(parts: List[Part]) -> Tuple[List[str], List[Dict[str, Any]]]:
    texts: List[str] = []
    data: List[Dict[str, Any]] = []
    for part in parts:
        if isinstance(part.root, TextPart):
            texts.append(part.root.text)
        elif isinstance(part.root, DataPart):
            try:
                data.append(part.root.data)
            except Exception:
                try:
                    data.append(json.loads(json.dumps(part.root.data)))
                except Exception:
                    pass
    return texts, data


async def send_message(
    message: str,
    base_url: str,
    context_id: str | None = None,
    streaming: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
    consumer: Consumer | None = None,
):
    async with httpx.AsyncClient(timeout=timeout) as httpx_client:
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=base_url)
        agent_card = await resolver.get_agent_card()
        config = ClientConfig(httpx_client=httpx_client, streaming=streaming)
        factory = ClientFactory(config)
        client = factory.create(agent_card)
        if consumer:
            await client.add_event_consumer(consumer)

        outbound_msg = create_message(text=message, context_id=context_id)
        last_event = None
        outputs: dict[str, object] = {
            "response_text": "",
            "context_id": None,
            "data_parts": [],
        }

        async for event in client.send_message(outbound_msg):
            last_event = event

        match last_event:
            case Message() as msg:
                outputs["context_id"] = msg.context_id
                text_parts, data_parts = _collect_parts(msg.parts)
                outputs["response_text"] = "\n".join(text_parts)
                outputs["data_parts"] = data_parts
            case (task, _update):
                outputs["context_id"] = task.context_id
                status_msg = task.status.message
                text_parts, data_parts = _collect_parts(status_msg.parts) if status_msg else ([], [])
                outputs["response_text"] = "\n".join(text_parts)
                if task.artifacts:
                    for artifact in task.artifacts:
                        _, artifact_data = _collect_parts(artifact.parts)
                        outputs["data_parts"].extend(artifact_data)
                outputs["data_parts"].extend(data_parts)
                outputs["status"] = task.status.state.value
            case _:
                pass

        return outputs


class Messenger:
    def __init__(self):
        self._context_ids: dict[str, str | None] = {}

    async def talk_to_agent(
        self,
        message: str,
        url: str,
        new_conversation: bool = False,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> dict[str, object]:
        outputs = await send_message(
            message=message,
            base_url=url,
            context_id=None if new_conversation else self._context_ids.get(url),
            timeout=timeout,
        )
        if outputs.get("status", "completed") != "completed":
            raise RuntimeError(f"{url} responded with non-completed status: {outputs}")
        self._context_ids[url] = outputs.get("context_id")
        return outputs

    def reset(self) -> None:
        self._context_ids = {}
