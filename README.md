# jdy_sdk
A simple jingdouyun SDK DEMO

一个简单的精斗云SDK模板

支持Redis 存储access_token

受到Wechatpy启发，  thanks to @messense  http://docs.wechatpy.org

具备超时自动重新获取access_token功能

-------------------------------

使用样例

redis_session = RedisStorage(redis) # 这里传入redis的对象

jdy_client = JDYClient(client_id='XX', client_secret='XX', username='XX', password='XX', account_id='XX', db_id='XX', session = redis_session)

jdy_client.accounting_get_accounts()



------------------------
只是个样例，需要添加更多接口的请自行编辑
仿照accounting_get_accounts 即可
