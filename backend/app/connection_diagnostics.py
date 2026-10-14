"""Connectivity evidence only: no access to proposals or write gateways."""
from __future__ import annotations

import asyncio
import logging
import socket
from datetime import UTC, datetime
from time import perf_counter, time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

MESSAGES = {
    'OAUTH_REQUIRED': ('Jira necesita autorización.', 'Conectar cuenta Atlassian'),
    'OAUTH_IN_PROGRESS': ('Autorización pendiente de completar.', 'Completa el consentimiento en Atlassian.'),
    'OAUTH_EXPIRED': ('La autorización Atlassian venció.', 'Reconectar cuenta'),
    'OAUTH_INVALID': ('La autorización Atlassian guardada ya no puede utilizarse.', 'Reconectar cuenta'),
    'OAUTH_CANCELLED': ('La autorización de Atlassian fue cancelada.', 'Intentar de nuevo'),
    'OAUTH_TIMEOUT': ('Autorización no completada.', 'Intentar de nuevo'),
    'OAUTH_STATE_INVALID': ('El estado de la autorización no existe o ya venció.', 'Intentar de nuevo'),
    'OAUTH_CALLBACK_INVALID': ('La respuesta de autorización está incompleta.', 'Intentar de nuevo'),
    'OAUTH_NOT_CONFIGURED': ('La configuración OAuth no es válida.', 'Revisa el endpoint y la URL de retorno configurados.'),
    'NETWORK_UNAVAILABLE': ('No se pudo resolver el servidor Atlassian.', 'Revisa tu conexión, VPN o proxy y vuelve a intentarlo.'),
    'MCP_UNREACHABLE': ('No se puede contactar con Atlassian MCP.', 'Revisa tu conexión, VPN o proxy y vuelve a intentarlo.'),
    'MCP_TIMEOUT': ('Atlassian MCP no respondió a tiempo.', 'Reintentar'),
    'MCP_CAPABILITIES_MISSING': ('MCP no ofrece las herramientas de lectura necesarias.', 'Revisa los permisos y la configuración de Atlassian.'),
    'ATLASSIAN_ACCOUNT_UNAVAILABLE': ('No se pudo identificar la cuenta Atlassian.', 'Reconectar cuenta'),
    'JIRA_SITE_UNAVAILABLE': ('La cuenta Atlassian está conectada, pero no tiene acceso al sitio Jira configurado.', 'Revisa el sitio y el acceso de tu cuenta.'),
    'JIRA_PERMISSION_DENIED': ('La cuenta no tiene permisos suficientes para consultar Jira.', 'Solicita acceso al administrador del sitio.'),
    'SPACE_UNAVAILABLE': ('Jira está conectado, pero no se puede acceder al Space AT.', 'Revisa permisos o configuración.'),
    'JIRA_READY': ('Jira listo para trabajar.', 'Probar conexión'),
}


class ConnectionFailure(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(MESSAGES[code][0])


def classify(exc: BaseException, stage: str) -> str:
    if isinstance(exc, BaseExceptionGroup):
        return classify(exc.exceptions[0], stage)
    if isinstance(exc, ConnectionFailure):
        return exc.code
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return 'OAUTH_TIMEOUT' if stage == 'OAUTH_CALLBACK' else 'MCP_TIMEOUT'
    if isinstance(exc, socket.gaierror):
        return 'NETWORK_UNAVAILABLE'
    if isinstance(exc, httpx.ConnectError):
        return 'MCP_UNREACHABLE'
    text = str(exc).casefold()
    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    if status == 403 or 'forbidden' in text or 'permission' in text:
        return 'JIRA_PERMISSION_DENIED'
    if 'invalid_grant' in text or 'venció' in text or 'expired' in text or 'consentimiento de nuevo' in text:
        return 'OAUTH_EXPIRED'
    if status == 401 or 'unauthorized' in text or 'invalid_token' in text:
        return 'OAUTH_INVALID'
    if stage == 'RESTORE_SAVED_OAUTH':
        return 'OAUTH_INVALID'
    if 'no tiene visible' in text or stage == 'READ_ACCESSIBLE_RESOURCES':
        return 'JIRA_SITE_UNAVAILABLE'
    if 'herramientas mínimas' in text:
        return 'MCP_CAPABILITIES_MISSING'
    return 'MCP_UNREACHABLE'


def now():
    return datetime.now(UTC).isoformat()


def report(code='OAUTH_REQUIRED', stage='IDLE'):
    message, action = MESSAGES[code]
    return dict(state=code, message=message, action=action, phase=stage,
                request_id=uuid4().hex, checked_at=None, last_success_at=None,
                duration_ms=None, error_code=None, technical=None,
                checks={key: ('OK' if key == 'backend' else 'NOT_CHECKED') for key in
                        ('backend', 'network', 'mcp', 'oauth', 'account', 'site', 'space', 'capabilities')},
                capabilities=[], account=None, write_performed=False, tools_invoked=[])


def failure_report(exc, stage):
    code = classify(exc, stage)
    result = report(code, stage)
    result['error_code'] = code
    # Deliberately allowlist error data: no raw exception/response or OAuth material.
    result['technical'] = f'{code} ({type(exc).__name__})'
    if stage.startswith('READ_') or code in ('OAUTH_EXPIRED', 'OAUTH_INVALID'):
        result['checks']['mcp'] = 'OK'
    if stage.startswith('READ_') and not code.startswith('OAUTH_'):
        result['checks']['oauth'] = 'OK'
    if stage in ('READ_ACCESSIBLE_RESOURCES', 'READ_VISIBLE_PROJECTS'):
        result['checks']['account'] = 'OK'
    if stage == 'READ_VISIBLE_PROJECTS':
        result['checks']['site'] = 'OK'
    failed_key = 'oauth' if code.startswith('OAUTH_') else 'mcp'
    if code == 'JIRA_SITE_UNAVAILABLE': failed_key = 'site'
    if code == 'SPACE_UNAVAILABLE': failed_key = 'space'
    if code == 'JIRA_PERMISSION_DENIED': failed_key = 'capabilities'
    result['checks'][failed_key] = 'FAILED'
    return result


class OAuthAccessLogFilter(logging.Filter):
    """Uvicorn normally logs the complete callback query string."""
    def filter(self, record):
        if isinstance(record.args, tuple):
            record.args = tuple(
                value.split('?', 1)[0] + '?[REDACTED]'
                if isinstance(value, str) and '/integrations/atlassian/callback?' in value
                else value for value in record.args
            )
        return True


logging.getLogger('uvicorn.access').addFilter(OAuthAccessLogFilter())


class OAuthLibraryLogFilter(logging.Filter):
    def filter(self, record):
        # SDK exception tracebacks can embed OAuth response bodies or URLs.
        record.msg = 'OAuth SDK event category=' + record.levelname
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        return True


logging.getLogger('mcp.client.auth.oauth2').addFilter(OAuthLibraryLogFilter())


async def probe_endpoint(endpoint, proxy_url: str | None = None):
    """DNS is advisory: a proxy can reach MCP even when local DNS cannot."""
    host = urlsplit(endpoint).hostname
    dns_ok = False
    try:
        await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, 443), 3)
        dns_ok = True
    except (OSError, TimeoutError):
        pass
    try:
        options = {"timeout": httpx.Timeout(5, connect=3)}
        if proxy_url:
            options["proxy"] = proxy_url
        async with httpx.AsyncClient(**options) as client:
            response = await client.head(endpoint)
            if response.status_code not in (200, 204, 400, 401, 403, 405, 406):
                raise ConnectionFailure('MCP_UNREACHABLE')
    except httpx.ConnectError as exc:
        raise ConnectionFailure('MCP_UNREACHABLE' if dns_ok else 'NETWORK_UNAVAILABLE') from exc
    return {'network': 'OK' if dns_ok else 'UNCONFIRMED', 'mcp': 'OK'}


class ConnectionDiagnostics:
    def __init__(self, manager):
        self.manager = manager
        self.results = {}
        self.locks = {}

    def status(self, username):
        attempt = self.manager._attempts.get(username)
        if attempt and attempt.diagnostic_failure:
            return attempt.diagnostic_failure
        context = getattr(getattr(attempt, 'provider', None), 'context', None)
        expires_at = getattr(context, 'token_expiry_time', None)
        if isinstance(expires_at, (int, float)) and expires_at <= time():
            return failure_report(ConnectionFailure('OAUTH_EXPIRED'), 'OAUTH_VALIDITY')
        if username in self.results:
            return self.results[username]
        if attempt and attempt.authorization_url and not attempt.connected:
            return report('OAUTH_IN_PROGRESS', attempt.stage)
        if attempt and attempt.error:
            return failure_report(RuntimeError(attempt.error), attempt.stage)
        result = report()
        if attempt and attempt.connected and attempt.snapshot:
            snap = attempt.snapshot
            result = report('JIRA_READY' if any(s.get('key') == 'AT' and s.get('found') for s in snap.get('spaces', [])) else 'SPACE_UNAVAILABLE', 'COMPLETE')
            result['checks'].update({k: 'OK' for k in ('mcp', 'oauth', 'account', 'site')})
            result['checks']['space'] = 'OK' if result['state'] == 'JIRA_READY' else 'FAILED'
            result['last_success_at'] = snap.get('verified_at')
            result['checked_at'] = snap.get('verified_at')
            result['account'] = snap.get('atlassian_user', {}).get('display_name')
            result['capabilities'] = snap.get('read_tools_available', [])
            result['checks']['capabilities'] = 'OK' if {'atlassianUserInfo', 'getAccessibleAtlassianResources', 'getVisibleJiraProjects'} <= set(result['capabilities']) else 'NOT_CHECKED'
        return result

    async def check(self, username):
        async with self.locks.setdefault(username, asyncio.Lock()):
            started = perf_counter()
            previous = self.status(username)
            result = report()
            result['last_success_at'] = previous.get('last_success_at')
            result['phase'] = 'NETWORK'
            try:
                for url in (self.manager.settings.atlassian_mcp_url, self.manager.settings.atlassian_oauth_callback_url):
                    if urlsplit(url).scheme not in ('http', 'https') or not urlsplit(url).hostname:
                        raise ConnectionFailure('OAUTH_NOT_CONFIGURED')
                # Advisory probe never prevents an authenticated MCP attempt.
                probe_failure = None
                try:
                    result['checks'].update(await probe_endpoint(
                        self.manager.settings.atlassian_mcp_url,
                        self.manager.settings.atlassian_proxy_url,
                    ))
                except Exception as exc:
                    probe_failure = exc
                    result['checks']['mcp'] = 'FAILED'
                attempt = self.manager._attempts.get(username)
                if attempt and attempt.task and not attempt.task.done():
                    result.update(state='OAUTH_IN_PROGRESS', phase=attempt.stage)
                else:
                    if attempt is None:
                        attempt = self.manager.diagnostic_attempt(username)
                    if not attempt.storage.has_credentials:
                        if probe_failure:
                            raise probe_failure
                        raise ConnectionFailure('OAUTH_REQUIRED')
                    async with asyncio.timeout(30):
                        await self.manager.diagnostic_read(attempt, result)
                    result.update(state='JIRA_READY', phase='COMPLETE', last_success_at=now())
                    attempt.diagnostic_failure = None
            except Exception as exc:
                code = classify(exc, result['phase'])
                result.update(state=code, error_code=code, technical=f'{code} ({type(exc).__name__})')
                key = {'NETWORK': 'network', 'MCP_INITIALIZE': 'mcp', 'MCP_LIST_TOOLS': 'capabilities', 'READ_USER': 'account', 'READ_ACCESSIBLE_RESOURCES': 'site', 'READ_VISIBLE_PROJECTS': 'space'}.get(result['phase'], 'oauth')
                if code.startswith('OAUTH_'):
                    key = 'oauth'
                elif code.startswith('MCP_'):
                    key = 'mcp' if code != 'MCP_CAPABILITIES_MISSING' else 'capabilities'
                result['checks'][key] = 'FAILED'
            result['message'], result['action'] = MESSAGES[result['state']]
            result['checked_at'] = now()
            result['duration_ms'] = round((perf_counter() - started) * 1000)
            self.results[username] = result
            attempt = self.manager._attempts.get(username)
            if attempt:
                attempt.diagnostic_failure = None
                if result['state'] not in ('JIRA_READY', 'OAUTH_IN_PROGRESS'):
                    attempt.connected = False
                elif result['state'] == 'JIRA_READY' and attempt.snapshot:
                    attempt.connected = True
                    attempt.error = None
            logging.getLogger(__name__).info('connection_check timestamp=%s phase=%s duration_ms=%s success=%s category=%s request_id=%s', result['checked_at'], result['phase'], result['duration_ms'], result['state'] == 'JIRA_READY', result['error_code'], result['request_id'])
            return result
