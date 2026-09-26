"""Package by default. --apply creates a Foundry version and requires operator approval."""
import argparse
import time
from datetime import timedelta

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    CodeConfiguration,
    HostedAgentDefinition,
    ProtocolVersionRecord,
    SessionConfiguration,
)
from azure.identity import DefaultAzureCredential

from package_agent import package


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project-endpoint', required=True)
    parser.add_argument('--model-endpoint', required=True)
    parser.add_argument('--deployment', required=True)
    parser.add_argument('--agent-name', default='regula-research-review')
    parser.add_argument('--idle-timeout-seconds', type=int, default=120,
                        choices=range(120, 3601), metavar='120..3600')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    path, sha = package()
    definition = HostedAgentDefinition(
        cpu='1', memory='2Gi',
        code_configuration=CodeConfiguration(runtime='python_3_13', entry_point=['python','main.py'],
                                               dependency_resolution='remote_build'),
        protocol_versions=[ProtocolVersionRecord(protocol='responses', version='2.0.0')],
        session_configuration=SessionConfiguration(
            idle_timeout_seconds=timedelta(seconds=args.idle_timeout_seconds)),
        environment_variables={'MODEL_PROVIDER':'azure', 'AZURE_OPENAI_ENDPOINT':args.model_endpoint,
                               'OPENAI_DEPLOYMENT_ID':args.deployment,
                               'OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT':'false'},
    )
    print(f'Prepared {args.agent_name}: {path.name}, sha256={sha}, compute=1 CPU/2Gi, '
          f'idle timeout={args.idle_timeout_seconds}s.')
    if not args.apply:
        print('No Azure changes. --apply creates a hosted agent version and incurs usage charges.')
        return
    with DefaultAzureCredential() as credential, AIProjectClient(endpoint=args.project_endpoint, credential=credential) as project:
        created = project.agents.create_version_from_code(
            agent_name=args.agent_name, definition=definition,
            code=(path.name, path.read_bytes(), 'application/zip'), code_zip_sha256=sha,
            description='Regula bounded synthesis and independent model review; no publication tools.')
        for _ in range(120):
            version = project.agents.get_version(agent_name=args.agent_name, agent_version=created.version)
            status = version['status']
            print(f'Agent version {created.version}: {status}')
            if status == 'active':
                return
            if status == 'failed':
                raise RuntimeError('Hosted agent provisioning failed; inspect deployment diagnostics.')
            time.sleep(5)
        raise TimeoutError('Provisioning did not finish within ten minutes; inspect the existing version before retrying.')


if __name__ == '__main__':
    main()
