"""Python client for the XCREENER XQL HTTP API.

from xcreener import Xcreener

xc = Xcreener()  # reads XCREENER_API_KEY

query = '''
market = "CRYPTO"
timeframe = h1
columns = [rsi(14), volume]
sort = volume desc
limit = 5
rsi(14) < 30 and close > d::sma(200)
'''

for match in xc.run(query):
    print(match.symbol, match["rsi(14)"])
"""

from ._version import __version__
from .client import DEFAULT_BASE_URL, Xcreener
from .errors import (
    AuthenticationError,
    QuotaExceeded,
    TransportError,
    UpstreamError,
    XcreenerError,
    XQLError,
    XQLPlanError,
    XQLSyntaxError,
)
from .models import (
    Explanation,
    Match,
    Plan,
    Position,
    Quota,
    RateLimit,
    ResultSet,
    Source,
    SupportsXQL,
    ValidationResult,
    XQLErrorDetail,
)

__all__ = [
    "Xcreener",
    "DEFAULT_BASE_URL",
    "__version__",
    # errors
    "XcreenerError",
    "AuthenticationError",
    "QuotaExceeded",
    "XQLError",
    "XQLSyntaxError",
    "XQLPlanError",
    "UpstreamError",
    "TransportError",
    # models
    "SupportsXQL",
    "ValidationResult",
    "XQLErrorDetail",
    "Position",
    "Plan",
    "Source",
    "Explanation",
    "Match",
    "ResultSet",
    "Quota",
    "RateLimit",
]
