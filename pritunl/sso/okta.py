from pritunl import settings
from pritunl import logger
from pritunl import utils

import urllib
import httplib
import time
import urlparse

def _getokta_url():
    parsed = urlparse.urlparse(settings.app.sso_saml_url)
    return '%s://%s' % (parsed.scheme, parsed.netloc)

def get_user_id(username):
    try:
        response = utils.request.get(
            _getokta_url() + '/api/v1/users/%s' % urllib.quote(username),
            headers={
                'Accept': 'application/json',
                'Authorization': 'SSWS %s' % settings.app.sso_okta_token,
            },
        )
    except httplib.HTTPException:
        logger.exception('Okta api error', 'sso',
            username=username,
        )
        return None

    if response.status_code != 200:
        logger.error('Okta api error', 'sso',
            username=username,
            status_code=response.status_code,
            response=response.content,
        )
        return None

    data = response.json()
    if 'id' in data:
        return data['id']

    logger.error('Okta username not found', 'sso',
        username=username,
        status_code=response.status_code,
        response=response.content,
    )

    return None

def get_factor_id(user_id):
    try:
        response = utils.request.get(
            _getokta_url() + '/api/v1/users/%s/factors' % user_id,
            headers={
                'Accept': 'application/json',
                'Authorization': 'SSWS %s' % settings.app.sso_okta_token,
            },
        )
    except httplib.HTTPException:
        logger.exception('Okta api error', 'sso',
            user_id=user_id,
        )
        return None

    if response.status_code != 200:
        logger.error('Okta api error', 'sso',
            user_id=user_id,
            status_code=response.status_code,
            response=response.content,
        )
        return None

    not_active = False
    data = response.json()
    for factor in data:
        if 'id' not in factor or 'provider' not in factor or \
                'factorType' not in factor or 'status' not in factor:
            continue

        if factor['provider'].lower() != 'okta' or \
                factor['factorType'].lower() != 'push':
            continue

        if factor['status'].lower() != 'active':
            not_active = True
            continue

        return factor['id']

    if not_active:
        logger.error('Okta push not active', 'sso',
            user_id=user_id,
        )
        return None
    else:
        logger.warning('Okta push not available, skipping', 'sso',
            user_id=user_id,
        )
        return True

def auth_okta(username, strong=False, ipaddr=None, type=None, info=None):
    user_id = get_user_id(username)
    if not user_id:
        return False

    factor_id = get_factor_id(user_id)
    if not factor_id:
        return False

    try:
        response = utils.request.post(
            _getokta_url() + '/api/v1/users/%s/factors/%s/verify' % (
                user_id, factor_id),
            headers={
                'Accept': 'application/json',
                'Authorization': 'SSWS %s' % settings.app.sso_okta_token,
            },
        )
    except httplib.HTTPException:
        logger.exception('Okta api error', 'sso',
            username=username,
            user_id=user_id,
            factor_id=factor_id,
        )
        return False

    if response.status_code != 201:
        logger.error('Okta api error', 'sso',
            username=username,
            user_id=user_id,
            factor_id=factor_id,
            status_code=response.status_code,
            response=response.content,
        )
        return False

    poll_url = None

    while True:
        data = response.json()
        result = data.get('factorResult').lower()

        if result == 'success':
            return True
        elif result == 'waiting':
            pass
        else:
            logger.error('Okta got bad result', 'sso',
                username=username,
                user_id=user_id,
                factor_id=factor_id,
                result=result,
            )
            return False

        if not poll_url:
            links = data.get('_links')
            if not links:
                logger.error('Okta cant find links', 'sso',
                    username=username,
                    user_id=user_id,
                    factor_id=factor_id,
                    data=data,
                )
                return False

            poll = links.get('poll')
            if not poll:
                logger.error('Okta cant find poll', 'sso',
                    username=username,
                    user_id=user_id,
                    factor_id=factor_id,
                    data=data,
                )
                return False

            poll_url = poll.get('href')
            if not poll_url:
                logger.error('Okta cant find href', 'sso',
                    username=username,
                    user_id=user_id,
                    factor_id=factor_id,
                    data=data,
                )
                return False

        time.sleep(0.2)

        try:
            response = utils.request.get(
                poll_url,
                headers={
                    'Accept': 'application/json',
                    'Authorization': 'SSWS %s' % settings.app.sso_okta_token,
                },
            )
        except httplib.HTTPException:
            logger.exception('Okta poll api error', 'sso',
                username=username,
                user_id=user_id,
                factor_id=factor_id,
            )
            return False

        if response.status_code != 200:
            logger.error('Okta poll api error', 'sso',
                username=username,
                user_id=user_id,
                factor_id=factor_id,
                status_code=response.status_code,
                response=response.content,
            )
            return False
