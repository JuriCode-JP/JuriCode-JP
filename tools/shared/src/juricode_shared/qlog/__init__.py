"""juricode_shared.qlog -- question-log persistence layer (Phase A).

Why: search-ui の質問ログ 4 原材料 (質問文 + feedback + click + dwell) を SQLite に
記録する永続化レイヤ. server.py から SQLite I/O を分離し, server 起動なしで
単体テスト可能にする.
"""
