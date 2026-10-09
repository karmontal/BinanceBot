# BinanceBot — بوتات تداول متعددة الاستراتيجيات على Binance

مجموعة بوتات تداول **Spot** على باينانس، كل بوت باستراتيجية مختلفة وبميزانية مستقلة، وكلهم **بيشتغلوا مع بعض بشكل متوازي** عشان نقارن بيناتهم ونختار الأفضل.

- 🧪 **Paper Trading** (افتراضي): أسعار حقيقية حية، فلوس وهمية، بدون API keys.
- 📊 **Backtest**: نفس منطق البوت بالضبط على بيانات تاريخية.
- 📈 **تقارير مقارنة**: ربح، تراجع، Sharpe، Win%، Profit Factor...
- 🔒 **Testnet / Live**: جاهز للتحويل لاحقاً، بس مقفول بالافتراضي.

> ⚠️ التداول فيه مخاطرة. هاد مشروع تجريبي، استخدمه على مسؤوليتك.

## الاستراتيجيات

| الاستراتيجية | النوع | الشرح |
|---|---|---|
| `buy_and_hold` | معيار مقارنة | [docs/strategies/buy_and_hold.md](docs/strategies/buy_and_hold.md) |
| `sma_crossover` | تتبّع اتجاه | [docs/strategies/sma_crossover.md](docs/strategies/sma_crossover.md) |
| `ema_trend` | تتبّع اتجاه + فلتر | [docs/strategies/ema_trend.md](docs/strategies/ema_trend.md) |
| `rsi_reversion` | ارتداد | [docs/strategies/rsi_reversion.md](docs/strategies/rsi_reversion.md) |
| `bollinger_reversion` | ارتداد | [docs/strategies/bollinger_reversion.md](docs/strategies/bollinger_reversion.md) |
| `macd_cross` | زخم | [docs/strategies/macd_cross.md](docs/strategies/macd_cross.md) |
| `donchian_breakout` | اختراق | [docs/strategies/donchian_breakout.md](docs/strategies/donchian_breakout.md) |
| `supertrend` | تتبّع اتجاه (تقلّب) | [docs/strategies/supertrend.md](docs/strategies/supertrend.md) |

**كيف نقيّم ونختار:** [docs/evaluation.md](docs/evaluation.md)
**التشغيل على سيرفر بـ Docker:** [docs/deploy-docker.md](docs/deploy-docker.md)

## التثبيت

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```
بحتاج Python 3.9 أو أحدث.

## الاستخدام

### 1. شوف الاستراتيجيات المتوفرة
```bash
python main.py strategies
```

### 2. باك تست لكل البوتات
```bash
python main.py backtest --days 180
python main.py backtest --start 2024-01-01 --end 2024-06-30
python main.py backtest --days 365 --interval 4h   # كل البوتات على فريم 4 ساعات
python main.py backtest --days 365 --symbol ETHUSDT
python main.py backtest --only sma_cross_20_50,supertrend_10_3
python main.py backtest --synthetic 3000   # بيانات وهمية، بدون إنترنت (للتجربة بس)
```
الباك تست بينزّل شموع زيادة قبل تاريخ البداية عشان تكون المؤشرات (مثل EMA 200) جاهزة من أول يوم، وما بيتداول عليها.
بيطبع جدول مقارنة مرتّب، وبيحفظ النتائج بـ `reports/backtest_<التاريخ>/` (ملخص + كل صفقات كل بوت CSV).

### 3. تشغيل البوتات Paper بشكل متوازي
```bash
python main.py run
```
- كل بوت بـ thread مستقل وبميزانية مستقلة (`starting_balance`).
- كل 30 ثانية بيشيك السعر (للـ stop loss / take profit) وكل ما تسكّر شمعة جديدة بيقيّم الاستراتيجية.
- كل ساعة بيطبع جدول مقارنة. `Ctrl+C` للإيقاف.
- الحالة محفوظة بـ `data/bots.db` (SQLite)، فإذا وقّفته ورجعت شغّلته **بيكمّل من مطرح ما وقف**.

```bash
python main.py run --only rsi_reversion_14,macd_cross   # بوتات محددة بس
python main.py run --reset all                           # بداية من الصفر (بيمسح السجل)
python main.py run --reset macd_cross                    # تصفير بوت واحد
```

> لازم يضل شغّال 24/7 عشان النتائج تكون صح، والأفضل على VPS.
> **التشغيل بـ Docker على VPS (مثلاً Hostinger):** [docs/deploy-docker.md](docs/deploy-docker.md)
> ```bash
> docker compose up -d --build                     # تشغيل بالخلفية 24/7
> docker compose exec bot python main.py report    # التقرير
> docker compose logs -f --tail 100                # الـ logs
> ```

### 4. التقرير بأي وقت (حتى والبوتات شغالة)
```bash
python main.py report
python main.py report --csv reports/paper_week1.csv
```

## الإعدادات (`config.yaml`)

```yaml
mode: paper                 # paper | testnet | live
defaults:                   # بتنطبق على كل البوتات
  symbol: BTCUSDT
  interval: 1h              # 1m 5m 15m 1h 4h 1d ...
  starting_balance: 1000    # ميزانية كل بوت بالـ USDT
  position_size_pct: 100    # كم % من رأس مال البوت بكل صفقة
  stop_loss_pct: null       # مثلاً 3
  take_profit_pct: null     # مثلاً 6
  trailing_stop_pct: null   # مثلاً 4
  trend_filter_ema: null    # مثلاً 200: ما بيشتري إلا إذا السعر فوق EMA(200) لنفس الفريم
bots:
  - name: sma_cross_20_50   # اسم فريد
    strategy: sma_crossover
    params: {fast: 20, slow: 50}
  - name: supertrend_eth_4h
    strategy: supertrend
    symbol: ETHUSDT         # أي إعداد ممكن يتغيّر لكل بوت لحاله
    interval: 4h
    stop_loss_pct: 4
```
- بتقدر تحط نفس الاستراتيجية أكثر من مرة بمعاملات مختلفة وتقارنهم.
- `enabled: false` لإيقاف بوت مؤقتاً.
- إذا `api.binance.com` محجوب عندك: `market_data_url: https://data-api.binance.vision`

## التحويل لـ Live

**ما تحوّل لـ live إلا بعد ما تكون جرّبت paper لفترة كافية.** الترتيب الصح:

### أ) Testnet (فلوس وهمية بس أوامر حقيقية على باينانس)
1. اعمل حساب وAPI key على https://testnet.binance.vision
2. ```bash
   export BINANCE_TESTNET_API_KEY=...
   export BINANCE_TESTNET_API_SECRET=...
   ```
3. بالـ config: `mode: testnet` (أو `mode: testnet` لبوت معين بس).

### ب) Live (فلوس حقيقية)
1. اعمل API key على باينانس مع صلاحية **Spot Trading فقط**. **لا تفعّل Withdrawals أبداً**، وفعّل IP whitelist.
2. ```bash
   export BINANCE_API_KEY=...
   export BINANCE_API_SECRET=...
   export BINANCE_LIVE_CONFIRM=YES     # قفل أمان، بدونه البوت ما بيشتغل live
   ```
3. بالـ config خلّي بس البوت اللي اخترته `mode: live` وبميزانية صغيرة للبداية، مثلاً:
   ```yaml
   - name: supertrend_live
     strategy: supertrend
     mode: live
     starting_balance: 50
     stop_loss_pct: 4
   ```

ملاحظات الـ live:
- البوت بيستخدم **Market orders**.
- كل بوت بيتعامل مع "حساب فرعي افتراضي" بحدود `starting_balance` تبعه، وما ببيع إلا الكمية اللي هو اشتراها. قبل التشغيل بيتأكد إنه رصيد الحساب بيغطي مجموع ميزانيات البوتات.
- لا تتداول يدوياً بنفس العملة بنفس الحساب وقت البوت شغال.
- ما بتنحط أوامر stop على المنصة نفسها؛ البوت بيراقب السعر كل `poll_seconds`، فلازم يضل شغّال.

## بنية المشروع

```
main.py                      # CLI: strategies / backtest / run / report
config.yaml                  # تعريف البوتات
Dockerfile, docker-compose.yml, .env.example
binancebot/
  strategies/                # كل استراتيجية بملف (أضف استراتيجيتك هون)
  indicators.py              # SMA, EMA, RSI, Bollinger, MACD, ATR, Supertrend...
  bot.py                     # منطق البوت: إشارات + stop loss / take profit / trailing
  broker.py                  # PaperBroker (محاكاة) + BinanceBroker (حقيقي)
  exchange.py                # Binance REST client
  runner.py                  # تشغيل البوتات بالتوازي
  backtest.py                # باك تست بنفس منطق البوت
  metrics.py / report.py     # مقاييس الأداء وجداول المقارنة
  storage.py                 # SQLite
docs/
  strategies/*.md            # شرح كل استراتيجية
  evaluation.md              # كيف نقيّم ونختار
tests/
```

## إضافة استراتيجية جديدة
1. اعمل ملف بـ `binancebot/strategies/my_strategy.py`:
   ```python
   from .. import indicators as ind
   from ..models import Signal
   from .base import Strategy, closes

   class MyStrategy(Strategy):
       name = "my_strategy"
       default_params = {"period": 14}

       @property
       def min_candles(self):
           return self.params["period"] + 2

       def generate_signal(self, candles, in_position):
           ...
           return Signal.HOLD   # أو Signal.BUY / Signal.SELL
   ```
2. سجّلها بـ `binancebot/strategies/__init__.py`.
3. أضف ملف شرح بـ `docs/strategies/my_strategy.md` وبوت بالـ `config.yaml`.

## الاختبارات
```bash
pip install pytest
python -m pytest
```
