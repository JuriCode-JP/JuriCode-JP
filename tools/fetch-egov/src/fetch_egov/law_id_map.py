"""法令略称 ↔ e-Gov 法令 ID マッピング.

JuriCode-JP の docs/glossary.md と同期する. 新法令追加時は本ファイルにも
登録すること.
"""

from __future__ import annotations

# 略称 → e-Gov 法令ID(13桁の標準フォーマット、または特例)
# 出典: JuriCode-JP/docs/glossary.md
LAW_ID_MAP: dict[str, str] = {
    # 憲法
    "kenpou": "321CONSTITUTION",
    "constitution": "321CONSTITUTION",
    # 刑事関連
    "keihou": "140AC0000000045",
    "penal-code": "140AC0000000045",
    "keiji-soshou-hou": "323AC0000000131",
    "code-of-criminal-procedure": "323AC0000000131",
    "keisatsu-hou": "329AC0000000162",
    "police-act": "329AC0000000162",
    "keisatsukan-shokumu-shikkou-hou": "323AC0000000136",
    "police-duties-execution-act": "323AC0000000136",
    "keihanzai-hou": "323AC0000000039",
    "minor-offenses-act": "323AC0000000039",
    "stalker-kisei-hou": "412AC0100000081",
    "anti-stalking-act": "412AC0100000081",
    # 民事・商事
    "minpou": "129AC0000000089",
    "civil-code": "129AC0000000089",
    "shouhou": "132AC0000000048",
    "commercial-code": "132AC0000000048",
    "kaisha-hou": "417AC0000000086",
    "companies-act": "417AC0000000086",
    # 税法 (Phase 1 拡張: 税理士向け)
    "kokuzei-tsuusoku-hou": "337AC0000000066",
    "act-on-general-rules-for-national-taxes": "337AC0000000066",
    "houjin-zei-hou": "340AC0000000034",
    "corporation-tax-act": "340AC0000000034",
    "shotoku-zei-hou": "340AC0000000033",
    "income-tax-act": "340AC0000000033",
    "shouhi-zei-hou": "363AC0000000108",
    "consumption-tax-act": "363AC0000000108",
    # 税法 追加 (2026-05-20)
    "souzoku-zei-hou": "325AC0000000073",
    "inheritance-tax-act": "325AC0000000073",
    "chihou-zei-hou": "325AC0000000226",
    "local-tax-act": "325AC0000000226",
    # 警察柱 拡張 (2026-05-20): 道路交通法
    "douro-koutsuu-hou": "335AC0000000105",
    "road-traffic-act": "335AC0000000105",
    # その他
    "dokusen-kinshi-hou": "322AC0000000054",
    "antimonopoly-act": "322AC0000000054",
    "kojin-jouhou-hogo-hou": "415AC0000000057",
    "personal-information-protection-act": "415AC0000000057",
    # 行政柱 拡張 (2026-05-21): AI ガバナンス・公文書・情報公開・公務員
    "koubunsho-kanri-hou": "421AC0000000066",
    "public-records-management-act": "421AC0000000066",
    "jouhou-koukai-hou": "411AC0000000042",
    "act-on-access-to-information-held-by-administrative-organs": "411AC0000000042",
    "kokka-koumuin-hou": "322AC0000000120",
    "national-public-service-act": "322AC0000000120",
    "chihou-koumuin-hou": "325AC0000000261",
    "local-public-service-act": "325AC0000000261",
    "digital-shakai-keisei-kihon-hou": "503AC0000000035",
    "digital-society-formation-basic-act": "503AC0000000035",
    # 警察柱 拡張 (2026-05-21): 風営法・犯罪収益移転防止法
    "fueihou": "323AC0000000122",
    "act-on-control-and-improvement-of-amusement-business": "323AC0000000122",
    "hanzai-shueki-iten-boushi-hou": "419AC0000000022",
    "act-on-prevention-of-transfer-of-criminal-proceeds": "419AC0000000022",
    # Phase 3 先取り (2026-05-21): 労働基準法
    "roudou-kijun-hou": "322AC0000000049",
    "labor-standards-act": "322AC0000000049",
    # 2026-05-21 lawqa_jp 対応: e-Gov 取得可能 13 法令を一気投入
    # 商事 (Phase 2): 金商法本体 + 関連内閣府令・施行令 計 10 件
    "kinsho-hou": "323AC0000000025",
    "financial-instruments-and-exchange-act": "323AC0000000025",
    "kinsho-hou-shikkourei": "340CO0000000321",
    "kinsho-shikkourei": "340CO0000000321",
    "kigyou-kaiji-furei": "348M50000040005",
    "koukai-kaitsuke-furei": "402M50000040038",
    "kinsho-teigi-furei": "405M50000040014",
    "kinsho-kachoukin-furei": "417M60000002017",
    "kinsho-gyou-furei": "419M60000002052",
    "yuukashouken-kisei-furei": "419M60000002059",
    "shouken-jouhou-furei": "420M60000002078",
    "juuyou-jouhou-furei": "429M60000002054",
    # 民事 (Phase 1 拡張): 借地借家法
    "shakuchi-shakka-hou": "403AC0000000090",
    "land-and-house-lease-act": "403AC0000000090",
    # 医薬品・医療機器 (Phase 3 新規 pharma): 薬機法 + 施行規則
    "yakkihou": "335AC0000000145",
    "act-on-securing-quality-efficacy-safety-of-pharmaceuticals": "335AC0000000145",
    "yakkihou-shikoukisoku": "336M50000100001",
}


def resolve_law_id(name_or_id: str) -> str:
    """略称または法令IDを受け取り、正規の法令IDを返す.

    Args:
        name_or_id: 略称(例: "keihou")または法令ID(例: "140AC0000000045").
            すでに法令IDの形式なら、そのまま返す.

    Returns:
        e-Gov 法令ID.

    Raises:
        KeyError: 略称が `LAW_ID_MAP` にない場合.

    Examples:
        >>> resolve_law_id("keihou")
        '140AC0000000045'
        >>> resolve_law_id("140AC0000000045")
        '140AC0000000045'
    """
    # 法令IDっぽい形式(英数 13 桁前後)ならそのまま返す
    if name_or_id.isalnum() and len(name_or_id) >= 13:
        return name_or_id
    # 略称マップから引く(小文字化して検索)
    key = name_or_id.lower()
    if key in LAW_ID_MAP:
        return LAW_ID_MAP[key]
    raise KeyError(
        f"Unknown law name or ID: {name_or_id!r}. "
        f"Register it in fetch_egov/law_id_map.py and docs/glossary.md."
    )
