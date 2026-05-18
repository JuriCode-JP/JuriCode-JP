"""fetch-egov — e-Gov 法令API v2 クライアント.

JuriCode-JP のデータ取得層. e-Gov 法令API v2 (https://laws.e-gov.go.jp/api/2/)
から法令 XML を取得し、ローカルキャッシュに保存する.

主な使い方:
    >>> from fetch_egov import EGovClient, FileCache
    >>> client = EGovClient(cache=FileCache("cache/"))
    >>> xml = client.get_law("140AC0000000045")  # 刑法
    >>> xml = client.get_law("keihou")  # 略称でも取得可能

または CLI で:
    $ uv run fetch-egov get-law keihou
    $ uv run fetch-egov get-article keihou 36
"""

from fetch_egov.cache import FileCache
from fetch_egov.client import EGovClient
from fetch_egov.law_id_map import LAW_ID_MAP, resolve_law_id
from fetch_egov.models import LawData, LawMetadata

__version__ = "0.1.0"

__all__ = [
    "EGovClient",
    "FileCache",
    "LAW_ID_MAP",
    "resolve_law_id",
    "LawMetadata",
    "LawData",
    "__version__",
]
