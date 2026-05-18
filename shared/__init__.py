"""Cross-cutting libraries shared across Spine subsystems.

Regular package (not namespace) so pytest's rootdir discovery stops at
the ``shared/`` boundary instead of inserting ``shared/`` on ``sys.path``
— that prevents ``shared/secrets/`` from shadowing the stdlib ``secrets``
module (which Starlette / FastAPI rely on via ``from secrets import
token_hex``).
"""
