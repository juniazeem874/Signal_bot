# Sirf GOLD TwelveData se, baaki crypto Binance se
from config import GOLD_PAIR, CRYPTO_PAIRS, FOREX_PAIRS

def fetch_all_pairs_data():
    """
    Returns list of indicator bundles ready for AI.
    Crypto  → Binance (no quota)
    Forex   → Binance me nahi hain, is liye unhe HOLD pe rakhna
              ya free source (exchangerate) se lena.
    Gold    → TwelveData (sirf ye 1 call per 5 min = 288/day ✓ within 800)
    """
    bundles = []
    for sym in CRYPTO_PAIRS:
        bundles.append(build_bundle_binance(sym))
    for sym in FOREX_PAIRS:
        bundles.append(build_bundle_forex_free(sym))  # yfinance/er-api
    bundles.append(build_bundle_twelvedata(GOLD_PAIR))   # ONLY gold
    return bundles