"""
author: matt.cai(cysnake4713@gmail.com)
Inspired by Wechatpy, thanks to @messense  http://docs.wechatpy.org
"""
import json
import logging
import time
import requests

logger = logging.getLogger(__name__)

INVALID_CREDENTIAL = 4010


class SessionStorage(object):

    def get(self, key, default=None):
        raise NotImplementedError()

    def set(self, key, value, ttl=None):
        raise NotImplementedError()

    def delete(self, key):
        raise NotImplementedError()

    def __getitem__(self, key):
        self.get(key)

    def __setitem__(self, key, value):
        self.set(key, value)

    def __delitem__(self, key):
        self.delete(key)


def to_text(value, encoding='utf-8'):
    """Convert value to unicode, default encoding is utf-8

    :param value: Value to be converted
    :param encoding: Desired encoding
    """
    if not value:
        return ''
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode(encoding)
    return str(value)


class RedisStorage(SessionStorage):

    def __init__(self, redis, prefix='jdy_session'):
        for method_name in ('get', 'set', 'delete'):
            assert hasattr(redis, method_name)
        self.redis = redis
        self.prefix = prefix

    def key_name(self, key):
        return '{0}:{1}'.format(self.prefix, key)

    def get(self, key, default=None):
        key = self.key_name(key)
        value = self.redis.get(key)
        if value is None:
            return default
        return json.loads(to_text(value))

    def set(self, key, value, ttl=None):
        if value is None:
            return
        key = self.key_name(key)
        value = json.dumps(value)
        self.redis.set(key, value, ex=ttl)

    def delete(self, key):
        key = self.key_name(key)
        self.redis.delete(key)


class MemoryStorage(SessionStorage):

    def __init__(self):
        self._data = {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value, ttl=None):
        if value is None:
            return
        self._data[key] = value

    def delete(self, key):
        self._data.pop(key, None)


class JDYClientException(Exception):
    """Base exception for jdy"""

    def __init__(self, errcode, errmsg, client=None,
                 request=None, response=None):
        """
        :param errcode: Error code
        :param errmsg: Error message
        """
        self.errcode = errcode
        self.errmsg = errmsg
        self.client = client
        self.request = request
        self.response = response

    def __str__(self):
        if self.errcode:
            _repr = 'Error code: {code}, message: {msg}'.format(
                code=self.errcode,
                msg=self.errmsg
            )

        else:
            _repr = f'Error code: {self.errcode}, message: {self.errmsg} {self.response}'
        return _repr

    def __repr__(self):
        _repr = '{klass}({code}, {msg})'.format(
            klass=self.__class__.__name__,
            code=self.errcode,
            msg=self.errmsg
        )
        return _repr


class JDYClient(object):
    _http = requests.Session()

    API_BASE_URL = 'https://api.kingdee.com'
    GET_ACCESS_TOKEN = '/auth/user/access_token'  # 获得token

    VOUCHERS = '/jdyaccouting/voucherlist'  # 凭证
    ACCOUNTS = '/jdyaccouting/account'  # 科目

    # def __new__(cls, *args, **kwargs):
    #     self = super(JDYClient, cls).__new__(cls)
    #     api_endpoints = inspect.getmembers(self, _is_api_endpoint)
    #     for name, api in api_endpoints:
    #         api_cls = type(api)
    #         api = api_cls(self)
    #         setattr(self, name, api)
    #     return self

    def __init__(self, client_id, client_secret, username, password, account_id, db_id, session=None, access_token=None, timeout=None,
                 auto_retry=True):
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password

        self.account_id = account_id
        self.db_id = db_id

        self.expires_at = None
        self.session = session or MemoryStorage()
        self.timeout = timeout
        self.auto_retry = auto_retry

        if access_token:
            self.session.set(self.access_token_key, access_token)

    @property
    def access_token_key(self):
        return f'{self.client_id}_{self.username}_access_token'

    def _request(self, method, url_or_endpoint, auto_retry=True, **kwargs):
        if not url_or_endpoint.startswith(('http://', 'https://')):
            api_base_url = kwargs.pop('api_base_url', self.API_BASE_URL)
            url = '{base}{endpoint}'.format(
                base=api_base_url,
                endpoint=url_or_endpoint
            )
        else:
            url = url_or_endpoint

        if 'params' not in kwargs:
            kwargs['params'] = {}
        if isinstance(kwargs['params'], dict) and \
                'access_token' not in kwargs['params']:
            kwargs['params']['access_token'] = self.access_token

        # if isinstance(kwargs.get('data', ''), dict):
        #     body = json.dumps(kwargs['data'], ensure_ascii=False)
        #     body = body.encode('utf-8')
        #     kwargs['data'] = body

        # kwargs['timeout'] = kwargs.get('timeout', self.timeout)
        result_processor = kwargs.pop('result_processor', None)
        res = self._http.request(
            method=method,
            url=url,
            **kwargs
        )
        try:
            res.raise_for_status()
        except requests.RequestException as reqe:
            raise JDYClientException(
                errcode=None,
                errmsg=None,
                client=self,
                request=reqe.request,
                response=reqe.response
            )

        res = res.json()

        if 'code' not in res:
            raise JDYClientException(
                errcode=None,
                errmsg=str(res),
                client=self,
                request=kwargs,
                response=res,
            )

        return self._handle_result(
            res, method, url, result_processor, auto_retry=auto_retry, **kwargs
        )

    def _handle_result(self, res, method=None, url=None, result_processor=None, auto_retry=True, **kwargs):
        result = res

        if 'code' in result:
            result['code'] = int(result['code'])

        if 'code' in result and result['code'] != 0:
            errcode = result['code']
            errmsg = result.get('msg', errcode)
            if self.auto_retry and auto_retry and errcode in (INVALID_CREDENTIAL,):
                logger.info('Access token expired, fetch a new one and retry request')
                self.fetch_access_token()
                access_token = self.session.get(self.access_token_key)
                kwargs['params']['access_token'] = access_token
                return self._request(
                    method=method,
                    url_or_endpoint=url,
                    result_processor=result_processor,
                    auto_retry=False,
                    **kwargs
                )
            else:
                raise JDYClientException(
                    errcode,
                    errmsg,
                    client=self,
                    request=res.request,
                    response=res
                )

        return result if not result_processor else result_processor(result)

    def fetch_access_token(self):
        params = dict(
            username=self.username,
            password=self.password,
            client_id=self.client_id,
            client_secret=self.client_secret,
        )
        self._fetch_access_token(f'{self.API_BASE_URL}{self.GET_ACCESS_TOKEN}', params)

    def _fetch_access_token(self, url, params):
        """ The real fetch access token """
        logger.info('Fetching access token')
        res = self._http.get(
            url=url,
            params=params
        )
        try:
            res.raise_for_status()
        except requests.RequestException as reqe:
            raise JDYClientException(
                errcode=None,
                errmsg=None,
                client=self,
                request=reqe.request,
                response=reqe.response
            )
        result = res.json()
        if 'errcode' in result and result['errcode'] != 0:
            raise JDYClientException(
                result['errcode'],
                result['description'],
                client=self,
                request=res.request,
                response=res
            )

        expires_in = 7200
        if 'data' in result and 'expires_in' in result['data']:
            expires_in = result['data']['expires_in']
        self.session.set(
            self.access_token_key,
            result['data']['access_token'],
            expires_in
        )
        self.expires_at = int(time.time()) + expires_in
        return result

    @property
    def access_token(self):
        """ get access token """
        access_token = self.session.get(self.access_token_key)
        if access_token:
            if not self.expires_at:
                # user provided access_token, just return it
                return access_token

            timestamp = time.time()
            if self.expires_at - timestamp > 60:
                return access_token
        logger.debug(f'no jdy access_token find. fetch new one---->')
        self.fetch_access_token()
        return self.session.get(self.access_token_key)

    def accounting_get_accounts(self):
        response = self._request(
            'get',
            self.ACCOUNTS,
            params={
                'sid': self.account_id,
                'dbId': self.db_id,
            },
        )

        return response

    def accounting_get_voucher_list(self, from_period, to_period):
        """
        获得科目列表
        :return:
        """
        result_processor = None
        response = self._request(
            'post',
            self.VOUCHERS,
            params={
                'sid': self.account_id,
                'dbId': self.db_id,
            },
            json={
                'fromPeriod': from_period,
                'toPeriod': to_period,
            }
        )

        return response

