"""Stateless role execution hosted by Foundry; approval stays application-owned."""
import asyncio
import json
import os

# Opt in only after the deployment's telemetry redaction policy is validated.
os.environ.setdefault('OTEL_SDK_DISABLED', 'true')
os.environ.setdefault('OTEL_PYTHON_DISABLED_INSTRUMENTATIONS', 'openai_v2')

from azure.ai.agentserver.responses import ResponsesAgentServerHost, TextResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from src.config import ModelConfig
from src.model_client import create_model_client


class RoleRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['planner', 'synthesizer', 'fact_checker', 'critical_reviewer']
    instructions: str = Field(max_length=10000)
    payload: dict


app = ResponsesAgentServerHost()


@app.response_handler
async def handle(request, context, cancellation_signal: asyncio.Event):
    text = await context.get_input_text() or ''
    if len(text) > 180000:
        raise ValueError('Request exceeds the context bound')
    data = RoleRequest.model_validate_json(text)
    config = ModelConfig()
    if config.model_provider != 'azure':
        raise ValueError('Hosted role execution requires MODEL_PROVIDER=azure')
    model = create_model_client(config)
    operation = asyncio.create_task(model.complete_json(data.role, data.instructions, data.payload))
    cancellation = asyncio.create_task(cancellation_signal.wait())
    try:
        done, _ = await asyncio.wait([operation, cancellation], return_when=asyncio.FIRST_COMPLETED)
        if cancellation in done:
            operation.cancel()
            raise asyncio.CancelledError()
        return TextResponse(context, request, text=json.dumps(await operation))
    finally:
        cancellation.cancel()


if __name__ == '__main__':
    app.run()
