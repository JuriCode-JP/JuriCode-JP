"""fetch-egov -- e-Gov 法令API v2 クライアント.

JuriCode-JP のデータ取得層. e-Gov 法令API v2 (https://laws.e-gov.go.jp/api/2/)
から法令 XML を取得し、ローカルキャッシュに保存する.

利用側は submodule から直接 import すること (FU-506: top-level import は
httpx 等の heavy deps を --help 実行時にも load するため廃止):
    from fetch_egov.client import EGovClient
    from fetch_egov.cache import FileCache
    from fetch_egov.law_id_map import LAW_ID_MAP, resolve_law_id
    from fetch_egov.models import LawData, LawMetadata

または CLI で:
    $ uv run fetch-egov get-law keihou
    $ uv run fetch-egov get-article keihou 36
"""

__version__ = "0.1.0"
