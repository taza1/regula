"""Invoke an explicitly deployed Foundry hosted agent through its dedicated endpoint."""
import asyncio
import json

from src.model_client import ModelConnectionError, _parse_json_object, _validate_plan


class FoundryResearchModelClient:
    provider = 'foundry'

    def __init__(self, config):
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential
        if not config.foundry_project_endpoint or not config.foundry_agent_name:
            raise ValueError('FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_AGENT_NAME are required')
        self.model = config.foundry_agent_name
        self._project = AIProjectClient(endpoint=config.foundry_project_endpoint,
                                         credential=DefaultAzureCredential())
        self._client = self._project.get_openai_client(agent_name=config.foundry_agent_name)
        self._timeout = config.model_timeout_seconds

    async def complete_json(self, role, instructions, payload):
        body = json.dumps({'role': role, 'instructions': instructions, 'payload': payload})
        if len(body) > 180000:
            raise ModelConnectionError('Research context exceeds the request bound.')
        try:
            response = await asyncio.to_thread(self._client.responses.create,
                                               input=body, store=False, timeout=self._timeout)
            return _parse_json_object(response.output_text)
        except Exception as error:
            raise ModelConnectionError(f'Foundry agent request failed ({type(error).__name__}).') from error

    async def create_research_plan(self, research_request):
        result = await self.complete_json('planner',
            'Return {subquestions:[string],search_queries:[string],evidence_criteria:{}}. '
            'Include contradictory evidence searches; do not answer the question.', research_request)
        _validate_plan(result)
        return result

    def status(self):
        return {'provider': self.provider, 'model': self.model, 'configured': True,
                'remote': True, 'runtime': 'foundry-hosted-agent'}
