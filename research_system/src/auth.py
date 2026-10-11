"""Single-tenant Entra access-token validation; local identity remains explicit."""
import asyncio
from functools import lru_cache

import jwt
from fastapi import HTTPException


@lru_cache(maxsize=4)
def signing_keys(tenant):
    return jwt.PyJWKClient(f'https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys',
                          cache_keys=True, lifespan=300, timeout=10)


async def validate_entra(authorization, config):
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(status_code=401, detail='A Microsoft Entra access token is required')
    token = authorization[7:]
    try:
        key = await asyncio.to_thread(signing_keys(config.entra_tenant_id).get_signing_key_from_jwt, token)
        claims = jwt.decode(token, key.key, algorithms=['RS256'], audience=config.entra_audience,
                            issuer=f'https://login.microsoftonline.com/{config.entra_tenant_id}/v2.0',
                            options={'require': ['exp','iat','nbf','iss','aud','tid','oid']})
        if claims['tid'] != config.entra_tenant_id or config.entra_scope not in claims.get('scp', '').split():
            raise ValueError('Wrong tenant or missing delegated API scope')
        return claims['tid'], claims['oid']
    except Exception as error:
        raise HTTPException(status_code=401, detail='Invalid or unauthorized Entra access token') from error
